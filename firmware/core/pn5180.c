#include "pn5180.h"
#include "hal.h"
#include "pins.h"
#include "util.h"

#define CMD_WRITE_REGISTER          0x00
#define CMD_WRITE_REGISTER_OR_MASK  0x01
#define CMD_WRITE_REGISTER_AND_MASK 0x02
#define CMD_READ_REGISTER           0x04
#define CMD_READ_EEPROM             0x07
#define CMD_SEND_DATA               0x09
#define CMD_READ_DATA               0x0A
#define CMD_LOAD_RF_CONFIG          0x11
#define CMD_RF_ON                   0x16
#define CMD_RF_OFF                  0x17

#define RF_CFG_TX_ISO15693_ASK100   0x0D
#define RF_CFG_RX_ISO15693_26KBPS   0x8D

#define ISO_FLAG_HIGH_RATE   0x02
#define ISO_FLAG_INVENTORY   0x04
#define ISO_FLAG_ONE_SLOT    0x20
#define ISO_CMD_INVENTORY    0x01
#define ISO_CMD_READ_SINGLE  0x20
#define ISO_CMD_READ_MULTI   0x23
#define ISO_CMD_SYSTEM_INFO  0x2B

static int wait_busy(int level, uint32_t timeout_us)
{
    uint32_t waited = 0;
    while (hal_gpio_read(PIN_NFC_BUSY) != level) {
        if (waited >= timeout_us) return -1;
        hal_delay_us(20);
        waited += 20;
    }
    return 0;
}

/* One host-interface exchange. The PN5180 handshake is: wait for BUSY low,
 * NSS low, clock the bytes, wait for BUSY high, NSS high, wait for BUSY low.
 * A command that returns data is followed by a second frame that clocks the
 * answer out. */
static int frame(const uint8_t *tx, uint8_t *rx, int len)
{
    if (wait_busy(0, 20000) < 0) return -1;
    hal_gpio_write(PIN_NFC_NSS, 0);
    hal_delay_us(2);
    hal_spi_transfer(tx, rx, len);
    int r = wait_busy(1, 2000);
    hal_gpio_write(PIN_NFC_NSS, 1);
    if (r < 0) return -1;
    return wait_busy(0, 20000);
}

static int command(const uint8_t *tx, int tx_len, uint8_t *rx, int rx_len)
{
    if (frame(tx, 0, tx_len) < 0) return -1;
    if (rx_len > 0 && frame(0, rx, rx_len) < 0) return -1;
    return 0;
}

static int write_reg_cmd(uint8_t cmd, uint8_t reg, uint32_t v)
{
    uint8_t b[6] = { cmd, reg, (uint8_t)v, (uint8_t)(v >> 8), (uint8_t)(v >> 16), (uint8_t)(v >> 24) };
    return command(b, 6, 0, 0);
}

static int read_reg(uint8_t reg, uint32_t *v)
{
    uint8_t b[2] = { CMD_READ_REGISTER, reg }, r[4];
    if (command(b, 2, r, 4) < 0) return -1;
    *v = rd32(r);
    return 0;
}

static int read_eeprom(uint8_t addr, uint8_t *dst, uint8_t len)
{
    uint8_t b[3] = { CMD_READ_EEPROM, addr, len };
    return command(b, 3, dst, len);
}

int pn5180_init(void)
{
    hal_gpio_mode(PIN_NFC_BUSY, HAL_GPIO_INPUT);
    hal_gpio_write(PIN_NFC_NSS, 1);
    hal_gpio_mode(PIN_NFC_NSS, HAL_GPIO_OUTPUT);
    /* RESET_N is tied to the switched rail, so the reader has just come out
     * of reset. It needs a couple of milliseconds to boot. */
    hal_delay_us(3000);

    uint8_t ver[6];
    if (read_eeprom(PN5180_EE_PRODUCT_VERSION, ver, 6) < 0) return -1;
    if (ver[1] == 0xFF || (ver[0] == 0 && ver[1] == 0)) return -1;
    opb_logf("PN5180 product %u.%u firmware %u.%u eeprom %u.%u", ver[1], ver[0], ver[3], ver[2], ver[5], ver[4]);
    return 0;
}

void pn5180_release_bus(void)
{
    hal_gpio_mode(PIN_NFC_NSS, HAL_GPIO_HIGHZ);
}

int pn5180_rf_on(void)
{
    uint8_t cfg[3] = { CMD_LOAD_RF_CONFIG, RF_CFG_TX_ISO15693_ASK100, RF_CFG_RX_ISO15693_26KBPS };
    uint8_t on[2] = { CMD_RF_ON, 0x00 };
    if (command(cfg, 3, 0, 0) < 0) return -1;
    if (command(on, 2, 0, 0) < 0) return -1;
    /* Let the field settle and give a passive tag time to power up. */
    hal_delay_us(2000);
    return 0;
}

