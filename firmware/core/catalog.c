#include "catalog.h"
#include "hal.h"
#include "util.h"

#define HDR_SIZE  16
#define TAG_SIZE  36
#define PROF_SIZE 32
#define PAT_SIZE  4
#define SEG_SIZE  12

static uint8_t blob[CATALOG_MAX_BYTES];
static int n_tags, n_profiles, n_patches, n_segs;
static const uint8_t *tags, *profiles, *patches, *segs;

int catalog_load(void)
{
    n_tags = n_profiles = n_patches = n_segs = 0;
    if (hal_storage_read(0, blob, HDR_SIZE) != HDR_SIZE) return -1;
    if (memcmp(blob, "OPBC", 4) != 0 || blob[4] != CATALOG_VERSION) return -1;

    int tags_n = blob[5], prof_n = blob[6], pat_n = blob[7], seg_n = rd16(blob + 8);
    int total = HDR_SIZE + tags_n * TAG_SIZE + prof_n * PROF_SIZE + pat_n * PAT_SIZE + seg_n * SEG_SIZE;
    if (total > CATALOG_MAX_BYTES || prof_n == 0) return -1;
    if (hal_storage_read(HDR_SIZE, blob + HDR_SIZE, total - HDR_SIZE) != total - HDR_SIZE) return -1;

    tags = blob + HDR_SIZE;
    profiles = tags + tags_n * TAG_SIZE;
    patches = profiles + prof_n * PROF_SIZE;
    segs = patches + pat_n * PAT_SIZE;
    n_tags = tags_n; n_profiles = prof_n; n_patches = pat_n; n_segs = seg_n;
    opb_logf("Catalogue: %d tags, %d profiles, %d patches, %d bytes", n_tags, n_profiles, n_patches, total);
    return 0;
}

int catalog_tag_count(void) { return n_tags; }

void catalog_tag(int index, tag_info_t *out)
{
    const uint8_t *t = tags + index * TAG_SIZE;
    out->len = t[0]; out->kind = t[1]; out->profile = t[2]; out->flags = t[3];
    out->r = t[4]; out->g = t[5]; out->b = t[6];
    out->crc_a = rd32(t + 8); out->crc_b = rd32(t + 12);
    memcpy(out->name, t + 16, 20);
    out->name[20] = 0;
}

int catalog_find(uint8_t len, uint32_t crc, int *exact)
{
    int by_len = -1;
    for (int i = 0; i < n_tags; i++) {
        const uint8_t *t = tags + i * TAG_SIZE;
        if (t[0] != len) continue;
        if (crc && (rd32(t + 8) == crc || rd32(t + 12) == crc)) { *exact = 1; return i; }
        if (by_len < 0) by_len = i;
    }
    *exact = 0;
    return by_len;
}

uint8_t catalog_event_patch(int profile, int event)
{
    if (profile >= n_profiles) profile = 0;
    return profiles[profile * PROF_SIZE + event];
}

uint8_t catalog_event_anim(int profile, int event)
{
    if (profile >= n_profiles) profile = 0;
    return profiles[profile * PROF_SIZE + EV_COUNT + event];
}

uint8_t catalog_sys_patch(int which) { return n_profiles ? blob[10 + which] : PATCH_NONE; }

int catalog_patch(int patch, int *flags)
{
    if (patch >= n_patches) return 0;
    const uint8_t *p = patches + patch * PAT_SIZE;
    if (rd16(p) + p[2] > n_segs) return 0;
    if (flags) *flags = p[3];
    return p[2];
}

void catalog_segment(int patch, int index, segment_t *out)
{
    const uint8_t *s = segs + (rd16(patches + patch * PAT_SIZE) + index) * SEG_SIZE;
    out->wave = s[0]; out->volume = s[1];
    out->f0 = rd16(s + 2); out->f1 = rd16(s + 4); out->ms = rd16(s + 6);
    out->attack_ms = s[8]; out->release_ms4 = s[9]; out->vib_hz = s[10]; out->vib_depth = s[11];
}

uint32_t catalog_patch_ms(int patch)
{
    uint32_t ms = 0;
    int n = catalog_patch(patch, 0);
    for (int i = 0; i < n; i++) ms += rd16(segs + (rd16(patches + patch * PAT_SIZE) + i) * SEG_SIZE + 6);
    return ms;
}
