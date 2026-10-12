/* Sound synthesiser and pixel animations. */
#ifndef OPB_OUTPUT_H
#define OPB_OUTPUT_H

#include <stdint.h>

/* ---- synthesiser: 4 voices, 16 kHz, integer maths only (the ESP32-C3 has
 * no floating point unit) ---- */
#define SYNTH_RATE 16000

void synth_init(void);
void synth_play(int patch);        /* looping patches take the ambient voice */
void synth_stop_ambient(void);
void synth_stop_all(void);
void synth_set_volume(int v);      /* 0..256 */
int  synth_busy(void);
void synth_fill(void);             /* top up the I2S buffer */

/* ---- pixels: 0..7 are the light array (0..3 on one long side, 4..7 on the
 * other), 8 lights the surface in front of the colour sensor ---- */
#define LED_COUNT  9
#define LED_ARRAY  8
#define LED_ILLUM  8

enum {
    ANIM_OFF, ANIM_SOLID, ANIM_BREATHE, ANIM_FLASH, ANIM_CHASE, ANIM_SPARKLE,
    ANIM_RAINBOW, ANIM_ALTERNATE, ANIM_HALVES, ANIM_FADE, ANIM_COUNT
};

void leds_init(void);
void leds_base(int anim, uint8_t r, uint8_t g, uint8_t b);
void leds_overlay(int anim, uint8_t r, uint8_t g, uint8_t b, uint32_t ms);
void leds_illuminate(int on);
void leds_set_brightness(int v);   /* 0..256 */
void leds_tick(uint32_t now);      /* renders a frame when one is due */
void leds_blank(void);             /* everything off, sent immediately */

#endif
