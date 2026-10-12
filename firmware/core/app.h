#ifndef OPB_APP_H
#define OPB_APP_H

#include <stdint.h>

#define FW_VERSION "0.1.0"

enum { ST_BOOT, ST_IDLE, ST_TAG_ACTIVE, ST_GESTURE, ST_CHARGING, ST_LOW_BATTERY, ST_SLEEP };

/* Debug probe. The emulator reads this to fill its status panel. It is a
 * fixed byte layout so a host can read it without knowing the compiler. */
typedef struct __attribute__((packed)) {
    uint8_t  state;          /*  0 */
    uint8_t  tag_present;    /*  1 */
    uint8_t  tag_index;      /*  2  catalogue index, 0xFF if not in the catalogue */
    uint8_t  tag_exact;      /*  3  1 if matched by CRC, 0 if by length only */
    uint8_t  tag_len;        /*  4 */
    uint8_t  tag_kind;       /*  5 */
    uint8_t  colour;         /*  6 */
    uint8_t  hits;           /*  7 */
    uint8_t  damaged;        /*  8 */
    uint8_t  charging;       /*  9 */
    uint8_t  soc;            /* 10 */
    uint8_t  last_event;     /* 11  0xFF if none yet */
    uint16_t mv;             /* 12 */
    int16_t  ax, ay, az;     /* 14 */
    uint32_t tag_crc;        /* 20 */
    uint8_t  uid[8];         /* 24 */
    char     tag_name[24];   /* 32 */
} fw_status_t;               /* 56 bytes */

void fw_init(void);
void fw_loop(void);
void fw_on_radio(const uint8_t *data, int len);
const fw_status_t *fw_status(void);

#endif
