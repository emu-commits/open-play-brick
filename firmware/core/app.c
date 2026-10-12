/* Open Play Brick: application logic.
 *
 * One cooperative loop. Each pass samples the sensors that are due, polls
 * for a tag, turns whatever happened into play events, and keeps the pixels
 * and the audio buffer fed.
 */
#include "app.h"
#include "catalog.h"
#include "hal.h"
#include "output.h"
#include "pins.h"
#include "pn5180.h"
#include "sensors.h"
#include "util.h"

#define NFC_SEARCH_MS      250      /* poll period while no tag is present */
#define NFC_PRESENCE_MS    500      /* poll period while a tag is present */
#define NFC_MISSES         2        /* missed polls before a tag counts as removed */
#define COLOUR_PERIOD_MS   60
#define GAUGE_PERIOD_MS    2000
#define SLEEP_AFTER_MS     30000    /* at rest with no tag for this long: deep sleep */
#define LOW_BATTERY_PCT    10
#define CUTOFF_PCT         3
#define TAG_BLOCKS         66
#define HITS_TO_DAMAGE     4
#define HITS_TO_DESTROY    2

#define RADIO_FIRE         1

static const char *const EVENT_NAMES[EV_COUNT] = {
    "Tag placed", "Tag removed", "Shake", "Swing", "Tilt left", "Tilt right", "Roll", "Impact",
    "Throw", "Red", "Green", "Blue", "Hit", "Damaged", "Destroyed", "Ambient", "Clap"
};

static fw_status_t st;
static tag_info_t tag;
static uint8_t tag_data[TAG_BLOCKS * 4];
static uint8_t sleeping, nfc_ok, imu_ok, colour_ok, gauge_ok, low_warned, misses;
static uint16_t radio_seq;
static uint32_t next_imu, next_nfc, next_colour, next_gauge, gesture_until, idle_since, mic_muted_until;

/* ------------------------------------------------------------------ */

/* Pixel supply and amplifier enable. */
static void periph_power(int on)
{
    hal_gpio_write(PIN_PERIPH_EN, on ? 1 : 0);
    hal_gpio_mode(PIN_PERIPH_EN, HAL_GPIO_OUTPUT);
    hal_gpio_hold(PIN_PERIPH_EN, !on);
    if (on) hal_delay_us(5000);
}

/* The white LED beside the colour sensor. */
static void lamp(int on) { hal_gpio_write(PIN_LAMP_EN, on ? 1 : 0); }

static void set_idle_look(void)
{
    if (st.charging) {
        if (st.soc >= 99) leds_base(ANIM_SOLID, 0, 60, 0);
        else leds_base(ANIM_BREATHE, 70, 40, 0);
    } else if (st.soc < LOW_BATTERY_PCT) {
        leds_base(ANIM_BREATHE, 50, 0, 0);
    } else {
        leds_base(ANIM_BREATHE, 14, 14, 14);
    }
}

static void set_tag_look(void)
{
    if (st.damaged) leds_base(ANIM_ALTERNATE, 255, 30, 0);
    else leds_base(catalog_event_anim(tag.profile, EV_AMBIENT), tag.r, tag.g, tag.b);
}

static void refresh_state(uint32_t now)
{
    if (sleeping) st.state = ST_SLEEP;
    else if (st.tag_present) st.state = now < gesture_until ? ST_GESTURE : ST_TAG_ACTIVE;
    else if (st.charging) st.state = ST_CHARGING;
    else if (st.soc < LOW_BATTERY_PCT) st.state = ST_LOW_BATTERY;
    else st.state = ST_IDLE;
}

/* Turn a play event into sound and light, using the active tag's profile. */
static void play_event(int ev)
{
    int profile = st.tag_present ? tag.profile : 0;
    uint8_t patch = catalog_event_patch(profile, ev);
    uint8_t anim = catalog_event_anim(profile, ev);
    uint8_t r = 200, g = 200, b = 200;

    if (st.tag_present) { r = tag.r; g = tag.g; b = tag.b; }
    switch (ev) {
    case EV_RED:       r = 255; g = 0;   b = 0;   break;
    case EV_GREEN:     r = 0;   g = 255; b = 0;   break;
    case EV_BLUE:      r = 0;   g = 60;  b = 255; break;
    case EV_HIT:       r = 255; g = 120; b = 0;   break;
    case EV_DAMAGED:   r = 255; g = 30;  b = 0;   break;
    case EV_DESTROYED: r = 255; g = 255; b = 255; break;
    default: break;
    }

    uint32_t ms = 400;
    if (patch != PATCH_NONE) {
        synth_play(patch);
        uint32_t len = catalog_patch_ms(patch);
        if (len > ms) ms = len;
        if (ms > 2500) ms = 2500;
    }
    if (anim != ANIM_OFF) leds_overlay(anim, r, g, b, ms);
    gesture_until = hal_millis() + ms;
    st.last_event = (uint8_t)ev;

    if (st.tag_present) opb_logf("%s while %s active -> patch#%d, anim %d", EVENT_NAMES[ev], tag.name, patch, anim);
    else opb_logf("%s with no tag -> patch#%d, anim %d", EVENT_NAMES[ev], patch, anim);
}

