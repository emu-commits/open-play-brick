#ifndef OPB_UTIL_H
#define OPB_UTIL_H

#include <stdint.h>
#include <stddef.h>

void *memcpy(void *dst, const void *src, size_t n);
void *memset(void *dst, int c, size_t n);
int   memcmp(const void *a, const void *b, size_t n);

/* printf-style logging to hal_log. Supports %s %d %u %x %02x %08x %c %%. */
void     opb_logf(const char *fmt, ...);

uint32_t opb_crc32(const uint8_t *p, int n);
uint32_t opb_isqrt(uint32_t v);

static inline uint16_t rd16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static inline uint32_t rd32(const uint8_t *p) { return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24); }

#endif
