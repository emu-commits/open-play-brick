#include "output.h"
#include "catalog.h"
#include "hal.h"
#include "util.h"
#include "sintab.h"

/* ------------------------------------------------------------------ */
/* Synthesiser                                                        */
/* ------------------------------------------------------------------ */

#define VOICES       4
#define BLOCK        64
#define PHASE_PER_HZ 268435u   /* 2^32 / 16000 */

enum { WAVE_SINE, WAVE_SQUARE, WAVE_SAW, WAVE_TRIANGLE, WAVE_NOISE, WAVE_SILENCE };

typedef struct {
    uint8_t   active, patch, seg, n_seg, loop;
    segment_t s;
    uint32_t  pos, len, attack, release;
    uint32_t  phase, lfo, lfo_inc;
    int32_t   f_q16, f_step;
    int16_t   hold;
} voice_t;

static voice_t voices[VOICES];
static uint32_t lfsr = 0xACE1u;
static int master = 200;
static uint8_t next_voice = 1;

static void load_segment(voice_t *v)
{
    catalog_segment(v->patch, v->seg, &v->s);
    v->pos = 0;
    v->len = (uint32_t)v->s.ms * (SYNTH_RATE / 1000);
    if (v->len == 0) v->len = 1;
    v->attack = (uint32_t)v->s.attack_ms * (SYNTH_RATE / 1000);
    v->release = (uint32_t)v->s.release_ms4 * 4 * (SYNTH_RATE / 1000);
    v->f_q16 = (int32_t)v->s.f0 << 16;
    v->f_step = (((int32_t)v->s.f1 - (int32_t)v->s.f0) << 16) / (int32_t)v->len;
    v->lfo_inc = (uint32_t)v->s.vib_hz * PHASE_PER_HZ;
}

void synth_init(void)
{
    memset(voices, 0, sizeof voices);
    next_voice = 1;
}

void synth_play(int patch)
{
    int flags = 0;
    int n = catalog_patch(patch, &flags);
    if (n == 0) return;

    voice_t *v;
    if (flags & PATCH_FLAG_LOOP) {
        v = &voices[0];
    } else {
        v = &voices[next_voice];
        for (int i = 1; i < VOICES; i++) if (!voices[i].active) { v = &voices[i]; break; }
        if (v == &voices[next_voice]) next_voice = (uint8_t)(next_voice % (VOICES - 1) + 1);
    }
    v->patch = (uint8_t)patch;
    v->seg = 0;
    v->n_seg = (uint8_t)n;
    v->loop = (flags & PATCH_FLAG_LOOP) != 0;
    v->phase = 0;
    v->lfo = 0;
    v->hold = 0;
    load_segment(v);
    v->active = 1;
}

void synth_stop_ambient(void) { voices[0].active = 0; }
void synth_stop_all(void) { for (int i = 0; i < VOICES; i++) voices[i].active = 0; }
void synth_set_volume(int v) { master = v; }

int synth_busy(void)
{
    for (int i = 0; i < VOICES; i++) if (voices[i].active) return 1;
    return 0;
}

static int32_t voice_sample(voice_t *v)
{
    int32_t f = v->f_q16;
    v->f_q16 += v->f_step;
    if (v->s.vib_depth) {
        v->lfo += v->lfo_inc;
        f += (int32_t)(((int64_t)f * v->s.vib_depth * SINTAB[v->lfo >> 24]) >> 25);
    }
    if (f < 0) f = 0;
    uint32_t inc = (uint32_t)(((uint64_t)(uint32_t)f * PHASE_PER_HZ) >> 16);
    uint32_t before = v->phase;
    v->phase += inc;

    int32_t s;
    switch (v->s.wave) {
    case WAVE_SINE: {
        uint32_t i = v->phase >> 24, frac = (v->phase >> 16) & 0xFF;
        int32_t a = SINTAB[i], b = SINTAB[(i + 1) & 0xFF];
        s = a + (((b - a) * (int32_t)frac) >> 8);
        break;
    }
    case WAVE_SQUARE:   s = (v->phase & 0x80000000u) ? -18000 : 18000; break;
    case WAVE_SAW:      s = (((int32_t)(v->phase >> 16) - 32768) * 3) / 4; break;
    case WAVE_TRIANGLE: {
        int32_t p = (int32_t)(v->phase >> 15) - 65536;
        s = (p < 0 ? -p : p) - 32768;
        break;
    }
    case WAVE_NOISE:
        /* Sample-and-hold noise: the "frequency" sets how often it changes. */
        if (v->phase < before || inc > 0x7FFFFFFFu) {
            lfsr ^= lfsr << 13; lfsr ^= lfsr >> 17; lfsr ^= lfsr << 5;
            v->hold = (int16_t)(lfsr & 0xFFFF);
        }
        s = (v->hold * 3) / 4;
        break;
    default: s = 0; break;
    }

    int32_t env = 256;
    uint32_t left = v->len - v->pos;
    if (v->pos < v->attack) env = (int32_t)(v->pos * 256 / v->attack);
    if (left < v->release) {
        int32_t r = (int32_t)(left * 256 / v->release);
        if (r < env) env = r;
    }
    s = (s * (int32_t)v->s.volume * env) >> 16;

    if (++v->pos >= v->len) {
        if (++v->seg >= v->n_seg) {
            if (v->loop) v->seg = 0;
            else { v->active = 0; return s; }
        }
        load_segment(v);
    }
    return s;
}

int synth_oneshot_busy(void)
{
    for (int i = 1; i < VOICES; i++) if (voices[i].active) return 1;
    return 0;
}

