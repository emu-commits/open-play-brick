/* Accelerometer (LIS3DH) with gesture detection, colour sensor (TCS34725)
 * and battery fuel gauge (MAX17048) on the I2C bus, and the I2S microphone. */
#ifndef OPB_SENSORS_H
#define OPB_SENSORS_H

#include <stdint.h>

/* ---- accelerometer ---- */
enum { GEST_NONE = -1, GEST_SHAKE, GEST_SWING, GEST_TILT_L, GEST_TILT_R, GEST_ROLL, GEST_IMPACT, GEST_THROW };

typedef struct {
    int16_t  ax, ay, az;     /* latest sample, mg */
    int16_t  gx, gy, gz;     /* low-passed gravity estimate, mg */
    uint32_t still_ms;       /* how long the brick has been at rest */
} imu_state_t;

extern imu_state_t imu;

int  imu_init(void);            /* 0 on success */
int  imu_sample(void);          /* call every IMU_PERIOD_MS, returns a GEST_ value */
void imu_arm_wake(void);        /* clear the latched interrupt before sleeping */
#define IMU_PERIOD_MS 20

/* ---- colour sensor ---- */
enum { COL_NONE, COL_RED, COL_GREEN, COL_BLUE, COL_YELLOW, COL_WHITE };

typedef struct {
    uint16_t c, r, g, b;     /* latest raw counts */
    uint8_t  colour;         /* debounced COL_ value */
} colour_state_t;

extern colour_state_t colour;

int  colour_init(void);
void colour_enable(int on);
int  colour_sample(void);       /* returns a COL_ value when the debounced colour changes, else -1 */
const char *colour_name(int c);

/* ---- fuel gauge ---- */
typedef struct {
    uint16_t mv;             /* cell voltage */
    uint8_t  soc;            /* state of charge, percent */
    int16_t  rate;           /* percent per hour x 10, positive while charging */
} gauge_state_t;

extern gauge_state_t gauge;

int  gauge_init(void);
int  gauge_sample(void);

/* ---- microphone ---- */
typedef struct {
    uint16_t level;          /* loudness of the latest 4 ms block */
    uint16_t floor;          /* slow average of the background */
} mic_state_t;

extern mic_state_t mic;

void mic_init(void);
int  mic_sample(int muted);     /* drains waiting samples, returns 1 when it hears a clap */

#endif
