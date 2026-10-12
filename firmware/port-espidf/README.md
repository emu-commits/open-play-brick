# ESP32-C6 port

**Status: compiles and links with ESP-IDF 5.5; not yet run on hardware.** The core firmware in `../core` is exercised by the emulator and its tests. This folder maps the same hardware calls onto ESP-IDF drivers. Most people should not need it: the [build page](https://emu-commits.github.io/open-play-brick/build.html) installs a prebuilt image from the browser.

## Build and flash

```sh
. $IDF_PATH/export.sh
idf.py set-target esp32c6
idf.py build flash monitor
```

## Flash the catalogue

The tag and sound catalogue lives in its own partition so it can be updated without rebuilding the firmware.

```sh
node ../../tools/build_catalog.mjs
parttool.py --port /dev/ttyACM0 write_partition --partition-name catalog --input ../../build/catalog.bin
```

## Other ESP32-C6 boards

The pin numbers are GPIO numbers from `site/data/netlist.json`, so any ESP32-C6 board that brings those GPIOs out will run the same image. A board without a MAX17048 fuel gauge will log an error for it and carry on without battery readings.

The C library provides `memcpy`, `memset` and `memcmp` here, so `port-wasm/port.c` is not part of this build.
