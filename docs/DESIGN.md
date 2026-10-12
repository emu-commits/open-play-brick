# Hardware design, rev B

Status: **the firmware runs in simulation and compiles for the ESP32-C6. No hardware has been built.** The emulator runs the real firmware against models of these parts. It cannot tell you how far the reader reads or whether a wire is loose. Open risks are at the end.

The machine-readable design is [`site/data/netlist.json`](../site/data/netlist.json). The emulator's diagram, the firmware's `pins.h`, and the parts list and wiring table in the [build guide](../site/BUILD.md) are all generated from it.

## What changed from rev A, and why

Rev A was a paper design for a board the size of a 2 x 4 brick, using an ESP32-C3. It was not something a person could build without designing and assembling a fine-pitch circuit board. Rev B puts buildability first.

- **Ready-made boards instead of bare chips.** Every part is a breakout board with 0.1 inch pads. The cost is size: this is a small box, not a brick.
- **ESP32-C6 instead of ESP32-C3.** The C3 has 15 usable GPIOs and rev A used all of them, with three compromises to fit: no microphone, no reset line for the reader, and the colour sensor's lamp borrowed from the pixel chain. The C6 has 22. The Adafruit ESP32-C6 Feather also has the battery charger, the fuel gauge, the regulator and USB-C on board, which removes four parts from the build.
- **Microphone added.** One more GPIO, because it shares the amplifier's clocks. It is used to hear a clap. The firmware reduces audio to a loudness number every 4 ms and discards the samples: nothing is recorded, stored or sent.
- **Reader switched off by its reset pin** rather than by cutting its power.
- **Lamp is a plain GPIO**, driving the white LED on the colour sensor board.
- **Radio only on when needed.** The receiver draws tens of milliamps, so it runs only while a combat tag is on the brick.

## Parts and pins

See the [build guide](../site/BUILD.md) for the parts list with order numbers and prices, and the full wiring table.

| GPIO | Feather pad | Net | Notes |
| --- | --- | --- | --- |
| 0 | 0 | NFC_NSS | |
| 1 | A0 | IMU_INT1 | GPIO0 to 7 can wake the C6 from deep sleep |
| 2 | A5 | NFC_BUSY | |
| 3 | A4 | NFC_RST | Low = reader in hard power-down |
| 4 | A1 | I2S_DIN | Microphone data |
| 5, 6, 7 | A3, A2, 7 | I2S_BCLK, I2S_LRCLK, I2S_DOUT | Clocks shared by amplifier and microphone |
| 14 | 14 | LED_DATA | |
| 16 | TX | LAMP_EN | |
| 17 | RX | PERIPH_EN | Pixel power switch and amplifier enable |
| 18, 19 | SCL, SDA | I2C | The STEMMA QT socket |
| 20 | (internal) | QT_PWR | Powers the QT socket. Held high in sleep so the accelerometer can wake the brick |
| 21, 22, 23 | SCK, MO, MI | SPI | |
| 12, 13 | (USB-C) | USB | |

Free: GPIO8, GPIO9 (boot button and the Feather's own pixel) and GPIO15 (red LED).

## Power

- The Feather's regulator supplies 3.3 V to the MCU, the reader's logic, the sensors and the microphone.
- The reader's transmitter, the amplifier and the pixels run straight from the battery (3.2 to 4.2 V).
- In sleep: the reader is held in reset, the amplifier is shut down by its SD pin, and the optional MOSFET board opens the pixels' ground. The sensor socket stays powered so the accelerometer's interrupt can wake the MCU.

Estimated current from datasheet typical values. These are the figures the emulator's power tab uses. They are estimates, not measurements.

| State | Estimate | On a 500 mAh cell |
| --- | --- | --- |
| Asleep | about 1 mA, most of it the Feather's own pixel on the sensor rail | about three weeks |
| Asleep, no MOSFET board | about 9 mA | two days |
| Awake, no tag | about 48 mA | 10 hours, but it sleeps after 30 s |
| Tag active, lights and sound | about 88 mA | 5 to 6 hours |
| Combat tag active (radio on) | about 160 mA | 3 hours |

## What it does not do

- It does not decrypt tags, so it cannot reproduce the original's sounds or scripts.
- It does not talk to original bricks or to the LEGO app. Brick-to-brick play uses ESP-NOW between Open Play Bricks only.
- One antenna: it cannot tell where a tag sits, and it reads one tag at a time.
- "Roll" is detected from gravity flipping over, because there is no gyroscope.
- No wireless charging.

## Open risks, in the order to test them

1. **Read range.** The reader's transmitter runs from the battery, not the 5 V its module is specified for, and the tags are small. This decides whether the build works. The fallback is a 5 V boost board on the reader's supply.
2. **First run on hardware.** The ESP-IDF port compiles and links. Places most likely to need adjusting are marked `CHECK ON HARDWARE` in `firmware/port-espidf/main/hal_espidf.c`: microphone sample alignment, and pins held through deep sleep.
3. **PN5180 module differences.** Boards differ in which supply pads they have and whether they carry their own regulator.
4. **Pixel stick on battery voltage.** It is specified for 4 to 7 V and will be run at 3.2 to 4.2 V. Expect it to work with reduced brightness and a colour shift as the battery empties.
5. **Low-side pixel switching.** The firmware floats the data pin before switching off, which should prevent the stick being powered through it. Needs checking.
6. **Clap and gesture thresholds** were tuned against synthetic signals in the emulator and will need retuning against real hands and rooms.
7. **Colour sensor supply.** Adafruit has retired its TCS34725 board. Copies are plentiful today. The APDS-9960 is the likely replacement if that changes; it would need a new driver.

## Towards a brick-sized board

The original is 2 x 4 studs and five plates tall, about 31.8 x 15.8 x 16 mm. Fitting this design into that needs a custom four-layer board with the bare chips (all exist in packages of 6 mm or less), a pouch cell of around 100 mAh, a 15 x 11 mm speaker and an antenna loop around the board edge. On paper the parts fit the volume. Nothing has been laid out, and the small antenna makes risk 1 much harder. The sensible order is to prove the module build first, then shrink it. Assembly would be by a board house, not by hand.

If you make a shell: the stud-and-tube interface is free to use where the old patents have expired, but brick shapes and the LEGO name and logo are protected as trademarks in some countries. Do not put LEGO branding on it or sell it as a LEGO product.
