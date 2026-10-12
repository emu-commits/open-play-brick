# Hardware design, rev A

Status: **paper design, proven in simulation only.** No board has been laid out or built. The emulator runs the real firmware against models of these parts; it cannot tell you whether the antenna reads through the shell or whether everything fits. The open risks are listed at the end.

The machine-readable version of this design is [`site/data/netlist.json`](../site/data/netlist.json). The emulator's diagram and the firmware's `pins.h` are both generated from it.

## Parts

Every part is a catalogue item from a large distributor, chosen to fit inside a 2 x 4 brick five plates tall.

| Ref | Part | Job | Package | Replaces in the original |
| --- | --- | --- | --- | --- |
| U1 | ESP32-C3FH4 | MCU, radio, USB, 4 MB flash | QFN-32, 5 x 5 mm | EM9305 |
| U2 | NXP PN5180 | ISO 15693 reader | HVQFN-40, 6 x 6 mm | tag reader in the ASIC |
| ANT1 | PCB or flex loop, about 28 x 12 mm | 13.56 MHz antenna | on the board edge | side-wall coils |
| U3 | ST LIS2DH12 | accelerometer, wake-on-motion | LGA-12, 2 x 2 mm | accelerometer |
| U4 | ams TCS34725 | colour sensor | FN-6, 2 x 2.4 mm | colour sensor |
| U5 | MAX17048 | fuel gauge | TDFN-8, 2 x 2 mm | |
| U6 | MAX98357A | I2S class-D amplifier | TQFN-16, 3 x 3 mm | analog synthesiser output |
| LS1 | 8 ohm micro speaker | sound | 15 x 11 x 3 mm | speaker |
| D1 | 9 x SK6805-EC15 | 8 array pixels + 1 lamp for the colour sensor | 1.5 x 1.5 mm each | LED array, sensor LEDs |
| Q1 | P-channel MOSFET | switched 3.3 V rail | SOT-723 | |
| U7 | 3.3 V LDO, 300 mA (e.g. TLV75533) | regulator | SOT-23-5 or DFN | |
| U8 | MCP73831 | Li-Po charger, set to about 50 mA | DFN-8, 2 x 3 mm | inductive charger |
| BT1 | 401225 Li-Po pouch, about 100 mAh | battery | 4 x 12 x 25 mm | 45 mAh pouch |
| J1 | USB-C receptacle, mid-mount | charge, flash, console | | charging pad |

## Pin map

The ESP32-C3FH4 exposes 15 usable GPIOs (0 to 10 and 18 to 21). All 15 are used.

| GPIO | Net | Notes |
| --- | --- | --- |
| 0 | IMU_INT1 | GPIO0 to 5 can wake the chip from deep sleep |
| 1 | NFC_BUSY | |
| 2 | PERIPH_EN_N | Low turns the switched rail on. The 10k pull-up to 3V3 keeps the rail off in reset and sleep, and also satisfies the GPIO2 boot strap. |
| 3 | LED_DATA | |
| 4, 5, 6, 10 | SPI_SCK, SPI_MOSI, SPI_MISO, NFC_NSS | Same pins as the Ellerbach breadboard build |
| 7, 20, 21 | I2S_DOUT, I2S_BCLK, I2S_LRCLK | |
| 8, 9 | I2C_SDA, I2C_SCL | 2.2k pull-ups. GPIO8 and GPIO9 are boot straps that must be high, which the pull-ups ensure. A pad to ground on GPIO9 is the "boot" button for recovery. |
| 18, 19 | USB_DN, USB_DP | Built-in USB Serial/JTAG |

Choices forced by the pin count:

- **No battery ADC pin.** A fuel gauge on the I2C bus reports voltage, charge and charge rate, which also tells the firmware when USB power is present.
- **No reader reset pin.** The PN5180's RESET_N is tied to the switched rail, so cutting and restoring the rail resets it.
- **No lamp pin for the colour sensor.** A ninth pixel on the LED chain sits beside the sensor window and is switched in software.
- **No microphone.** There is no pin left for one. An ESP32-C6 (22 GPIOs in the same package size) would make room and adds 802.15.4; it is the obvious rev B candidate.

