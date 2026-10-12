/* ESP32-C6 port of the hardware abstraction layer (ESP-IDF 5.3 or newer).
 *
 * STATUS: this compiles and links, and the core firmware it serves is the
 * same code the emulator runs, but it has not yet been run on a real board.
 * Expect to adjust it during bring-up. The places most likely to need it are
 * marked CHECK ON HARDWARE.
 */
#include <string.h>
#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "driver/i2s_std.h"
#include "driver/rmt_tx.h"
#include "driver/spi_master.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_now.h"
#include "esp_partition.h"
#include "esp_rom_sys.h"
#include "esp_sleep.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"

#include "hal.h"
#include "pins.h"

#define I2S_RATE     16000
#define I2C_TIMEOUT  20     /* ms */
#define MAX_I2C_DEVS 4

static spi_device_handle_t spi;
static i2c_master_bus_handle_t i2c_bus;
static struct { uint8_t addr; i2c_master_dev_handle_t dev; } i2c_devs[MAX_I2C_DEVS];
static rmt_channel_handle_t led_chan;
static rmt_encoder_handle_t led_encoder;
static i2s_chan_handle_t i2s_tx, i2s_rx;
static const esp_partition_t *catalog;
static int64_t i2s_end_us;
static bool radio_ready, radio_on;
static void (*radio_rx_handler)(const uint8_t *, int);
static const uint8_t BROADCAST[6] = { 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF };

void hal_espidf_init(void (*on_radio)(const uint8_t *, int))
{
    radio_rx_handler = on_radio;

    spi_bus_config_t bus = { .mosi_io_num = PIN_SPI_MOSI, .miso_io_num = PIN_SPI_MISO, .sclk_io_num = PIN_SPI_SCK,
                             .quadwp_io_num = -1, .quadhd_io_num = -1 };
    spi_device_interface_config_t dev = { .clock_speed_hz = 2000000, .mode = 0, .spics_io_num = -1, .queue_size = 1 };
    ESP_ERROR_CHECK(spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_DISABLED));
    ESP_ERROR_CHECK(spi_bus_add_device(SPI2_HOST, &dev, &spi));

    /* The Feather and the sensor breakouts carry the I2C pull-ups. */
    i2c_master_bus_config_t i2c = { .i2c_port = I2C_NUM_0, .sda_io_num = PIN_I2C_SDA, .scl_io_num = PIN_I2C_SCL,
                                    .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7 };
    ESP_ERROR_CHECK(i2c_new_master_bus(&i2c, &i2c_bus));

    /* Pixel data: 800 kHz, 0 = 0.3 us high, 1 = 0.6 us high, at 0.1 us per tick. */
    rmt_tx_channel_config_t rmt = { .gpio_num = PIN_LED_DATA, .clk_src = RMT_CLK_SRC_DEFAULT, .resolution_hz = 10000000,
                                    .mem_block_symbols = 64, .trans_queue_depth = 1 };
    ESP_ERROR_CHECK(rmt_new_tx_channel(&rmt, &led_chan));
    rmt_bytes_encoder_config_t enc = {
        .bit0 = { .level0 = 1, .duration0 = 3, .level1 = 0, .duration1 = 9 },
        .bit1 = { .level0 = 1, .duration0 = 6, .level1 = 0, .duration1 = 6 },
        .flags.msb_first = 1,
    };
    ESP_ERROR_CHECK(rmt_new_bytes_encoder(&enc, &led_encoder));
    ESP_ERROR_CHECK(rmt_enable(led_chan));

    /* One I2S port, both directions, shared clocks. 32-bit slots because the
     * microphone needs 64 clocks per frame; 16 bits of data sit at the top of
     * the left slot. The amplifier (SD_MODE high) plays the left slot.
     * CHECK ON HARDWARE: microphone sample alignment and level. */
    i2s_chan_config_t chan = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    chan.dma_desc_num = 8;
    chan.dma_frame_num = HAL_I2S_BUFFER / 8;
    chan.auto_clear = true;
    ESP_ERROR_CHECK(i2s_new_channel(&chan, &i2s_tx, &i2s_rx));
    i2s_std_config_t std = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(I2S_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO),
        .gpio_cfg = { .mclk = I2S_GPIO_UNUSED, .bclk = PIN_I2S_BCLK, .ws = PIN_I2S_LRCLK, .dout = PIN_I2S_DOUT, .din = PIN_I2S_DIN },
    };
    std.slot_cfg.slot_bit_width = I2S_SLOT_BIT_WIDTH_32BIT;
    ESP_ERROR_CHECK(i2s_channel_init_std_mode(i2s_tx, &std));
    ESP_ERROR_CHECK(i2s_channel_init_std_mode(i2s_rx, &std));
    ESP_ERROR_CHECK(i2s_channel_enable(i2s_tx));
    ESP_ERROR_CHECK(i2s_channel_enable(i2s_rx));

    catalog = esp_partition_find_first(ESP_PARTITION_TYPE_DATA, 0x40, "catalog");
}

/* ---- GPIO ---- */

void hal_gpio_mode(int pin, int mode)
{
    /* gpio_config also switches the pad to its GPIO function, which matters
     * for GPIO4 to 7: they start out as JTAG pins. */
    gpio_config_t cfg = {
        .pin_bit_mask = 1ULL << pin,
        .mode = mode == HAL_GPIO_OUTPUT ? GPIO_MODE_OUTPUT : mode == HAL_GPIO_INPUT ? GPIO_MODE_INPUT : GPIO_MODE_DISABLE,
    };
    gpio_config(&cfg);
}

void hal_gpio_write(int pin, int level) { gpio_set_level(pin, level); }
int  hal_gpio_read(int pin) { return gpio_get_level(pin); }

