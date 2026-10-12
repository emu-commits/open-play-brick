# Open Play Brick

An open design for a brick that reads the play tags in LEGO® SMART Play™ compatible sets and reacts with its own sounds and lights, built from parts anyone can buy. Non-commercial, and not affiliated with or endorsed by the LEGO Group.

**Try the emulator: https://emu-commits.github.io/open-play-brick/**

Some sets come with tags but no brick. The aim is to give those sets something to play with: put a tagged figure or tile on the brick, shake it, swing it, show it a colour, and it responds.

## Where this stands

| | |
| --- | --- |
| Firmware core (C) | Written. Runs in the emulator and passes 71 end-to-end checks. |
| Emulator | Working. Runs that same firmware in the browser against models of every chip. |
| ESP32-C3 port | Written, **not yet compiled or run on hardware**. |
| Circuit board and shell | **Not designed.** There is a netlist, a parts list and a fit estimate. |
| Real tags | Not tested. Tag format and nine tag IDs come from public reverse-engineering work. |

So this is a design proven in simulation. Whether a small antenna reads these tags through a brick wall is the first thing a hardware build has to find out. See [docs/DESIGN.md](docs/DESIGN.md) for the open risks.

## What the emulator shows

- **The firmware is the real one.** `firmware/core` is compiled to WebAssembly and loaded by the page. Nothing in the browser decides what the brick does.
- **Every hardware call becomes pin activity.** SPI bytes go to a PN5180 model that implements the reader's command set and BUSY handshake; that model passes ISO 15693 frames to a tag model. The accelerometer, colour sensor and fuel gauge are I2C register models. Audio leaves as I2S samples and is what you hear.
- **Gestures are not faked.** The Shake button feeds an acceleration waveform into the accelerometer model. The firmware reads raw samples over I2C and has to recognise the shake itself.
- **The wiring diagram is the netlist.** [`site/data/netlist.json`](site/data/netlist.json) draws the diagram and generates the firmware's `pins.h`. A CI check fails if they drift apart.
- **The logic analyzer** shows each pin on the firmware's clock, down to single bits. Press Step to run one pass of the main loop and frame it.

What is not modelled at pin level: the 13.56 MHz RF link is frame-accurate rather than waveform-accurate, USB is not simulated, and the radio is a packet stub.

## How it differs from the original

It reads the same tags and plays in the same spirit. It is not a clone.

- It **does not decrypt tags**. A tag is identified by its payload length and a CRC-32 of its raw contents, then mapped to a sound and light profile from this project's catalogue. All sounds are original and synthesised.
- It does not talk to original bricks or the LEGO app.
- One antenna, so it cannot tell where a tag sits, and it reads one tag at a time.
- USB-C charging instead of a wireless pad. No microphone.

Background and sources: [docs/RESEARCH.md](docs/RESEARCH.md).

## Run it locally

```sh
cd site && python3 -m http.server 8000
# open http://localhost:8000
```

No build step is needed: `site/firmware.wasm` is committed.

To change the firmware and rebuild (needs [zig](https://ziglang.org/), or clang with `wasm-ld`, and Node 20+):

```sh
sh tools/build_wasm.sh     # firmware/core -> site/firmware.wasm
npm test                   # pin header check + 71 end-to-end checks
```

## Add a tag

Edit [`site/data/tags.json`](site/data/tags.json). No code changes.

```json
{ "name": "Pikachu", "len": "0xNN", "crc32": "0xNNNNNNNN", "kind": "identity",
  "profile": "electric", "colour": "#ffd21f", "group": "Pokémon", "set": "72xxx" }
```

`len` is the second byte of block 0 on the tag. Scan it with a phone (NFC Tools: Read Single Block 0, command `02 20 00`), a Flipper Zero, or the brick itself, which prints the length and CRC of any tag it does not know. `crc32` is optional but recommended.

The Pokémon entries in the catalogue are **placeholders**: nobody has published those tags' lengths yet. The emulator lets you try them with made-up IDs and labels them as such; `tools/build_catalog.mjs` leaves them out of the image for a real brick. If you scan one, please send the numbers.

## Add or change a sound

Edit [`site/data/sounds.json`](site/data/sounds.json). A sound is a list of segments, each one oscillator sweeping between two frequencies. A profile maps play events (place, shake, swing, red, hit and so on) to a sound and a light animation. The file's first lines explain the fields. Reload the page to hear the change.

Adding a new gesture or colour means firmware work: see `imu_sample()` and `classify()` in [`firmware/core/sensors.c`](firmware/core/sensors.c), and the `GESTURES` table in [`site/js/chips.js`](site/js/chips.js) for the motion the emulator feeds in.

## Layout

```
site/                 the emulator (this folder is what GitHub Pages serves)
  data/netlist.json   wiring: parts, pins, nets, GPIO numbers
  data/tags.json      tag catalogue
  data/sounds.json    sounds and per-tag profiles
  js/board.js         virtual clock, nets, firmware hardware calls
  js/chips.js         chip models: PN5180, tag, LIS2DH12, TCS34725, MAX17048, pixels, battery
  js/catalog.js       packs the JSON into the binary the firmware reads
  js/diagram.js, analyzer.js, decode.js, brickview.js, main.js   the page
firmware/core/        portable C: drivers, gesture detection, synthesiser, play logic
firmware/port-wasm/   glue for the emulator
firmware/port-espidf/ glue for the ESP32-C3 (untested)
test/run.mjs          boots the firmware headlessly and plays through every feature
docs/                 research notes and hardware design
```

## Deploying

Pushing to `main` runs the tests and publishes `site/` to GitHub Pages through `.github/workflows/pages.yml`. In a fork, set Settings → Pages → Source to "GitHub Actions".

## Credits

- [node-smartplay](https://github.com/nathankellenicki/node-smartplay) by Nathan Kellenicki, for the tag format, hardware notes and play-engine analysis.
- [LegoSmartPlay](https://github.com/Ellerbach/LegoSmartPlay) by Laurent Ellerbach, for showing that an ESP32-C3 and a PN5180 read these tags, and for the breadboard wiring this design keeps.
- [Coffee & Fun](https://www.coffeeandfun.com/blog/reverse-engineering-lego-smart-play-nfc-part-1/) for early tag reads.

## Legal

LEGO® and SMART Play™ are trademarks of the LEGO Group, which does not sponsor, authorise or endorse this project. Character and product names are used only to say what a tag is.

This repository contains no LEGO firmware, audio or tag data. Simulated tags use the public 5-byte header followed by generated filler. The CRC-32 values in the catalogue are checksums computed from tag dumps other researchers published; they identify a tag and cannot be turned back into its contents.

This is an interoperability project for personal, non-commercial use. It is not legal advice: if you plan to distribute hardware, check the rules where you live.

Code is under the [MIT licence](LICENSE).