/* ------------------------------------------------------------------ */
/* Tags                                                               */
/* ------------------------------------------------------------------ */

static void tag_removed(void)
{
    opb_logf("Tag removed.");
    play_event(EV_REMOVE);
    synth_stop_ambient();
    st.tag_present = 0;
    st.tag_index = 0xFF;
    st.hits = st.damaged = 0;
    st.tag_name[0] = 0;
    if (colour_ok) colour_enable(0);
    st.colour = COL_NONE;
    lamp(0);
    hal_radio_enable(0);
    set_idle_look();
}

static void tag_found(const uint8_t uid[8])
{
    opb_logf("ISO 15693 tag detected, UID %02x:%02x:%02x:%02x:%02x:%02x:%02x:%02x",
             uid[7], uid[6], uid[5], uid[4], uid[3], uid[2], uid[1], uid[0]);

    if (iso15693_read_blocks(0, 1, tag_data) < 0) { opb_logf("  Block 0 read failed, will retry."); return; }
    const uint8_t *h = tag_data;
    opb_logf("  Block 0: %02x %02x %02x %02x", h[0], h[1], h[2], h[3]);

    int is_play_tag = h[0] == 0x00 && h[2] == 0x01 && h[3] == 0x0C && h[1] >= 5;
    uint8_t len = h[1];
    uint32_t crc = 0;
    int index = -1, exact = 0;

    if (is_play_tag) {
        uint8_t blocks = (uint8_t)((len + 3) / 4);
        if (blocks > TAG_BLOCKS) blocks = TAG_BLOCKS;
        if (blocks > 1 && iso15693_read_blocks(1, (uint8_t)(blocks - 1), tag_data + 4) < 0) {
            opb_logf("  Payload read failed, will retry.");
            return;
        }
        crc = opb_crc32(tag_data, len);
        opb_logf("  Payload length %d bytes (blocks 0-%d), CRC-32 0x%08x", len, blocks - 1, crc);
        index = catalog_find(len, crc, &exact);
    } else {
        opb_logf("  Not a play tag header (expected 00 LL 01 0C).");
    }

    memset(&tag, 0, sizeof tag);
    if (index >= 0) {
        catalog_tag(index, &tag);
        opb_logf("  => %s (%s), %s", tag.name, tag.kind == KIND_IDENTITY ? "identity" : tag.kind == KIND_ITEM ? "item" : "unknown kind",
                 exact ? "exact CRC match" : "matched by length only");
    } else {
        memcpy(tag.name, "Unknown tag", 12);
        tag.r = tag.g = tag.b = 160;
        if (is_play_tag) opb_logf("  => not in the catalogue. Add len 0x%02x, crc 0x%08x to tags.json.", len, crc);
    }

    st.tag_present = 1;
    st.tag_index = index >= 0 ? (uint8_t)index : 0xFF;
    st.tag_exact = (uint8_t)exact;
    st.tag_len = len;
    st.tag_kind = tag.kind;
    st.tag_crc = crc;
    st.hits = st.damaged = 0;
    memcpy(st.uid, uid, 8);
    memcpy(st.tag_name, tag.name, sizeof tag.name);
    misses = 0;

    if (index < 0) {
        uint8_t p = catalog_sys_patch(SYS_UNKNOWN_TAG);
        if (p != PATCH_NONE) synth_play(p);
    }
    play_event(EV_PLACE);
    uint8_t ambient = catalog_event_patch(tag.profile, EV_AMBIENT);
    if (ambient != PATCH_NONE) synth_play(ambient);
    set_tag_look();
    if (colour_ok) { colour_enable(1); lamp(1); }
    if (tag.flags & TAG_FLAG_COMBAT) hal_radio_enable(1);
}

