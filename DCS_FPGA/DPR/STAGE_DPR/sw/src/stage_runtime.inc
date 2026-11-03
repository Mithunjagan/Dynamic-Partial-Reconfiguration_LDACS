/* Stage-specific protocol; buffered frames never overlap PCAP image slots.
 * At most 64 frames, each in [0x06000000+i*65536, +65536).
 * coded input: +0; block-deinterleaved bytes: +0x8000;
 * raw RS output: +0x9000; final payload: +0xa000.
 */
#define BATCH_MAX 64
#define BATCH_BASE 0x06000000u
static unsigned batch_count, batch_phase, batch_rate, batch_coded, batch_steps;
static unsigned batch_cw, batch_n, batch_payload;
static uint32_t batch_crc[BATCH_MAX];
static uint64_t helical_ticks, vit_bdi_ticks, rs_ticks, derand_ticks, compute_ticks;
static uint32_t batch_corr,batch_fail,batch_bad;
static uint8_t *frame_at(unsigned i,unsigned offset){return (uint8_t *)(uintptr_t)(BATCH_BASE+i*65536u+offset);}
static void copy_bytes(uint8_t *d,const volatile uint8_t *s,unsigned n){for(unsigned i=0;i<n;i++)d[i]=s[i];DPR_BARRIER();}
static int stage_ready(unsigned id){return !pcap_fault&&rreg(DEC_BASE+0x9c)==0x53544731u&&rreg(DEC_BASE+0x88)==id&&!rreg(DEC_BASE+0x80);}
static void batch_load(void){
 unsigned rate=uart_getc(),coded=uart_get_u16(),payload=uart_get_u16();
 unsigned steps=uart_get_u16(),cw=uart_get_u16(),n=uart_getc(),count=uart_get_u16();
 if(pcap_fault||!count||count>BATCH_MAX||!valid(rate,coded,steps,cw,n,payload)) {dpr_error(20);return;}
 batch_phase=0;batch_count=count;batch_rate=rate;batch_coded=coded;
 batch_payload=payload;batch_steps=steps;batch_cw=cw;batch_n=n;
 helical_ticks=0;vit_bdi_ticks=0;rs_ticks=0;derand_ticks=0;compute_ticks=0;
 batch_corr=0;batch_fail=0;batch_bad=0;
 dpr_magic("RDY1");
 for(unsigned i=0;i<count;i++){
  batch_crc[i]=get32();uart_read_buf(helical_buf,coded);
  uint64_t a=ticks();helical_deinterleave(helical_buf,frame_at(i,0),coded);
  helical_ticks+=ticks()-a;
  /* Bound UART flow while the PS permutes a frame; the host waits for this ACK. */
  dpr_magic("SBF1");uart_put_u32(i);
 }
 batch_phase=1;dpr_magic("SBLA");uart_put_u32(count);uart_put_u32(timer_hz());put64(helical_ticks);
}
static int run_stage(unsigned id,unsigned frame){
 wreg(DEC_BASE+DEC_CTRL,3);for(volatile unsigned j=0;j<1000;j++);
 wreg(DEC_BASE+DEC_CTRL,0);wreg(DEC_BASE+DEC_RATE,batch_rate);
 wreg(DEC_BASE+DEC_N_STEPS,batch_steps);wreg(DEC_BASE+DEC_NUM_CW,batch_cw);wreg(DEC_BASE+DEC_RS_N,batch_n);
 dma_reset();
 unsigned nrs=batch_cw*batch_n;
 uint32_t source=(uint32_t)(uintptr_t)frame_at(frame,id?0x8000:0);
 return dma_transfer(source,id?nrs:batch_coded,DMA_RX_PHYS,id?batch_payload:nrs);
}
static void batch_viterbi(void){
 if(batch_phase!=1||!stage_ready(0)){dpr_error(21);return;}
 uint64_t a=ticks();batch_phase=0;
 for(unsigned i=0;i<batch_count;i++){
  if(run_stage(0,i)){pcap_fault=1;wreg(DEC_BASE+0x80,3);dpr_error(22);return;}
  copy_bytes(frame_at(i,0x8000),rx_buf,batch_cw*batch_n);
 }
 vit_bdi_ticks=ticks()-a;batch_phase=2;
 dpr_magic("SBVA");uart_put_u32(batch_count);put64(vit_bdi_ticks);
}
static void batch_rs(void){
 if(batch_phase!=2||!stage_ready(1)){dpr_error(23);return;}
 uint64_t start=ticks();batch_phase=0;
 for(unsigned i=0;i<batch_count;i++){
  uint64_t a=ticks();
  if(run_stage(1,i)){pcap_fault=1;wreg(DEC_BASE+0x80,3);dpr_error(24);return;}
  batch_corr+=rreg(DEC_BASE+DEC_RS_CORR);batch_fail+=rreg(DEC_BASE+DEC_RS_FAIL);
  copy_bytes(frame_at(i,0x9000),rx_buf,batch_payload);rs_ticks+=ticks()-a;
  a=ticks();derandomize(frame_at(i,0x9000),frame_at(i,0xa000),batch_payload);derand_ticks+=ticks()-a;
  if(crc32(frame_at(i,0xa000),batch_payload)!=batch_crc[i])batch_bad++;
 }
 compute_ticks=helical_ticks+vit_bdi_ticks+(ticks()-start);batch_phase=3;
 dpr_magic("SBRR");uart_put_u32(batch_count);uart_put_u32(batch_coded);uart_put_u32(batch_cw*batch_n);
 uart_put_u32(batch_payload);uart_put_u32(timer_hz());uart_put_u32(fabric_hz());
 uart_put_u32(batch_corr);uart_put_u32(batch_fail);uart_put_u32(batch_bad);uart_put_u32(batch_phase);
 put64(helical_ticks);put64(vit_bdi_ticks);put64(rs_ticks);put64(derand_ticks);put64(compute_ticks);
}
static void batch_trace(void){
 unsigned i=uart_get_u16();
 if(i>=batch_count||batch_phase<2){dpr_error(25);return;}
 dpr_magic("SBTR");uart_put_u32(batch_cw*batch_n);uart_put_u32(batch_phase==3?batch_payload:0);
 uart_write_buf(frame_at(i,0x8000),batch_cw*batch_n);
 if(batch_phase==3){uart_write_buf(frame_at(i,0x9000),batch_payload);uart_write_buf(frame_at(i,0xa000),batch_payload);}
}
void bridge_main(void){
 disable_caches();uart_init_115200();wreg(0xF8F00208,1);pl_clock_hz=fabric_hz();
 /* New static signature prevents booting this scheduler on the whole-chain family. */
 if(rreg(DEC_BASE+0x9c)==0x53544731u)wreg(DEC_BASE+0x80,0);
 for(;;){
  uint32_t magic=0;for(unsigned i=0;i<4;i++)magic=(magic<<8)|uart_getc();
  switch(magic){
   case 0x44505331:dpr_status();break;
   case 0x44505531:dpr_upload();break;
   case 0x44505231:dpr_switch();break;
   case 0x44534331:dpr_continuity();break;
   case 0x53424c31:batch_load();break;
   case 0x53425631:batch_viterbi();break;
   case 0x53425231:batch_rs();break;
   case 0x53425431:batch_trace();break;
   default:dpr_error(26);break;
  }
 }
}
