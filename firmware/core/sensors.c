#include "sensors.h"
#include "hal.h"
#include "pins.h"
#include "util.h"

static int reg_write(uint8_t addr, uint8_t reg, uint8_t v)
{
    uint8_t b[2] = { reg, v };
    return hal_i2c_write(addr, b, 2);
}

static int reg_read(uint8_t addr, uint8_t reg, uint8_t *dst, int n)
{
    return hal_i2c_write_read(addr, &reg, 1, dst, n);
}

/* ------------------------------------------------------------------ */
/* LIS2DH12                                                           */
/* ------------------------------------------------------------------ */

#define LIS_WHO_AM_I   0x0F
#define LIS_CTRL1      0x20
#define LIS_CTRL2      0x21
#define LIS_CTRL3      0x22
#define LIS_CTRL4      0x23
#define LIS_CTRL5      0x24
#define LIS_REFERENCE  0x26
#define LIS_OUT_X_L    0x28
#define LIS_INT1_CFG   0x30
#define LIS_INT1_SRC   0x31
#define LIS_INT1_THS   0x32
#define LIS_INT1_DUR   0x33
#define LIS_AUTO_INC   0x80

imu_state_t imu;

/* Gesture thresholds, in mg and ms. "energy" is how far the length of the
 * acceleration vector is from 1 g: turning the brick over leaves it near zero,
 * pushing the brick through the air does not. */
#define SHAKE_AXIS_MG      700
#define SHAKE_REVERSALS    4
#define SHAKE_WINDOW_MS    900
#define SWING_ON_MG        350
#define SWING_OFF_MG       200
#define SWING_MIN_MS       240
#define SWING_MAX_MS       1400
#define SWING_GAP_MS       160
#define IMPACT_MG          2500
#define FREEFALL_MG        350
#define FREEFALL_MS        100
#define TILT_ON_MG         600
#define TILT_OFF_MG        300
#define TILT_HOLD_MS       300
#define ROLL_MG            700
#define ROLL_HOLD_MS       200
#define LOCKOUT_MS         500

static struct {
    int32_t  g16[3];            /* gravity estimate, mg x 16 */
    uint32_t t;                 /* ms since init, advanced per sample */
    uint32_t lockout_until;
    /* shake */
    int8_t   shake_axis, shake_sign;
    uint8_t  reversals;
    uint32_t first_reversal, last_strong;
    /* swing */
    uint8_t  swinging;
    uint32_t swing_start, swing_last;
    uint8_t  swing_reversals;
    /* throw */
    uint32_t fall_ms;
    uint8_t  thrown;
    /* tilt and roll */
    int8_t   tilt;              /* -1, 0, +1 */
    uint32_t tilt_ms;
    int8_t   up;                /* +1 upright, -1 inverted */
    uint32_t roll_ms;
} gs;

int imu_init(void)
{
    uint8_t id = 0;
    if (reg_read(I2C_ADDR_LIS2DH12, LIS_WHO_AM_I, &id, 1) < 0 || id != 0x33) return -1;
    reg_write(I2C_ADDR_LIS2DH12, LIS_CTRL1, 0x57);     /* 100 Hz, X Y Z on */
    reg_write(I2C_ADDR_LIS2DH12, LIS_CTRL2, 0x01);     /* high-pass on the interrupt path: ignore gravity */
    reg_write(I2C_ADDR_LIS2DH12, LIS_CTRL3, 0x40);     /* route activity interrupt to INT1 */
    reg_write(I2C_ADDR_LIS2DH12, LIS_CTRL4, 0x98);     /* block data update, +/-4 g, high resolution */
    reg_write(I2C_ADDR_LIS2DH12, LIS_CTRL5, 0x08);     /* latch INT1 until INT1_SRC is read */
    reg_write(I2C_ADDR_LIS2DH12, LIS_INT1_THS, 8);     /* 8 x 32 mg = 256 mg */
    reg_write(I2C_ADDR_LIS2DH12, LIS_INT1_DUR, 0);
    reg_write(I2C_ADDR_LIS2DH12, LIS_INT1_CFG, 0x2A);  /* X, Y or Z above threshold */
    reg_read(I2C_ADDR_LIS2DH12, LIS_REFERENCE, &id, 1);
    hal_gpio_mode(PIN_IMU_INT1, HAL_GPIO_INPUT);

    memset(&gs, 0, sizeof gs);
    gs.g16[2] = 1000 * 16;
    gs.up = 1;
    gs.shake_axis = -1;
    opb_logf("LIS2DH12 found, +/-4 g, 100 Hz, wake-on-motion armed at 256 mg");
    return 0;
}

void imu_arm_wake(void)
{
    uint8_t src;
    reg_read(I2C_ADDR_LIS2DH12, LIS_REFERENCE, &src, 1);
    reg_read(I2C_ADDR_LIS2DH12, LIS_INT1_SRC, &src, 1);
}

static int iabs(int v) { return v < 0 ? -v : v; }