static void nfc_task(uint32_t now)
{
    if (!nfc_ok || now < next_nfc) return;
    synth_fill(1);   /* a tag read blocks for tens of milliseconds */

    uint8_t uid[8];
    int found = -1;
    if (pn5180_rf_on() == 0) found = iso15693_inventory(uid);
    if (found == 1) {
        misses = 0;
        if (!st.tag_present || memcmp(uid, st.uid, 8) != 0) {
            if (st.tag_present) tag_removed();
            tag_found(uid);
        }
    } else if (found == 0 && st.tag_present && ++misses >= NFC_MISSES) {
        tag_removed();
    }
    pn5180_rf_off();
    next_nfc = hal_millis() + (st.tag_present ? NFC_PRESENCE_MS : NFC_SEARCH_MS);
}

/* ------------------------------------------------------------------ */
/* Brick-to-brick                                                     */
/* ------------------------------------------------------------------ */

static void radio_fire(void)
{
    uint8_t pkt[8] = { 'O', 'P', 'B', 1, RADIO_FIRE, st.tag_len, (uint8_t)radio_seq, (uint8_t)(radio_seq >> 8) };
    radio_seq++;
    hal_radio_send(pkt, sizeof pkt);
    opb_logf("Radio: sent FIRE #%d", radio_seq);
}

void fw_on_radio(const uint8_t *data, int len)
{
    if (sleeping || len < 8 || memcmp(data, "OPB", 3) != 0 || data[3] != 1 || data[4] != RADIO_FIRE) return;
    if (!st.tag_present || !(tag.flags & TAG_FLAG_COMBAT)) {
        opb_logf("Radio: FIRE received, ignored (no combat tag active)");
        return;
    }
    st.hits++;
    if (!st.damaged && st.hits >= HITS_TO_DAMAGE) {
        st.damaged = 1;
        st.hits = 0;
        opb_logf("Radio: hit %d of %d, now damaged", HITS_TO_DAMAGE, HITS_TO_DAMAGE);
        set_tag_look();
        play_event(EV_DAMAGED);
    } else if (st.damaged && st.hits >= HITS_TO_DESTROY) {
        st.damaged = 0;
        st.hits = 0;
        opb_logf("Radio: destroyed, resetting");
        set_tag_look();
        play_event(EV_DESTROYED);
    } else {
        opb_logf("Radio: hit %d%s", st.hits, st.damaged ? " while damaged" : "");
        play_event(EV_HIT);
    }
}

/* ------------------------------------------------------------------ */
/* Power                                                              */
/* ------------------------------------------------------------------ */

static void go_to_sleep(const char *why)
{
    opb_logf("Sleeping: %s. Move the brick to wake it.", why);
    synth_stop_all();
    leds_blank();
    lamp(0);
    hal_radio_enable(0);
    if (colour_ok) colour_enable(0);
    pn5180_power_down();
    /* The pixel supply is switched on its ground side on the module build, so
     * the data pin must float, not sit low, while the pixels are off. */
    hal_gpio_mode(PIN_LED_DATA, HAL_GPIO_HIGHZ);
    periph_power(0);
    /* The accelerometer stays powered so that it can wake the brick. */
    hal_gpio_hold(PIN_QT_PWR, 1);
    if (imu_ok) imu_arm_wake();
    sleeping = 1;
    st.state = ST_SLEEP;
    hal_deep_sleep();
}

static void gauge_task(uint32_t now)
{
    if (!gauge_ok || now < next_gauge) return;
    next_gauge = now + GAUGE_PERIOD_MS;
    if (gauge_sample() < 0) return;

    uint8_t was_charging = st.charging, was_soc = st.soc;
    st.mv = gauge.mv;
    st.soc = gauge.soc;
    st.charging = gauge.rate > 5;
    if (st.charging != was_charging) opb_logf("Battery: %s, %d%%, %d mV", st.charging ? "charging" : "on battery", st.soc, st.mv);

    int low = st.soc < LOW_BATTERY_PCT && !st.charging;
    leds_set_brightness(low ? 50 : 140);
    synth_set_volume(low ? 100 : 200);
    if (low && !low_warned) {
        low_warned = 1;
        opb_logf("Battery low: %d%%", st.soc);
        uint8_t p = catalog_sys_patch(SYS_LOW_BATTERY);
        if (p != PATCH_NONE) synth_play(p);
        leds_overlay(ANIM_FLASH, 255, 0, 0, 600);
    }
    if (!low) low_warned = 0;
    if (!st.tag_present && (st.charging != was_charging || (st.soc < LOW_BATTERY_PCT) != (was_soc < LOW_BATTERY_PCT) || (st.soc >= 99) != (was_soc >= 99)))
        set_idle_look();
    if (st.soc <= CUTOFF_PCT && !st.charging) go_to_sleep("battery empty");
}

/* ------------------------------------------------------------------ */