## Power

- Battery feeds the LDO (always-on 3V3) and the amplifier directly.
- 3V3 feeds the MCU, accelerometer, colour sensor.
- Q1 switches 3V3_SW to the reader, the pixels and the amplifier's enable pin.

The switched rail exists because of the pixels: nine SK6805s draw roughly 0.5 mA each when dark, about 4.5 mA in total, which would flatten a 100 mAh cell in under a day of "sleep".

Estimated current, from datasheet typical values (these are the numbers the emulator's power tab uses, and they are estimates, not measurements):

| State | Estimate |
| --- | --- |
| Deep sleep, waiting for motion | about 0.07 mA: weeks of standby |
| Awake, no tag, pixels dim | about 37 mA: under three hours on 100 mAh, which is why it sleeps after 30 s |
| Tag active, pixels and background sound | about 58 mA: roughly an hour and a half on 100 mAh |

Two things would cut the awake figure and are not done yet: using the PN5180's low-power card detection instead of a full field pulse every 250 ms, and letting the MCU light-sleep between loop passes.

## Does it fit?

Outer envelope 31.8 x 15.8 x 16.0 mm. With 1.2 mm walls, a 1.2 mm top and a floor 2.8 mm up (to leave the stud recess underneath), the cavity is about 29.4 x 13.4 x 12.0 mm.

| Layer, top to bottom | Height |
| --- | --- |
| Speaker under the top face | 3.0 mm |
| Gap and light-mixing space | 0.8 mm |
| Parts on top of the board | 1.0 mm |
| Board, 28.6 x 12.6 mm, 4 layers | 0.8 mm |
| Parts under the board | 1.0 mm |
| Battery | 4.0 mm |
| Foam and tolerance | 0.8 mm |
| **Total** | **11.4 mm of 12.0 mm** |

Board area is 360 mm². The ICs listed total about 110 mm² before passives, crystal, antenna matching and the USB-C receptacle. It is tight but plausible on two sides. USB-C at one short end costs about 9 x 7 mm of board edge.

This is arithmetic, not CAD. Nothing here has been modelled in 3D.

## What it does not do

- It does not decrypt tags, so it cannot reproduce the original's sounds or scripts. Each tag gets a sound and light profile from this project's own catalogue.
- It does not talk to original bricks or to the LEGO app. Brick-to-brick play uses ESP-NOW between Open Play Bricks only.
- It cannot tell where on the brick a tag sits. There is one antenna.
- It reads one tag at a time (one-slot inventory). The original tracks a figure and a tile together.
- It charges over USB-C, not wirelessly.
- "Roll" is detected from gravity flipping over, because there is no gyroscope.

## Open risks, in the order I would test them

1. **Antenna and read range.** A 28 x 12 mm loop next to a battery and a speaker magnet, reading a small tag through plastic. This decides whether the concept works and can only be answered on a bench. Ferrite sheet between antenna and battery is likely needed.
2. **The ESP-IDF port** has not been compiled or run.
3. **SK6805-EC15 at 3.3 V** is below its nominal supply. They usually work, with weaker blue. Otherwise feed them from VBAT through the switch.
4. **PN5180 supply.** Transmit current pulses on a 300 mA LDO shared with the MCU.
5. **Mechanical fit**, above.
6. **Acoustics.** A 15 x 11 mm speaker in a sealed 2 x 4 brick will be quiet and thin.
7. **Gesture thresholds** were tuned against synthetic motion in the emulator. Real hands will need retuning.

## Shell

Not designed yet. If you make one, note that the stud-and-tube interface is free to use where the old patents have expired, but brick shapes and the LEGO name and logo are protected as trademarks in some countries. Do not put LEGO branding on it or sell it as a LEGO product.
