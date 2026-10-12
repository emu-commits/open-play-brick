/* ESP32-C3 port of the hardware abstraction layer (ESP-IDF 5.x).
 *
 * STATUS: written against the ESP-IDF 5 APIs but not yet compiled or run on
 * hardware. Treat it as the starting point for bring-up, not as tested code.
 * The core firmware it serves is the same code the emulator runs.
 */
#include <string.h>
#include "driver/gpio.h"
#include "driver/i2c.h"
#include "driver/i2s_std.h"
#include "driver/spi_master.h"
#include "esp_log.h"
#include "esp_now.h"
#include "esp_partition.h"
#include "esp_rom_sys.h"
#include "esp_sleep.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "led_strip.h"
#include "nvs_flash.h"

#include "hal.h"
#include "pins.h"

#define I2S_RATE          16000
#define I2S_BUFFER_FRAMES 2048

static spi_device_handle_t spi;
static led_strip_handle_t strip;
static i2s_chan_handle_t i2s_tx;
static const esp_partition_t *catalog;
static int64_t i2s_end_us;
static bool i2s_running;
static const uint8_t BROADCAST[6] = { 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF };

void hal_espidf_init(void)
{
    spi_bus_config_t bus = { .mosi_io_num = PIN_SPI_MOSI, .miso_io_num = PIN_SPI_MISO, .sclk_io_num = PIN_SPI_SCK,
                             .quadwp_io_num = -1, .quadhd_io_num = -1 };
    spi_device_interface_config_t dev = { .clock_speed_hz = 2000000, .mode = 0, .spics_io_num = -1, .queue_size = 1 };
    ESP_ERROR_CHECK(spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_DISABLED));
    ESP_ERROR_CHECK(spi_bus_add_device(SPI2_HOST, &dev, &spi));

    /* The board carries its own 2.2k pull-ups. */
    i2c_config_t i2c = { .mode = I2C_MODE_MASTER, .sda_io_num = PIN_I2C_SDA, .scl_io_num = PIN_I2C_SCL,
                         .master.clk_speed = 400000 };
    ESP_ERROR_CHECK(i2c_param_config(I2C_NUM_0, &i2c));
    ESP_ERROR_CHECK(i2c_driver_install(I2C_NUM_0, I2C_MODE_MASTER, 0, 0, 0));

    led_strip_config_t led = { .strip_gpio_num = PIN_LED_DATA, .max_leds = 9, .led_model = LED_MODEL_SK6812,
                               .led_pixel_format = LED_PIXEL_FORMAT_GRB };
    led_strip_rmt_config_t rmt = { .resolution_hz = 10 * 1000 * 1000 };
    ESP_ERROR_CHECK(led_strip_new_rmt_device(&led, &rmt, &strip));

    /* MAX98357A with SD_MODE tied high plays the left slot. */
    i2s_chan_config_t chan = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    chan.dma_desc_num = 8;
    chan.dma_frame_num = I2S_BUFFER_FRAMES / 8;
    ESP_ERROR_CHECK(i2s_new_channel(&chan, &i2s_tx, NULL));
    i2s_std_config_t std = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(I2S_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO),
        .gpio_cfg = { .mclk = I2S_GPIO_UNUSED, .bclk = PIN_I2S_BCLK, .ws = PIN_I2S_LRCLK, .dout = PIN_I2S_DOUT, .din = I2S_GPIO_UNUSED },
    };
    ESP_ERROR_CHECK(i2s_channel_init_std_mode(i2s_tx, &std));

    catalog = esp_partition_find_first(ESP_PARTITION_TYPE_DATA, 0x40, "catalog");
}

/* ---- GPIO ---- */

void hal_gpio_mode(int pin, int mode)
{
    gpio_set_direction(pin, mode == HAL_GPIO_OUTPUT ? GPIO_MODE_OUTPUT : mode == HAL_GPIO_INPUT ? GPIO_MODE_INPUT : GPIO_MODE_DISABLE);
}

void hal_gpio_write(int pin, int level) { gpio_set_level(pin, level); }
int  hal_gpio_read(int pin) { return gpio_get_level(pin); }

/* ---- SPI ---- */

void hal_spi_transfer(const uint8_t *tx, uint8_t *rx, int len)
{
    static uint8_t ones[80];
    if (!tx) { memset(ones, 0xFF, sizeof ones); tx = ones; }
    spi_transaction_t t = { .length = (size_t)len * 8, .tx_buffer = tx, .rx_buffer = rx };
    spi_device_polling_transmit(spi, &t);
}

