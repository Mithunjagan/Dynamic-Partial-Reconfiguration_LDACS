/* Real Cortex-A9 Gray-QAM digital loopback, added to the existing UART bridge.
 * No RF, OFDM, ADC/DAC, channel estimation, or PL modem is claimed.
 * LDM1: bps:u8, bit_count:u16, one-byte-per-bit input.
 * LDMR: bps:u8, bits:u16, symbols:u16, gt_hz:u32, map_ticks:u64,
 *       demap_ticks:u64, interleaved signed I/Q bytes, recovered bit bytes.
 */
static uint8_t modem_bits[29304], modem_recovered[29304];
static int8_t modem_i[14652], modem_q[14652];

static void axiom_registers(void) {
#if ARCH == 2
    error();
#else
    static const uint32_t addresses[10] = {
        0x40000004, 0x40000024, 0x4000002C, 0x40000030, 0x40000034,
        0x40000038, 0x4000001C, 0x40000020, 0x40400004, 0x40400034
    };
    /* Latch before transmitting, entirely outside decoder benchmark timers. */
    uint32_t values[10];
    for (unsigned i = 0; i < 10; i++) values[i] = rreg(addresses[i]);
    uart_putc('L'); uart_putc('D'); uart_putc('R'); uart_putc('R');
    uart_putc(ARCH); uart_putc(10);
    for (unsigned i = 0; i < 10; i++) {
        uart_put_u32(addresses[i]); uart_put_u32(values[i]);
    }
#endif
}

static unsigned gray_to_binary(unsigned value) {
    unsigned binary = value;
    while (value >>= 1) binary ^= value;
    return binary;
}

static void axiom_modem(void) {
    unsigned bps = uart_getc(), count = uart_get_u16();
    if ((bps != 2 && bps != 4 && bps != 6) || !count || count > 29304 || count % bps) {
        error(); return;
    }
    uart_read_buf(modem_bits, count);
    for (unsigned j = 0; j < count; j++) if (modem_bits[j] > 1) { error(); return; }
    unsigned axis_bits = bps / 2, levels = 1u << axis_bits, symbols = count / bps;
    uint64_t begin = ticks();
    for (unsigned s = 0; s < symbols; s++) {
        unsigned gi = 0, gq = 0;
        for (unsigned k = 0; k < axis_bits; k++) {
            gi = (gi << 1) | modem_bits[s * bps + k];
            gq = (gq << 1) | modem_bits[s * bps + axis_bits + k];
        }
        modem_i[s] = (int8_t)((int)(2 * gray_to_binary(gi)) - (int)(levels - 1));
        modem_q[s] = (int8_t)((int)(2 * gray_to_binary(gq)) - (int)(levels - 1));
    }
    uint64_t map_ticks = ticks() - begin;
    begin = ticks();
    for (unsigned s = 0; s < symbols; s++) {
        unsigned bi = (unsigned)((int)modem_i[s] + (int)levels - 1) / 2;
        unsigned bq = (unsigned)((int)modem_q[s] + (int)levels - 1) / 2;
        unsigned gi = bi ^ (bi >> 1), gq = bq ^ (bq >> 1);
        for (unsigned k = 0; k < axis_bits; k++) {
            modem_recovered[s * bps + k] = (gi >> (axis_bits - k - 1)) & 1;
            modem_recovered[s * bps + axis_bits + k] = (gq >> (axis_bits - k - 1)) & 1;
        }
    }
    uint64_t demap_ticks = ticks() - begin;
    uart_putc('L'); uart_putc('D'); uart_putc('M'); uart_putc('R');
    uart_putc(bps); uart_put_u16(count); uart_put_u16(symbols); uart_put_u32(timer_hz());
    put64(map_ticks); put64(demap_ticks);
    for (unsigned s = 0; s < symbols; s++) { uart_putc((uint8_t)modem_i[s]); uart_putc((uint8_t)modem_q[s]); }
    uart_write_buf(modem_recovered, count);
}