int imu_sample(void)
{
    uint8_t raw[6];
    if (reg_read(I2C_ADDR_LIS2DH12, LIS_OUT_X_L | LIS_AUTO_INC, raw, 6) < 0) return GEST_NONE;
    if (hal_gpio_read(PIN_IMU_INT1)) {
        uint8_t src;
        reg_read(I2C_ADDR_LIS2DH12, LIS_INT1_SRC, &src, 1);
    }

    /* 12-bit left-justified, 2 mg per count at +/-4 g. */
    int a[3], d[3];
    for (int i = 0; i < 3; i++) {
        a[i] = ((int16_t)rd16(raw + i * 2) >> 4) * 2;
        gs.g16[i] += ((a[i] << 4) - gs.g16[i]) >> 3;
        d[i] = a[i] - (gs.g16[i] >> 4);
    }
    imu.ax = (int16_t)a[0]; imu.ay = (int16_t)a[1]; imu.az = (int16_t)a[2];
    imu.gx = (int16_t)(gs.g16[0] >> 4); imu.gy = (int16_t)(gs.g16[1] >> 4); imu.gz = (int16_t)(gs.g16[2] >> 4);

    int mag = (int)opb_isqrt((uint32_t)(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]));
    int energy = iabs(mag - 1000);
    int dyn = (int)opb_isqrt((uint32_t)(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]));
    uint32_t now = gs.t += IMU_PERIOD_MS;
    int locked = now < gs.lockout_until;
    int gesture = GEST_NONE;

    if (energy < 80 && dyn < 120) imu.still_ms += IMU_PERIOD_MS;
    else imu.still_ms = 0;

    /* Free fall, then the catch. */
    if (mag < FREEFALL_MG) {
        gs.fall_ms += IMU_PERIOD_MS;
        if (gs.fall_ms >= FREEFALL_MS && !gs.thrown) {
            gs.thrown = 1;
            gs.swinging = 0;
            gs.reversals = 0;
            gs.lockout_until = now + 150;
            return GEST_THROW;
        }
    } else {
        gs.fall_ms = 0;
        if (mag > 700 && energy < IMPACT_MG) gs.thrown = 0;   /* caught gently */
    }

    /* A single hard knock. */
    if (energy > IMPACT_MG && !locked) {
        gs.thrown = 0;
        gs.swinging = 0;
        gs.reversals = 0;
        gs.lockout_until = now + LOCKOUT_MS;
        return GEST_IMPACT;
    }

    /* Shake: the strongest axis keeps changing sign. */
    int axis = 0;
    if (iabs(d[1]) > iabs(d[axis])) axis = 1;
    if (iabs(d[2]) > iabs(d[axis])) axis = 2;
    if (iabs(d[axis]) > SHAKE_AXIS_MG) {
        int8_t sign = d[axis] > 0 ? 1 : -1;
        if (axis == gs.shake_axis && sign != gs.shake_sign && now - gs.last_strong < 300) {
            if (gs.reversals == 0) gs.first_reversal = now;
            gs.reversals++;
            if (gs.swinging) gs.swing_reversals++;
        } else if (axis != gs.shake_axis) {
            gs.reversals = 0;
        }
        gs.shake_axis = (int8_t)axis;
        gs.shake_sign = sign;
        gs.last_strong = now;
    } else if (now - gs.last_strong > 300) {
        gs.reversals = 0;
    }
    if (gs.reversals >= SHAKE_REVERSALS) {
        int in_window = now - gs.first_reversal <= SHAKE_WINDOW_MS;
        gs.reversals = 0;
        if (in_window && !locked) {
            gs.swinging = 0;
            gs.lockout_until = now + LOCKOUT_MS;
            return GEST_SHAKE;
        }
    }

    /* Swing: a push through the air that starts and stops once. */
    if (energy > SWING_ON_MG && !locked) {
        if (!gs.swinging) { gs.swinging = 1; gs.swing_start = now; gs.swing_reversals = 0; }
        gs.swing_last = now;
    } else if (gs.swinging && energy < SWING_OFF_MG && now - gs.swing_last >= SWING_GAP_MS) {
        uint32_t len = gs.swing_last - gs.swing_start;
        gs.swinging = 0;
        if (len >= SWING_MIN_MS && len <= SWING_MAX_MS && gs.swing_reversals <= 2 && !locked) {
            gs.lockout_until = now + LOCKOUT_MS;
            gesture = GEST_SWING;
        }
    }

    /* Tilt along the long axis and turning the brick over, both read from the
     * gravity estimate while the brick is otherwise calm. */
    if (energy < SWING_OFF_MG) {
        int want = imu.gx > TILT_ON_MG ? 1 : imu.gx < -TILT_ON_MG ? -1 : 0;
        if (want && want != gs.tilt) {
            gs.tilt_ms += IMU_PERIOD_MS;
            if (gs.tilt_ms >= TILT_HOLD_MS) {
                gs.tilt = (int8_t)want;
                gs.tilt_ms = 0;
                if (gesture == GEST_NONE) gesture = want > 0 ? GEST_TILT_R : GEST_TILT_L;
            }
        } else {
            gs.tilt_ms = 0;
            if (iabs(imu.gx) < TILT_OFF_MG) gs.tilt = 0;
        }

        int facing = imu.gz > ROLL_MG ? 1 : imu.gz < -ROLL_MG ? -1 : 0;
        if (facing && facing != gs.up) {
            gs.roll_ms += IMU_PERIOD_MS;
            if (gs.roll_ms >= ROLL_HOLD_MS) {
                gs.up = (int8_t)facing;
                gs.roll_ms = 0;
                if (gesture == GEST_NONE) gesture = GEST_ROLL;
            }
        } else {
            gs.roll_ms = 0;
        }
    }
    return gesture;
}

