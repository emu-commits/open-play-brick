#!/bin/sh
# Compile the firmware core to WebAssembly for the emulator.
# Needs zig (any recent version) or clang with the wasm32 target and wasm-ld.
set -e
cd "$(dirname "$0")/.."

SRC="firmware/core/app.c firmware/core/catalog.c firmware/core/output.c firmware/core/pn5180.c firmware/core/sensors.c firmware/core/util.c firmware/port-wasm/port.c"
FLAGS="-O2 -std=c11 -Wall -Wextra -ffreestanding -fno-builtin -nostdlib -Ifirmware/core"
LINK="-Wl,--no-entry -Wl,--strip-all \
  -Wl,--export=fw_init -Wl,--export=fw_loop -Wl,--export=fw_on_radio -Wl,--export=fw_status"

if command -v zig >/dev/null 2>&1; then
  CC="zig cc -target wasm32-freestanding"
else
  CC="clang --target=wasm32"
fi

$CC $FLAGS $LINK $SRC -o site/firmware.wasm
ls -l site/firmware.wasm