/* ---- I2C ---- */

int hal_i2c_write(uint8_t addr, const uint8_t *data, int len)
{
    return i2c_master_write_to_device(I2C_NUM_0, addr, data, (size_t)len, pdMS_TO_TICKS(20)) == ESP_OK ? 0 : -1;
}

int hal_i2c_write_read(uint8_t addr, const uint8_t *wr, int wr_len, uint8_t *rd, int rd_len)
{
    return i2c_master_write_read_device(I2C_NUM_0, addr, wr, (size_t)wr_len, rd, (size_t)rd_len, pdMS_TO_TICKS(20)) == ESP_OK ? 0 : -1;
}

/* ---- pixels ---- */

void hal_led_write(const uint8_t *grb, int n_pixels)
{
    for (int i = 0; i < n_pixels; i++) led_strip_set_pixel(strip, (uint32_t)i, grb[i * 3 + 1], grb[i * 3], grb[i * 3 + 2]);
    led_strip_refresh(strip);
}

/* ---- audio ---- */

int hal_i2s_space(void)
{
    int64_t now = esp_timer_get_time();
    /* Stop the clocks once the buffer has drained so the amplifier drops
     * into standby. */
    if (i2s_running && now > i2s_end_us + 50000) { i2s_channel_disable(i2s_tx); i2s_running = false; }
    int64_t queued = i2s_end_us > now ? (i2s_end_us - now) * I2S_RATE / 1000000 : 0;
    return I2S_BUFFER_FRAMES - (int)queued;
}

void hal_i2s_write(const int16_t *samples, int n)
{
    int64_t now = esp_timer_get_time();
    size_t written;
    if (!i2s_running) { i2s_channel_enable(i2s_tx); i2s_running = true; }
    i2s_channel_write(i2s_tx, samples, (size_t)n * sizeof(int16_t), &written, pdMS_TO_TICKS(100));
    i2s_end_us = (i2s_end_us > now ? i2s_end_us : now) + (int64_t)n * 1000000 / I2S_RATE;
}

/* ---- time and logging ---- */

uint32_t hal_millis(void) { return (uint32_t)(esp_timer_get_time() / 1000); }

void hal_delay_us(uint32_t us)
{
    if (us >= 1000) { vTaskDelay(pdMS_TO_TICKS(us / 1000)); us %= 1000; }   /* needs CONFIG_FREERTOS_HZ=1000 */
    if (us) esp_rom_delay_us(us);
}

void hal_log(const char *line) { ESP_LOGI("opb", "%s", line); }

/* ---- storage ---- */

int hal_storage_read(uint32_t offset, uint8_t *dst, int len)
{
    if (!catalog || esp_partition_read(catalog, offset, dst, (size_t)len) != ESP_OK) return 0;
    return len;
}

/* ---- radio ---- */

static void (*radio_rx_handler)(const uint8_t *, int);

static void on_espnow(const esp_now_recv_info_t *info, const uint8_t *data, int len)
{
    (void)info;
    if (radio_rx_handler) radio_rx_handler(data, len);
}

void hal_espidf_radio_start(void (*handler)(const uint8_t *, int))
{
    radio_rx_handler = handler;
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) { nvs_flash_erase(); nvs_flash_init(); }
    esp_netif_init();
    esp_event_loop_create_default();
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    esp_wifi_init(&cfg);
    esp_wifi_set_storage(WIFI_STORAGE_RAM);
    esp_wifi_set_mode(WIFI_MODE_STA);
    esp_wifi_start();
    esp_now_init();
    esp_now_register_recv_cb(on_espnow);
    esp_now_peer_info_t peer = { .channel = 0, .ifidx = WIFI_IF_STA, .encrypt = false };
    memcpy(peer.peer_addr, BROADCAST, 6);
    esp_now_add_peer(&peer);
}

void hal_radio_send(const uint8_t *data, int len) { esp_now_send(BROADCAST, data, (size_t)len); }

/* ---- sleep ---- */

void hal_deep_sleep(void)
{
    /* GPIO0 to GPIO5 can wake the ESP32-C3 from deep sleep. PERIPH_EN_N is
     * left floating: its pull-up keeps the switched rail off. */
    esp_deep_sleep_enable_gpio_wakeup(1ULL << PIN_IMU_INT1, ESP_GPIO_WAKEUP_GPIO_HIGH);
    esp_deep_sleep_start();
}