void pn5180_rf_off(void)
{
    uint8_t off[2] = { CMD_RF_OFF, 0x00 };
    command(off, 2, 0, 0);
}

/* Send an ISO 15693 request and collect the answer. Returns the number of
 * response bytes (flags byte included), 0 if no tag answered, -1 on error. */
static int transceive(const uint8_t *req, int req_len, uint8_t *resp, int max)
{
    uint8_t tx[12];
    uint32_t irq, rx_status;

    if (req_len > (int)sizeof tx - 2) return -1;
    if (write_reg_cmd(CMD_WRITE_REGISTER, PN5180_IRQ_CLEAR, 0x000FFFFF) < 0) return -1;
    /* Stop whatever is running, then enter transceive state. */
    if (write_reg_cmd(CMD_WRITE_REGISTER_AND_MASK, PN5180_SYSTEM_CONFIG, 0xFFFFFFF8) < 0) return -1;
    if (write_reg_cmd(CMD_WRITE_REGISTER_OR_MASK, PN5180_SYSTEM_CONFIG, 0x00000003) < 0) return -1;

    tx[0] = CMD_SEND_DATA;
    tx[1] = 0x00; /* all 8 bits of the last byte are valid */
    memcpy(tx + 2, req, (size_t)req_len);
    if (command(tx, req_len + 2, 0, 0) < 0) return -1;

    /* A tag starts answering about 320 us after the request ends. No start
     * of frame within 10 ms means there is no tag in the field. */
    int got_sof = 0;
    for (int ms = 0; ms < 10; ms++) {
        hal_delay_us(1000);
        if (read_reg(PN5180_IRQ_STATUS, &irq) < 0) return -1;
        if (irq & PN5180_IRQ_RX_SOF_DET) { got_sof = 1; break; }
    }
    if (!got_sof) return 0;

    for (int ms = 0; ms < 80 && !(irq & PN5180_IRQ_RX); ms++) {
        hal_delay_us(1000);
        if (read_reg(PN5180_IRQ_STATUS, &irq) < 0) return -1;
    }
    if (!(irq & PN5180_IRQ_RX)) return -1;

    if (read_reg(PN5180_RX_STATUS, &rx_status) < 0) return -1;
    int len = (int)(rx_status & 0x1FF);
    if (len == 0 || len > max) return -1;

    uint8_t rd[2] = { CMD_READ_DATA, 0x00 };
    if (command(rd, 2, resp, len) < 0) return -1;
    return len;
}

int iso15693_inventory(uint8_t uid[8])
{
    const uint8_t req[3] = { ISO_FLAG_HIGH_RATE | ISO_FLAG_INVENTORY | ISO_FLAG_ONE_SLOT, ISO_CMD_INVENTORY, 0x00 };
    uint8_t resp[12];
    int n = transceive(req, 3, resp, sizeof resp);
    if (n <= 0) return n;
    if (n < 10 || (resp[0] & 0x01)) return -1;
    memcpy(uid, resp + 2, 8);
    return 1;
}

int iso15693_read_blocks(uint8_t first, uint8_t count, uint8_t *dst)
{
    static uint8_t resp[1 + 16 * 4];
    while (count) {
        uint8_t n = count > 16 ? 16 : count;
        const uint8_t req[4] = { ISO_FLAG_HIGH_RATE, ISO_CMD_READ_MULTI, first, (uint8_t)(n - 1) };
        int len = transceive(req, 4, resp, sizeof resp);
        if (len == 1 + n * 4 && !(resp[0] & 0x01)) {
            memcpy(dst, resp + 1, (size_t)(n * 4));
        } else {
            /* Some tag chips refuse Read Multiple Blocks. Fall back to one
             * block at a time. */
            for (uint8_t i = 0; i < n; i++) {
                const uint8_t one[3] = { ISO_FLAG_HIGH_RATE, ISO_CMD_READ_SINGLE, (uint8_t)(first + i) };
                len = transceive(one, 3, resp, sizeof resp);
                if (len != 5 || (resp[0] & 0x01)) return -1;
                memcpy(dst + i * 4, resp + 1, 4);
            }
        }
        dst += n * 4;
        first = (uint8_t)(first + n);
        count = (uint8_t)(count - n);
    }
    return 0;
}

int iso15693_system_info(uint8_t *dst, int max)
{
    const uint8_t req[2] = { ISO_FLAG_HIGH_RATE, ISO_CMD_SYSTEM_INFO };
    uint8_t resp[20];
    int n = transceive(req, 2, resp, sizeof resp);
    if (n <= 1 || (resp[0] & 0x01)) return -1;
    n -= 1;
    if (n > max) n = max;
    memcpy(dst, resp + 1, (size_t)n);
    return n;
}
