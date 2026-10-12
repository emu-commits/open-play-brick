#!/bin/sh
# Collect the ESP32-C6 firmware images and the catalogue into site/flash/ with
# a manifest for the browser installer (ESP Web Tools) on site/build.html.
# Run after `idf.py build` in firmware/port-espidf.
set -e
cd "$(dirname "$0")/.."
B=firmware/port-espidf/build
VERSION=$(sed -n 's/#define FW_VERSION "\(.*\)"/\1/p' firmware/core/app.h)

node tools/build_catalog.mjs
mkdir -p site/flash
cp $B/bootloader/bootloader.bin site/flash/bootloader.bin
cp $B/partition_table/partition-table.bin site/flash/partition-table.bin
cp $B/open_play_brick.bin site/flash/firmware.bin
cp build/catalog.bin site/flash/catalog.bin

# Offsets match firmware/port-espidf/partitions.csv.
cat > site/flash/manifest.json <<JSON
{
  "name": "Open Play Brick",
  "version": "$VERSION",
  "new_install_prompt_erase": true,
  "builds": [
    {
      "chipFamily": "ESP32-C6",
      "parts": [
        { "path": "bootloader.bin", "offset": 0 },
        { "path": "partition-table.bin", "offset": 32768 },
        { "path": "firmware.bin", "offset": 65536 },
        { "path": "catalog.bin", "offset": 1638400 }
      ]
    }
  ]
}
JSON
ls -l site/flash
