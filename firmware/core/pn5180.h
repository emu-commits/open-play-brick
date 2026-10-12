/* NXP PN5180 NFC frontend driver (SPI host interface) plus the small part of
 * ISO 15693 the brick needs: inventory and block reads. */
#ifndef OPB_PN5180_H
#define OPB_PN5180_H

#include <stdint.h>

/* Registers */
#define PN5180_SYSTEM_CONFIG   0x00
#define PN5180_IRQ_ENABLE      0x01
#define PN5180_IRQ_STATUS      0x02
#define PN5180_IRQ_CLEAR       0x03
#define PN5180_RX_STATUS       0x13
#define PN5180_RF_STATUS       0x1D

/* IRQ_STATUS bits */
#define PN5180_IRQ_RX          (1u << 0)
#define PN5180_IRQ_TX          (1u << 1)
#define PN5180_IRQ_IDLE        (1u << 2)
#define PN5180_IRQ_TX_RFON     (1u << 9)
#define PN5180_IRQ_RX_SOF_DET  (1u << 14)
#define PN5180_IRQ_GENERAL_ERR (1u << 17)

/* EEPROM addresses */
#define PN5180_EE_PRODUCT_VERSION  0x10
#define PN5180_EE_FIRMWARE_VERSION 0x12
#define PN5180_EE_EEPROM_VERSION   0x14

/* Returns 0 if the reader answered with a plausible version, -1 otherwise. */
int  pn5180_init(void);
/* Hold the reader in reset, which is its hard power-down state. */
void pn5180_power_down(void);

int  pn5180_rf_on(void);   /* loads the ISO 15693 RF configuration and turns the field on */
void pn5180_rf_off(void);

/* ISO 15693 inventory, one slot. Returns 1 and fills uid (8 bytes, LSB first
 * as sent on air) if a tag answered, 0 if none, -1 on reader error. */
int  iso15693_inventory(uint8_t uid[8]);

/* Read `count` 4-byte blocks starting at `first`. Returns 0 on success. */
int  iso15693_read_blocks(uint8_t first, uint8_t count, uint8_t *dst);

/* Get System Information. Returns response length (without flags) or -1. */
int  iso15693_system_info(uint8_t *dst, int max);

#endif
