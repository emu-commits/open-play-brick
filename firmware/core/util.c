#include <stdarg.h>
#include "util.h"
#include "hal.h"

static void put_num(char **p, char *end, uint32_t v, int base, int width, char pad)
{
    char tmp[12];
    int n = 0;
    do {
        int d = (int)(v % (uint32_t)base);
        tmp[n++] = (char)(d < 10 ? '0' + d : 'A' + d - 10);
        v /= (uint32_t)base;
    } while (v && n < (int)sizeof tmp);
    while (width-- > n && *p < end) *(*p)++ = pad;
    while (n && *p < end) *(*p)++ = tmp[--n];
}

void opb_logf(const char *fmt, ...)
{
    char buf[160];
    char *p = buf, *end = buf + sizeof buf - 1;
    va_list ap;
    va_start(ap, fmt);
    for (; *fmt && p < end; fmt++) {
        if (*fmt != '%') { *p++ = *fmt; continue; }
        fmt++;
        char pad = ' ';
        int width = 0;
        if (*fmt == '0') { pad = '0'; fmt++; }
        while (*fmt >= '0' && *fmt <= '9') width = width * 10 + (*fmt++ - '0');
        switch (*fmt) {
        case 's': { const char *s = va_arg(ap, const char *); while (*s && p < end) *p++ = *s++; break; }
        case 'c': *p++ = (char)va_arg(ap, int); break;
        case 'd': {
            int v = va_arg(ap, int);
            if (v < 0) { *p++ = '-'; v = -v; }
            put_num(&p, end, (uint32_t)v, 10, width, pad);
            break;
        }
        case 'u': put_num(&p, end, va_arg(ap, uint32_t), 10, width, pad); break;
        case 'x': put_num(&p, end, va_arg(ap, uint32_t), 16, width, pad); break;
        case '%': *p++ = '%'; break;
        default: break;
        }
    }
    va_end(ap);
    *p = 0;
    hal_log(buf);
}

uint32_t opb_crc32(const uint8_t *p, int n)
{
    uint32_t crc = 0xFFFFFFFFu;
    while (n-- > 0) {
        crc ^= *p++;
        for (int k = 0; k < 8; k++) crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
    }
    return ~crc;
}

uint32_t opb_isqrt(uint32_t v)
{
    uint32_t r = 0, bit = 1u << 30;
    while (bit > v) bit >>= 2;
    while (bit) {
        if (v >= r + bit) { v -= r + bit; r = (r >> 1) + bit; }
        else r >>= 1;
        bit >>= 2;
    }
    return r;
}
