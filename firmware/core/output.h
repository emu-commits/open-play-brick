/* Sound synthesiser and pixel animations. */
#ifndef OPB_OUTPUT_H
#define OPB_OUTPUT_H

#include <stdint.h>

/* ---- synthesiser: 4 voices, 16 kHz, integer maths only (the ESP32-C6 has
 * no floating point unit) ---- */
#define SYNTH_RATE 16000

void synth_init(void);
void synth_play(int patch);        /* looping patches take the ambient voice */
void synth_stop_ambient(void);
void synth_stop_all(void);
void synth_set_volume(int v);      /* 0..256 */
int  synth_busy(void);
int  synth_oneshot_busy(void);     /* a sound effect (not the background loop) is playing */
/* Keep the I2S buffer fed. The clocks never stop while the brick is awake,
 * because the microphone runs on them, so this sends silence when nothing is
 * playing. `deep` fills the whole buffer, for use before a long blocking call. */
void synth_fill(int deep);

/* ---- pixels: 0..3 on one long side, 4..7 on the other ---- */
#define LED_COUNT  8

enum {
    ANIM_OFF, ANIM_SOLID, ANIM_BREATHE, ANIM_FLASH, ANIM_CHASE, ANIM_SPARKLE,
    ANIM_RAINBOW, ANIM_ALTERNATE, ANIM_HALVES, ANIM_FADE, ANIM_COUNT
};

void leds_init(void);
void leds_base(int anim, uint8_t r, uint8_t g, uint8_t b);
void leds_overlay(int anim, uint8_t r, uint8_t g, uint8_t b, uint32_t ms);
void leds_set_brightness(int v);   /* 0..256 */
void leds_tick(uint32_t now);      /* renders a frame when one is due */
void leds_blank(void);             /* everything off, sent immediately */

#endif
