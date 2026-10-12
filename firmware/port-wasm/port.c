/* WebAssembly port. Every hal_* function is imported from the emulator
 * (site/js/board.js), which turns it into pin activity on simulated chips.
 * This file only adds the few libc routines the core needs and a buffer for
 * incoming radio packets. */
#include <stddef.h>
#include <stdint.h>

void *memcpy(void *dst, const void *src, size_t n)
{
    uint8_t *d = dst;
    const uint8_t *s = src;
    while (n--) *d++ = *s++;
    return dst;
}

void *memset(void *dst, int c, size_t n)
{
    uint8_t *d = dst;
    while (n--) *d++ = (uint8_t)c;
    return dst;
}

int memcmp(const void *a, const void *b, size_t n)
{
    const uint8_t *x = a, *y = b;
    for (; n--; x++, y++) if (*x != *y) return *x - *y;
    return 0;
}

static uint8_t radio_rx[64];

__attribute__((export_name("fw_radio_buffer")))
uint8_t *fw_radio_buffer(void) { return radio_rx; }
