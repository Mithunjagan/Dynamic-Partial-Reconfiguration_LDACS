import ctypes,subprocess,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HARNESS=r"""
#include <stdint.h>
#define DPR_BARRIER() ((void)0)
#define DEC_BASE 0x40000000u
#define DEC_CTRL 0
#define DEC_RATE 8
#define DEC_N_STEPS 12
#define DEC_NUM_CW 16
#define DEC_RS_N 20
#define DEC_RS_CORR 28
#define DEC_RS_FAIL 32
#define DMA_RX_PHYS 0x00200000u
static unsigned pcap_fault,code,dma_calls,module_id,isolated,input_at,last_ctrl;
static uint8_t input[32],helical_buf[65536];static volatile uint8_t *rx_buf;
static uint32_t pl_clock_hz;
static uint32_t rreg(uint32_t a){return a==DEC_BASE+0x9c?0x53544731:a==DEC_BASE+0x88?module_id:a==DEC_BASE+0x80?isolated:0;}
static void wreg(uint32_t a,uint32_t b){if(a==DEC_BASE&&b)last_ctrl=b;}
static uint64_t ticks(void){return 1;}
static uint32_t timer_hz(void){return 100;}
static uint32_t fabric_hz(void){return 50;}
static void dpr_error(unsigned c){code=c;}
static void dpr_magic(const char *s){}
static void uart_put_u32(uint32_t x){}
static void put64(uint64_t x){}
static unsigned uart_getc(void){return input[input_at++];}
static unsigned uart_get_u16(void){unsigned a=uart_getc();return a|(uart_getc()<<8);}
static uint32_t get32(void){return 0;}
static void uart_read_buf(volatile uint8_t *p,unsigned n){}
static void uart_write_buf(const volatile uint8_t *p,unsigned n){}
static void helical_deinterleave(const uint8_t *a,uint8_t *b,unsigned n){}
static void derandomize(const uint8_t *a,uint8_t *b,unsigned n){}
static void dma_reset(void){}
static int dma_transfer(unsigned a,unsigned b,unsigned c,unsigned d){dma_calls++;return -1;}
static unsigned crc32(const uint8_t *a,unsigned n){return 0;}
static void disable_caches(void){}
static void uart_init_115200(void){}
static void dpr_status(void){}static void dpr_upload(void){}static void dpr_switch(void){}static void dpr_continuity(void){}
VALIDATOR
#include "stage_runtime.inc"
unsigned guard(unsigned which){
 code=0;last_ctrl=0;dma_calls=0;pcap_fault=0;module_id=0;isolated=0;batch_phase=0;input_at=0;
 if(which==0){batch_viterbi();}
 if(which==1){batch_phase=1;module_id=1;batch_rs();}
 if(which==2){batch_phase=1;module_id=1;batch_viterbi();}
 if(which==3){batch_phase=2;module_id=1;isolated=1;batch_rs();}
 if(which==4){for(unsigned i=0;i<32;i++)input[i]=0;input[10]=65;batch_load();}
 if(which==5){batch_count=1;batch_phase=1;batch_viterbi();}
 return code|(dma_calls<<16);
}
unsigned get_ctrl(void){return last_ctrl;}
"""
class Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  out=ROOT/'build/scheduler_test';out.mkdir(parents=True,exist_ok=True)
  source=(ROOT/'sw/src/uart_bridge.c').read_text();start=source.index('static int valid(');end=source.index('\n}',start)+2
  (out/'test.c').write_text(HARNESS.replace('VALIDATOR',source[start:end]))
  subprocess.run(['gcc','-O2','-shared','-I',str(ROOT/'sw/src'),str(out/'test.c'),'-o',str(out/'test.dll')],check=True)
  cls.lib=ctypes.CDLL(str(out/'test.dll'));cls.lib.guard.argtypes=[ctypes.c_uint];cls.lib.guard.restype=ctypes.c_uint
 def test_frame_reset_and_dma_fault(self):
  self.assertEqual(self.lib.guard(5),22|(1<<16));self.assertEqual(self.lib.get_ctrl(),3)
 def test_viterbi_before_input(self):self.assertEqual(self.lib.guard(0),21)
 def test_rs_before_viterbi(self):self.assertEqual(self.lib.guard(1),23)
 def test_wrong_rm(self):self.assertEqual(self.lib.guard(2),21)
 def test_isolated_slot(self):self.assertEqual(self.lib.guard(3),23)
 def test_oversized_or_invalid_batch(self):self.assertEqual(self.lib.guard(4),20)
if __name__=='__main__':unittest.main()