/* ------------------------------------------------------------------ */
/* TCS34725                                                           */
/* ------------------------------------------------------------------ */

#define TCS_CMD        0x80
#define TCS_AUTO_INC   0x20
#define TCS_ENABLE     0x00
#define TCS_ATIME      0x01
#define TCS_CONTROL    0x0F
#define TCS_ID         0x12
#define TCS_CDATAL     0x14

#define COLOUR_MIN_CLEAR 400   /* below this there is nothing in front of the sensor */

colour_state_t colour;
static uint8_t col_candidate, col_count;

int colour_init(void)
{
    uint8_t id = 0;
    if (reg_read(I2C_ADDR_TCS34725, TCS_CMD | TCS_ID, &id, 1) < 0 || (id != 0x44 && id != 0x4D)) return -1;
    reg_write(I2C_ADDR_TCS34725, TCS_CMD | TCS_ATIME, 0xF6);    /* 10 cycles, 24 ms */
    reg_write(I2C_ADDR_TCS34725, TCS_CMD | TCS_CONTROL, 0x01);  /* 4x gain */
    colour_enable(0);
    opb_logf("TCS3472x found, id 0x%02x, 24 ms integration, 4x gain", id);
    return 0;
}

void colour_enable(int on)
{
    reg_write(I2C_ADDR_TCS34725, TCS_CMD | TCS_ENABLE, on ? 0x03 : 0x00);
    if (!on) { colour.colour = COL_NONE; col_count = 0; }
}

static uint8_t classify(uint32_t c, uint32_t r, uint32_t g, uint32_t b)
{
    if (c < COLOUR_MIN_CLEAR) return COL_NONE;
    if (r * 10 > g * 16 && r * 10 > b * 16) return COL_RED;
    if (g * 10 > r * 13 && g * 10 > b * 13) return COL_GREEN;
    if (b * 10 > r * 14 && b * 10 > g * 12) return COL_BLUE;
    if (r * 10 > b * 17 && g * 10 > b * 15) return COL_YELLOW;
    return COL_WHITE;
}

int colour_sample(void)
{
    uint8_t raw[8];
    if (reg_read(I2C_ADDR_TCS34725, TCS_CMD | TCS_AUTO_INC | TCS_CDATAL, raw, 8) < 0) return -1;
    colour.c = rd16(raw); colour.r = rd16(raw + 2); colour.g = rd16(raw + 4); colour.b = rd16(raw + 6);

    uint8_t now = classify(colour.c, colour.r, colour.g, colour.b);
    if (now != col_candidate) { col_candidate = now; col_count = 1; return -1; }
    if (col_count < 3 && ++col_count == 3 && now != colour.colour) {
        colour.colour = now;
        return now;
    }
    return -1;
}

const char *colour_name(int c)
{
    static const char *const names[] = { "none", "red", "green", "blue", "yellow", "white" };
    return names[c];
}

/* ------------------------------------------------------------------ */
/* MAX17048                                                           */
/* ------------------------------------------------------------------ */

#define MAX_VCELL    0x02
#define MAX_SOC      0x04
#define MAX_VERSION  0x08
#define MAX_CRATE    0x16

gauge_state_t gauge;

int gauge_init(void)
{
    uint8_t v[2];
    if (reg_read(I2C_ADDR_MAX17048, MAX_VERSION, v, 2) < 0) return -1;
    opb_logf("MAX17048 found, version 0x%02x%02x", v[0], v[1]);
    return gauge_sample();
}

int gauge_sample(void)
{
    uint8_t v[2];
    if (reg_read(I2C_ADDR_MAX17048, MAX_VCELL, v, 2) < 0) return -1;
    gauge.mv = (uint16_t)((((uint32_t)v[0] << 8 | v[1]) * 5u) >> 6);   /* 78.125 uV per count */
    if (reg_read(I2C_ADDR_MAX17048, MAX_SOC, v, 2) < 0) return -1;
    gauge.soc = v[0] > 100 ? 100 : v[0];
    if (reg_read(I2C_ADDR_MAX17048, MAX_CRATE, v, 2) < 0) return -1;
    gauge.rate = (int16_t)(((int16_t)((v[0] << 8) | v[1]) * 208) / 100);  /* 0.208 %/h per count */
    return 0;
}
