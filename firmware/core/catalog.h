/* The play catalogue: which tags the brick knows, and what each one sounds
 * and looks like. It is data, not code. tools/build_catalog.mjs packs
 * site/data/tags.json and sounds.json into this binary layout, and the brick
 * reads it from a flash partition, so adding a tag never needs a firmware
 * rebuild.
 *
 * All multi-byte fields are little-endian.
 *
 *   header (16 bytes)   "OPBC", version, n_tags, n_profiles, n_patches,
 *                       n_segments (u16), sys_patch[4], reserved[2]
 *   tags      x 36      len, kind, profile, flags, r, g, b, reserved,
 *                       crc_a (u32), crc_b (u32), name[20]
 *   profiles  x 32      patch[16], anim[16], indexed by event
 *   patches   x 4       first_segment (u16), n_segments, flags
 *   segments  x 12      wave, volume, f0 (u16), f1 (u16), ms (u16),
 *                       attack_ms, release_ms/4, vibrato_hz, vibrato_depth
 */
#ifndef OPB_CATALOG_H
#define OPB_CATALOG_H

#include <stdint.h>

#define CATALOG_MAX_BYTES 8192
#define CATALOG_VERSION   1

enum {
    EV_PLACE, EV_REMOVE, EV_SHAKE, EV_SWING, EV_TILT_L, EV_TILT_R, EV_ROLL, EV_IMPACT,
    EV_THROW, EV_RED, EV_GREEN, EV_BLUE, EV_HIT, EV_DAMAGED, EV_DESTROYED, EV_AMBIENT,
    EV_COUNT
};

enum { SYS_BOOT, SYS_LOW_BATTERY, SYS_UNKNOWN_TAG, SYS_SLEEP, SYS_COUNT };

enum { KIND_UNKNOWN, KIND_IDENTITY, KIND_ITEM };

#define TAG_FLAG_COMBAT 0x01   /* fires on red, takes hits from other bricks */
#define PATCH_FLAG_LOOP 0x01
#define PATCH_NONE      0xFF

typedef struct {
    uint8_t  len, kind, profile, flags;
    uint8_t  r, g, b;
    uint32_t crc_a, crc_b;
    char     name[21];
} tag_info_t;

typedef struct {
    uint8_t  wave, volume;
    uint16_t f0, f1, ms;
    uint8_t  attack_ms, release_ms4, vib_hz, vib_depth;
} segment_t;

int  catalog_load(void);                 /* 0 on success */
int  catalog_tag_count(void);
void catalog_tag(int index, tag_info_t *out);

/* Find a tag by payload length and CRC-32. Returns the index, or -1.
 * *exact is set when the CRC matched, cleared when only the length did. */
int  catalog_find(uint8_t len, uint32_t crc, int *exact);

uint8_t catalog_event_patch(int profile, int event);
uint8_t catalog_event_anim(int profile, int event);
uint8_t catalog_sys_patch(int which);

/* Returns the number of segments in the patch (0 if it does not exist). */
int  catalog_patch(int patch, int *flags);
void catalog_segment(int patch, int index, segment_t *out);
uint32_t catalog_patch_ms(int patch);

#endif