void fw_init(void)
{
    memset(&st, 0, sizeof st);
    st.state = ST_BOOT;
    st.tag_index = 0xFF;
    st.last_event = 0xFF;
    st.soc = 100;
    sleeping = low_warned = misses = 0;
    gesture_until = 0;

    opb_logf("Open Play Brick firmware %s", FW_VERSION);
    hal_gpio_write(PIN_QT_PWR, 1);          /* sensor connector power, already on after a wake */
    hal_gpio_mode(PIN_QT_PWR, HAL_GPIO_OUTPUT);
    hal_gpio_hold(PIN_QT_PWR, 0);
    hal_gpio_write(PIN_LAMP_EN, 0);
    hal_gpio_mode(PIN_LAMP_EN, HAL_GPIO_OUTPUT);
    hal_gpio_write(PIN_LED_DATA, 0);
    hal_gpio_mode(PIN_LED_DATA, HAL_GPIO_OUTPUT);
    periph_power(1);

    if (catalog_load() < 0) opb_logf("ERROR: no valid catalogue in flash. The brick will stay silent.");
    synth_init();
    leds_init();

    nfc_ok = pn5180_init() == 0;
    if (!nfc_ok) opb_logf("ERROR: PN5180 not responding");
    imu_ok = imu_init() == 0;
    if (!imu_ok) opb_logf("ERROR: LIS3DH not responding");
    mic_init();
    colour_ok = colour_init() == 0;
    if (!colour_ok) opb_logf("ERROR: TCS3472x not responding");
    gauge_ok = gauge_init() == 0;
    if (!gauge_ok) opb_logf("ERROR: MAX17048 not responding");
    else { st.mv = gauge.mv; st.soc = gauge.soc; st.charging = gauge.rate > 5; opb_logf("Battery: %d%%, %d mV", st.soc, st.mv); }

    uint32_t now = hal_millis();
    next_imu = next_colour = idle_since = now;
    mic_muted_until = now + 400;
    next_nfc = now + 300;
    next_gauge = now + GAUGE_PERIOD_MS;

    leds_tick(now);
    set_idle_look();
    uint8_t boot = catalog_sys_patch(SYS_BOOT);
    if (boot != PATCH_NONE) synth_play(boot);
    leds_overlay(ANIM_RAINBOW, 0, 0, 0, 900);
    opb_logf("Waiting for a tag (ISO 15693)...");
}

void fw_loop(void)
{
    if (sleeping) return;
    uint32_t now = hal_millis();

    if (imu_ok && now >= next_imu) {
        next_imu += IMU_PERIOD_MS;
        if (now > next_imu + 200) next_imu = now;   /* fell far behind, resync */
        static const int8_t map[] = { EV_SHAKE, EV_SWING, EV_TILT_L, EV_TILT_R, EV_ROLL, EV_IMPACT, EV_THROW };
        int gesture = imu_sample();
        st.ax = imu.ax; st.ay = imu.ay; st.az = imu.az;
        if (gesture != GEST_NONE) play_event(map[gesture]);
    }

    if (colour_ok && st.tag_present && now >= next_colour) {
        next_colour = now + COLOUR_PERIOD_MS;
        int c = colour_sample();
        if (c >= 0) {
            st.colour = (uint8_t)c;
            opb_logf("Colour sensor: %s (C %d R %d G %d B %d)", colour_name(c), colour.c, colour.r, colour.g, colour.b);
            if (c == COL_RED) {
                play_event(EV_RED);
                if (tag.flags & TAG_FLAG_COMBAT) radio_fire();
            } else if (c == COL_GREEN) {
                play_event(EV_GREEN);
            } else if (c == COL_BLUE) {
                play_event(EV_BLUE);
            }
        }
    }

    /* The microphone hears the brick's own speaker, so claps are ignored
     * while a sound effect plays and for a moment after. */
    if (synth_oneshot_busy()) mic_muted_until = now + 200;
    if (mic_sample(now < mic_muted_until)) play_event(EV_CLAP);
    st.mic_level = mic.level;
    st.mic_floor = mic.floor;

    nfc_task(now);
    if (sleeping) return;
    gauge_task(now);
    if (sleeping) return;

    now = hal_millis();
    leds_tick(now);
    synth_fill(0);
    refresh_state(now);

    /* The sleep timer runs only while nothing at all is going on. */
    if (st.tag_present || st.charging || synth_busy() || !imu_ok || imu.still_ms == 0) idle_since = now;
    if (now - idle_since >= SLEEP_AFTER_MS) {
        go_to_sleep("no tag and no movement for 30 s");
        return;
    }
    hal_delay_us(2000);
}

const fw_status_t *fw_status(void) { return &st; }