void synth_fill(int deep)
{
    static int16_t block[BLOCK];
    /* A shallow queue keeps sounds prompt: about 50 ms from trigger to speaker. */
    int target = deep ? HAL_I2S_BUFFER - BLOCK : 768;

    for (int guard = 0; guard < 32 && HAL_I2S_BUFFER - hal_i2s_space() < target; guard++) {
        for (int i = 0; i < BLOCK; i++) {
            int32_t mix = 0;
            for (int k = 0; k < VOICES; k++) if (voices[k].active) mix += voice_sample(&voices[k]);
            mix = (mix * master) >> 9;
            if (mix > 32767) mix = 32767;
            if (mix < -32768) mix = -32768;
            block[i] = (int16_t)mix;
        }
        hal_i2s_write(block, BLOCK);
    }
}

/* ------------------------------------------------------------------ */
/* Pixels                                                             */
/* ------------------------------------------------------------------ */

#define FRAME_MS 40

typedef struct { uint8_t anim, r, g, b; uint32_t start, until; } layer_t;

static layer_t base, over;
static uint8_t frame[LED_COUNT * 3], sent[LED_COUNT * 3];
static uint8_t dirty;
static int brightness = 140;
static uint32_t next_frame, led_now;
static uint32_t sparkle = 0xBEEF1234u;

void leds_init(void)
{
    memset(&base, 0, sizeof base);
    memset(&over, 0, sizeof over);
    memset(sent, 0xFF, sizeof sent);
    next_frame = 0;
}

void leds_base(int anim, uint8_t r, uint8_t g, uint8_t b)
{
    base.anim = (uint8_t)anim; base.r = r; base.g = g; base.b = b; base.start = led_now;
    dirty = 1;
}

void leds_overlay(int anim, uint8_t r, uint8_t g, uint8_t b, uint32_t ms)
{
    over.anim = (uint8_t)anim; over.r = r; over.g = g; over.b = b;
    over.start = led_now; over.until = led_now + ms;
    dirty = 1;
}

void leds_set_brightness(int v) { brightness = v; }

static void put(int i, uint32_t r, uint32_t g, uint32_t b, uint32_t level)
{
    uint32_t k = level * (uint32_t)brightness;   /* level 0..256, brightness 0..256 */
    frame[i * 3 + 0] = (uint8_t)((g * k) >> 16);
    frame[i * 3 + 1] = (uint8_t)((r * k) >> 16);
    frame[i * 3 + 2] = (uint8_t)((b * k) >> 16);
}

static void wheel(uint8_t pos, uint32_t *r, uint32_t *g, uint32_t *b)
{
    if (pos < 85) { *r = 255 - pos * 3u; *g = pos * 3u; *b = 0; }
    else if (pos < 170) { pos = (uint8_t)(pos - 85); *r = 0; *g = 255 - pos * 3u; *b = pos * 3u; }
    else { pos = (uint8_t)(pos - 170); *r = pos * 3u; *g = 0; *b = 255 - pos * 3u; }
}

static void render(const layer_t *l, uint32_t now)
{
    uint32_t t = now - l->start;
    for (int i = 0; i < LED_COUNT; i++) {
        uint32_t r = l->r, g = l->g, b = l->b, level = 0;
        switch (l->anim) {
        case ANIM_SOLID: level = 256; break;
        case ANIM_BREATHE: {
            uint32_t p = t % 2000;
            p = p < 1000 ? p : 2000 - p;
            level = 40 + p * 216 / 1000;
            break;
        }
        case ANIM_FLASH: level = (t / 80) & 1 ? 0 : 256; break;
        case ANIM_CHASE: {
            /* One lit pixel runs around the loop 0 1 2 3 7 6 5 4 with a tail. */
            static const uint8_t ring[8] = { 0, 1, 2, 3, 7, 6, 5, 4 };
            uint32_t head = (t / 60) % 8;
            for (uint32_t k = 0; k < 8; k++) if (ring[k] == i) {
                uint32_t behind = (head + 8 - k) % 8;
                level = behind == 0 ? 256 : behind == 1 ? 90 : behind == 2 ? 30 : 0;
            }
            break;
        }
        case ANIM_SPARKLE: {
            uint32_t x = sparkle ^ (t / 60 * 2654435761u);
            x ^= x >> 15; x *= 2246822519u; x ^= x >> 13;
            level = (x >> i) & 1 ? 256 : 20;
            break;
        }
        case ANIM_RAINBOW: wheel((uint8_t)(t / 6 + (uint32_t)i * 32), &r, &g, &b); level = 256; break;
        case ANIM_ALTERNATE: level = (((t / 120) + (uint32_t)i) & 1) ? 256 : 0; break;
        case ANIM_HALVES: level = (((t / 150) & 1) == (uint32_t)(i >= 4)) ? 256 : 0; break;
        case ANIM_FADE: {
            uint32_t span = l->until > l->start ? l->until - l->start : 1;
            level = t >= span ? 0 : 256 - t * 256 / span;
            break;
        }
        default: break;
        }
        put(i, r, g, b, level);
    }
}

static void send(void)
{
    if (memcmp(frame, sent, sizeof frame) == 0) return;
    memcpy(sent, frame, sizeof frame);
    hal_led_write(frame, LED_COUNT);
}

void leds_tick(uint32_t now)
{
    led_now = now;
    if (now < next_frame && !dirty) return;
    next_frame = now + FRAME_MS;
    dirty = 0;
    if (over.anim != ANIM_OFF && now >= over.until) over.anim = ANIM_OFF;
    render(over.anim != ANIM_OFF ? &over : &base, now);
    send();
}

void leds_blank(void)
{
    base.anim = over.anim = ANIM_OFF;
    memset(frame, 0, sizeof frame);
    send();
}