void hal_gpio_hold(int pin, int on)
{
    /* On the ESP32-C6 a held pad keeps its level through deep sleep. */
    if (on) gpio_hold_en(pin);
    else gpio_hold_dis(pin);
}

/* ---- SPI ---- */

void hal_spi_transfer(const uint8_t *tx, uint8_t *rx, int len)
{
    static uint8_t ones[96];
    if (!tx) {
        memset(ones, 0xFF, sizeof ones);
        tx = ones;
        if (len > (int)sizeof ones) len = sizeof ones;
    }
    spi_transaction_t t = { .length = (size_t)len * 8, .tx_buffer = tx, .rx_buffer = rx };
    spi_device_polling_transmit(spi, &t);
}

/* ---- I2C ---- */

static i2c_master_dev_handle_t i2c_dev(uint8_t addr)
{
    for (int i = 0; i < MAX_I2C_DEVS; i++) {
        if (i2c_devs[i].dev && i2c_devs[i].addr == addr) return i2c_devs[i].dev;
        if (!i2c_devs[i].dev) {
            i2c_device_config_t cfg = { .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = addr, .scl_speed_hz = 400000 };
            if (i2c_master_bus_add_device(i2c_bus, &cfg, &i2c_devs[i].dev) != ESP_OK) return NULL;
            i2c_devs[i].addr = addr;
            return i2c_devs[i].dev;
        }
    }
    return NULL;
}

int hal_i2c_write(uint8_t addr, const uint8_t *data, int len)
{
    i2c_master_dev_handle_t d = i2c_dev(addr);
    return d && i2c_master_transmit(d, data, (size_t)len, I2C_TIMEOUT) == ESP_OK ? 0 : -1;
}

int hal_i2c_write_read(uint8_t addr, const uint8_t *wr, int wr_len, uint8_t *rd, int rd_len)
{
    i2c_master_dev_handle_t d = i2c_dev(addr);
    return d && i2c_master_transmit_receive(d, wr, (size_t)wr_len, rd, (size_t)rd_len, I2C_TIMEOUT) == ESP_OK ? 0 : -1;
}

/* ---- pixels ---- */

void hal_led_write(const uint8_t *grb, int n_pixels)
{
    rmt_transmit_config_t cfg = { .loop_count = 0 };
    if (rmt_transmit(led_chan, led_encoder, grb, (size_t)n_pixels * 3, &cfg) == ESP_OK)
        rmt_tx_wait_all_done(led_chan, 20);
}

/* ---- audio ---- */

int hal_i2s_space(void)
{
    int64_t now = esp_timer_get_time();
    int64_t queued = i2s_end_us > now ? (i2s_end_us - now) * I2S_RATE / 1000000 : 0;
    return HAL_I2S_BUFFER - (int)queued;
}

void hal_i2s_write(const int16_t *samples, int n)
{
    int64_t now = esp_timer_get_time();
    size_t written;
    i2s_channel_write(i2s_tx, samples, (size_t)n * sizeof(int16_t), &written, pdMS_TO_TICKS(100));
    i2s_end_us = (i2s_end_us > now ? i2s_end_us : now) + (int64_t)n * 1000000 / I2S_RATE;
}

int hal_i2s_read(int16_t *samples, int n)
{
    /* Collect whatever has arrived without blocking, and hand over a block
     * only once it is complete. */
    static int16_t pending[64];
    static size_t have;
    size_t want = (size_t)n * sizeof(int16_t), got = 0;
    if (want > sizeof pending) return 0;
    i2s_channel_read(i2s_rx, (uint8_t *)pending + have, want - have, &got, 0);
    have += got;
    if (have < want) return 0;
    memcpy(samples, pending, want);
    have = 0;
    return n;
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

static void on_espnow(const esp_now_recv_info_t *info, const uint8_t *data, int len)
{
    (void)info;
    if (radio_rx_handler) radio_rx_handler(data, len);
}

static void radio_setup(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) { nvs_flash_erase(); nvs_flash_init(); }
    esp_netif_init();
    esp_event_loop_create_default();
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    esp_wifi_init(&cfg);
    esp_wifi_set_storage(WIFI_STORAGE_RAM);
    esp_wifi_set_mode(WIFI_MODE_STA);
    radio_ready = true;
}

/* The receiver draws tens of milliamps, so it runs only while a tag that
 * uses it is on the brick. */
void hal_radio_enable(int on)
{
    if ((bool)on == radio_on) return;
    if (on) {
        if (!radio_ready) radio_setup();
        esp_wifi_start();
        esp_now_init();
        esp_now_register_recv_cb(on_espnow);
        esp_now_peer_info_t peer = { .channel = 0, .ifidx = WIFI_IF_STA, .encrypt = false };
        memcpy(peer.peer_addr, BROADCAST, 6);
        esp_now_add_peer(&peer);
    } else {
        esp_now_deinit();
        esp_wifi_stop();
    }
    radio_on = on;
}

void hal_radio_send(const uint8_t *data, int len)
{
    if (radio_on) esp_now_send(BROADCAST, data, (size_t)len);
}

/* ---- sleep ---- */

void hal_deep_sleep(void)
{
    /* GPIO0 to 7 can wake the ESP32-C6 from deep sleep. Pins the core put on
     * hold (sensor power, reader reset, pixel power) keep their levels. */
    i2s_channel_disable(i2s_tx);
    i2s_channel_disable(i2s_rx);
    esp_sleep_enable_ext1_wakeup_io(1ULL << PIN_IMU_INT1, ESP_EXT1_WAKEUP_ANY_HIGH);
    esp_deep_sleep_start();
}
