/* Hardware abstraction layer.
 *
 * The core firmware touches hardware only through these calls. Two ports
 * implement them: port-espidf (the real ESP32-C3) and port-wasm (the browser
 * emulator, where each call drives simulated pins and chip models).
 */
#ifndef OPB_HAL_H
#define OPB_HAL_H

#include <stdint.h>

/* In the WebAssembly build each call is an import supplied by the emulator. */
#ifdef __wasm__
#define HAL(name) __attribute__((import_module("env"), import_name(#name))) name
#else
#define HAL(name) name
#endif

#define HAL_GPIO_INPUT   0
#define HAL_GPIO_OUTPUT  1
#define HAL_GPIO_HIGHZ   2

void     HAL(hal_gpio_mode)(int pin, int mode);
void     HAL(hal_gpio_write)(int pin, int level);
int      HAL(hal_gpio_read)(int pin);

/* SPI mode 0, MSB first, on PIN_SPI_SCK / MOSI / MISO. Chip select is a plain
 * GPIO owned by the driver. Either buffer may be null. */
void     HAL(hal_spi_transfer)(const uint8_t *tx, uint8_t *rx, int len);

/* I2C host on PIN_I2C_SDA / SCL at 400 kHz. Return 0 on success, -1 on NACK. */
int      HAL(hal_i2c_write)(uint8_t addr, const uint8_t *data, int len);
int      HAL(hal_i2c_write_read)(uint8_t addr, const uint8_t *wr, int wr_len, uint8_t *rd, int rd_len);

/* Shift out pixel data (3 bytes per pixel, G R B order) on PIN_LED_DATA. */
void     HAL(hal_led_write)(const uint8_t *grb, int n_pixels);

/* I2S: 16 kHz, 16-bit mono. hal_i2s_space is the free room in the transmit
 * buffer, in samples. */
int      HAL(hal_i2s_space)(void);
void     HAL(hal_i2s_write)(const int16_t *samples, int n);

uint32_t HAL(hal_millis)(void);
void     HAL(hal_delay_us)(uint32_t us);

void     HAL(hal_log)(const char *line);

/* Read from the catalogue data partition. Returns bytes read. */
int      HAL(hal_storage_read)(uint32_t offset, uint8_t *dst, int len);

/* Brick-to-brick broadcast (ESP-NOW on hardware). */
void     HAL(hal_radio_send)(const uint8_t *data, int len);

/* Enter deep sleep until PIN_IMU_INT1 goes high. On hardware this does not
 * return: the chip resets on wake. */
void     HAL(hal_deep_sleep)(void);

#endif
