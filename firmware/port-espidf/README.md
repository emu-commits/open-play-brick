# ESP32-C3 port

**Status: not yet compiled or run on hardware.** The core firmware in `../core` is exercised by the emulator and its tests. This folder is the glue that maps the same hardware calls onto ESP-IDF 5.x drivers, written from the API documentation as a starting point for bring-up.

## Build and flash

```sh
. $IDF_PATH/export.sh
idf.py set-target esp32c3
idf.py build flash monitor
```

## Flash the catalogue

The tag and sound catalogue lives in its own partition so it can be updated without rebuilding the firmware.

```sh
node ../../tools/build_catalog.mjs
parttool.py --port /dev/ttyACM0 write_partition --partition-name catalog --input ../../build/catalog.bin
```

## Breadboard build

The same firmware runs on an ESP32-C3 Super Mini wired to breakout modules, using the GPIO numbers in `site/data/netlist.json`. On a breadboard you can skip the load switch: tie the PN5180 module's RST and the pixel supply to 3V3 and leave GPIO2 unconnected.

The C library provides `memcpy`, `memset` and `memcmp` here, so `port-wasm/port.c` is not part of this build.
