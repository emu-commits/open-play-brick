# Brick board (rev C)

A custom circuit board pair and a printed case for Open Play Brick. This is step 3 of the [roadmap](../../docs/ROADMAP.md): a board a board house can make and assemble from these files.

**Status: a first draft. Nothing here has been built, ordered, or reviewed by anyone with RF board-layout experience.** The roadmap's advice still holds: test a small NFC antenna on the bench (step 2) before paying for these boards.

## Size: 2 x 6, not 2 x 4

Rev C is the roadmap's fallback size: a **2 x 6 brick, six plates (19.2 mm) tall**. It uses the ready-made ESP32-C6-MINI-1 module with its built-in antenna, so there is no bare-chip 2.4 GHz design to verify. The module is 13.2 x 16.6 mm. It fits across the cavity (13.8 mm inside), but with the clear area its antenna needs beyond its end, it takes most of a 2 x 4 brick's length. The extra two studs give room for the rest of the circuit, the battery and the speaker.

A 2 x 4 version would need the bare chip and a chip antenna. That is a separate design.

## What is in it

Two boards, stacked and joined by a 1.27 mm 2 x 5 board-to-board header: a 6-layer main board and a 4-layer face board, both 0.8 mm thick.

| Board | Size | Contents |
|---|---|---|
| main (6 layers) | 45.4 x 13.4 mm | ESP32-C6-MINI-1 (underside), USB-C with ESD protection, LiPo charger (TP4054, 50 mA), battery/USB power path, 3.3 V regulator (RT9080, 2 µA quiescent), battery voltage divider, NFC reader (PN5180) with its 27.12 MHz crystal, amplifier (MAX98357A), accelerometer (LIS2DH12), pixel supply switch and data level shifter, battery and speaker sockets |
| face (4 layers) | 24.4 x 13.4 mm | Printed 6-turn NFC loop with its matching network, eight WS2812B-2020 pixels, colour sensor (TCS34725) and its white lamp |

The face board sits on top so the NFC loop is as close as possible to the tag on top of the brick. Its pixels and colour sensor sit inside the loop. For that reason the face board has **no copper pours**: a solid area of copper inside the loop would act as a shorted turn and weaken the field. Its inner layers carry only a few tracks.

The GPIO numbers match the rev B module build, so the same firmware image runs on both. `gen_board.py` fails if they drift from `firmware/core/pins.h`.

### Cut from rev B to fit

A 2 x 6 brick's main board was about 79% covered by parts and the clearances round them, too dense to route. Three things went to make room:

- **No microphone.** The clap detector hears silence and never fires. GPIO4, its data line, now reads the battery instead.
- **No fuel gauge.** A 1 MΩ / 1 MΩ divider (about 2 µA) feeds the battery voltage to GPIO4 (ADC1 channel 4). The firmware still probes for the MAX17048, finds nothing and carries on. Reading the divider needs a small firmware change that has not been made yet.
- **Smaller sockets.** Battery and speaker both plug into JST-SH 1.0 mm 2-pin sockets (2.9 mm tall). The JST-PH battery socket, with the room its plug needed, took 124 mm² of the top side. The 1.25 mm speaker socket it replaces was 3.53 mm tall, more than the 3.3 mm gap above the speaker.

One part was added: U10, a single-gate buffer (SN74LV1T34) powered from the pixel supply. The pixels run from VSYS, up to about 4.7 V on USB, where a WS2812 needs 0.7 x VDD (about 3.3 V) on its data input. A 3.3 V GPIO is marginal there.

## What to buy besides the boards

No soldering: everything plugs in.

- **Battery:** a 3.7 V single-cell LiPo with a protection circuit, at most 24 mm long, 13 mm wide and 4.5 mm thick (the bay is 24 x 13.8 mm; the module above it leaves 4.9 mm). A "401220" cell (4 x 12 x 20 mm, about 60 to 80 mAh) fits, with a **JST-SH 1.0 mm 2-pin** plug. LiPo plug polarity is not standardised: before plugging in, check that the red wire lands on pin 2, marked `+` on the board.
- **Speaker:** 8 Ω, 0.5 to 1 W, at most 15 x 13 x 4 mm (a "1510" or "1511" size, or 13 mm round), with a **JST-SH 1.0 mm 2-pin** plug.
- The two printed case parts.

## Stack inside the brick

Heights from the bottom of the brick, in mm (from `case/brick_case.scad`):

| From | To | What |
|---|---|---|
| 0.0 | 1.8 | tubes (room for the studs of the brick below) |
| 1.8 | 2.6 | floor (printed base part) |
| 2.6 | 6.6 | speaker at the USB end, battery beside it |
| 7.0 | 9.9 | speaker socket and plug, under the main board above the speaker |
| 9.9 | 10.7 | main board on rails; the ESP32 module hangs below it |
| 10.7 | 16.5 | board-to-board header |
| 16.5 | 17.3 | face board |
| 18.4 | 19.2 | top wall, studs above |

The NFC calculation (`tools/nfc_antenna.py`) assumes 6.6 mm from the loop copper down to the main board's top copper. If the stack changes, change `ground_gap_mm` there too.

## Files

```
tools/design.py        every part, pin and net, with JLCPCB part numbers (the source of truth)
tools/gen_board.py     builds both boards in KiCad: place, route, check
tools/autoplace.py     greedy placer for the small parts
tools/router.py        small maze router (see below)
tools/preroute.py      routes the NFC reader's antenna-side nets first and locks them
tools/stitch_islands.py  a via in each outer ground-pour island that has none
tools/hand_fixes.py    the few hand edits to the routed main board, as code
tools/nfc_antenna.py   loop inductance and PN5180 matching network
tools/gen_sch.py       draws docs/schematic.pdf
tools/gen_fab.py       writes the JLCPCB order files to ../fab/ (refuses a board that fails DRC)
tools/jlc_stock.py     checks every part number against JLCPCB's live stock
tools/kicad.sh         runs any of these in a KiCad 9 container (Docker, no install needed)
tools/kicad-gui.sh     opens a board in KiCad 9's PCB editor from the same container
tools/route_main.sh    routes the main board: preroute, Freerouting 1.9, finish_route.py, stitch_islands.py
tools/render.sh        SVG of a board's layers to ../render/
kicad/                 the generated boards, rules and DRC reports
case/brick_case.scad   printed shell and base
lib/lcsc.pretty/       footprints, from the LCSC/EasyEDA library
```

## Regenerating

Needs KiCad 9 (its Python `pcbnew` module), numpy and scipy, reportlab for the schematic, and Freerouting for the main board. The simplest way is Docker: `tools/kicad.sh` builds a KiCad 9 image with the Python packages (`tools/docker/Dockerfile`) and runs a command in it. For the main board, `tools/route_main.sh` runs Freerouting 1.9 on the host: it needs Java, `xvfb-run` and `freerouting-1.9.0.jar` (default `~/.local/opt/freerouting/freerouting-1.9.0.jar`, or set `FR19_JAR`).

```sh
cd tools
./kicad.sh python3 gen_board.py place     # any command below runs the same way
./route_main.sh                           # main board (see "Routing the main board")
./kicad.sh python3 hand_fixes.py          # the hand edits, after route_main.sh
```

```sh
cd tools
python3 gen_board.py place        # place parts, write ../kicad/*.kicad_pcb (unrouted)
python3 gen_board.py placecheck   # placement DRC: overlaps, clearances
python3 gen_board.py route face   # route the face board with the built-in router
./route_main.sh                   # route the main board (on the host: needs java and xvfb-run)
python3 hand_fixes.py             # the hand edits to the routed main board
python3 gen_board.py check        # full DRC and connectivity
python3 gen_sch.py                # ../docs/schematic.pdf
python3 nfc_antenna.py            # print the antenna and matching design
python3 nfc_antenna.py --check    # check the solver against NXP's worked example
python3 gen_fab.py                # Gerbers, drill, BOM and placement files for JLCPCB
python3 jlc_stock.py              # stock check (plain Python, no KiCad needed)
```

`place` rewrites both boards, so route the face board again after it.

The case, one part at a time:

```sh
openscad -D 'part="shell"' -o shell.stl case/brick_case.scad
openscad -D 'part="base"'  -o base.stl  case/brick_case.scad
```

### Routing the main board

The face board is routed by `tools/router.py`, a small grid maze router (A* on a 0.05 mm grid, with rip-up and retry); it finishes in under a minute. The main board takes more steps. `gen_board.py place` lays some fixed copper first:

- **Module fan-out** (`fanout_module`): each signal pad on the module's two long sides gets a via under the module, between its pads and its centre ground pads, staggered in two columns. The module is 13.2 mm wide on a 13.4 mm board, so those pads can only escape inward, and no autorouter here would place vias under a part by itself. In one straight column, 0.8 mm apart, the vias left 0.35 mm between them, less than any track needs, and walled the NFC reader off from the header on every layer.
- **Reader fan-out** (`fanout_reader`): the PN5180's ground pins get stubs to its exposed pad, its 3V3 and VSYS pins get their own vias, and so does C19's ground pad. Left to the routers, the signal pins either side took that room first.

Then `tools/route_main.sh` does the rest:

1. `preroute.py --analog` routes the reader's antenna-side nets (TX1/TX2, TX1F/TX2F, RXP/RXN and their taps, VMID, VDHF, V1V8, the crystal) with `router.py` on the empty board and locks them.
2. Freerouting **1.9** routes everything else round them (headless, under `xvfb-run`). Freerouting 2.5 oscillated between 55 and 130 open connections on this board; 1.9 converges.
3. `finish_route.py` connects what Freerouting leaves with `router.py`, starting from the copper already there.
4. `stitch_islands.py` puts a via in each piece of the top and bottom ground pours that has none.

Last, `hand_fixes.py` applies three small edits: ground vias for C4/C5, C21 and C1, with one In2 VLED track jogged to make room for C21's, and it removes ground vias the stitching passes stacked on top of each other. Each fix names the copper it changes and refuses to run if that copper is not there, because these edits fit one routing run.

The routing is not reproducible copper for copper: `router.py` and Freerouting do not lay the same tracks twice. Three runs of this recipe (60 and 150 Freerouting passes, and a clean re-run from `place`) each connected every signal net, and each left a different handful of ground joins: pour islands and capacitor ground pads. The committed board is one of those runs, finished by `hand_fixes.py`. After a new run, `gen_board.py check` lists what is left, and `hand_fixes.py` needs new fixes written for it.

`PYTHONHASHSEED` is pinned (0) by `tools/kicad.sh`, because `router.py`'s rip-up order depends on set ordering.

## NFC antenna

`tools/nfc_antenna.py` calculates the loop's inductance from its geometry (about 1.15 µH over the main board), then solves NXP's AN11740 asymmetric matching network for 50 Ω between TX1 and TX2. It checks its own solver against the worked example in that note.

These are first-board values from a calculation. NXP's procedure measures the real coil with a network analyser and then trims the capacitors. The tolerance sweep in the script's output shows how far the real result could land: the drive current stays within the PN5180's limits, and the field stays well above what ISO/IEC 15693 tags need, even in the worst case. Expect to change C1 and C2 on the first boards anyway.

## Routing status

- **Face board (4 layers): routed.** No DRC errors, no missing connections. Its order files are in `fab/brick-face/`.
- **Main board (6 layers): routed.** No DRC errors, no missing connections. Its order files are in `fab/brick-main/`. The DRC warnings left are silkscreen overlaps, footprint-library notices, three tiny dangling track ends, four pads with a single thermal spoke, three silk texts under KiCad's default height, and one fan-out via used on one layer only.

  How it got there: the first draft was about 79% covered and both autorouters left 40 or more connections open. Cutting the microphone and fuel gauge, smaller sockets, 0.2 mm power tracks, 6 layers and a finishing pass brought that down to 13 to 17, almost all of them the NFC reader's own pins. Three changes finished it:

  - The reader's EMC filter coils (L1, L2), VMID capacitor (C19) and receiver taps (R11, R12) are now placed by hand, in the strip between its TX/RX side and the module, each a short stub from its pin. The placer had put them past the module's fan-out vias, so every one of those nets had to cross that wall. Its supply capacitors C12, C13 and C14 are also placed by hand, straight above their pins, and the TX1F/TX2F capacitors sit beside the header pins they feed.
  - The module fan-out vias went under the module and are staggered (see above), and the reader's supply pins got fixed vias.
  - The antenna-side nets are routed first, and the accelerometer (U9) moved to the free top side left of the reader. Under the board, beside the module's pads, it boxed in its own nets.

## Ordering from JLCPCB

`tools/gen_fab.py` writes everything to `fab/<board>/`. It refuses a board that fails DRC or has open connections. Order the two boards as two separate designs, each with assembly:

1. **PCB.** Upload `brick-main-gerbers.zip` (then `brick-face-gerbers.zip` as a second design). Settings: layers as detected (main 6, face 4), **thickness 0.8 mm**, any colour, surface finish ENIG or HASL lead-free. On the 6-layer main board, epoxy-filled and capped vias are JLCPCB's default and free, which suits the vias in the module's and chips' ground pads.
2. **Panelise.** Both boards are smaller than the 70 x 70 mm that JLCPCB's Standard assembly needs, so choose "Panel by JLCPCB" with edge rails. A 2 x 3 or similar panel of the main board, and a 2 x 4 of the face board, gives a handful of each.
3. **Assembly.** Standard PCBA, **both sides**. Upload `-bom.csv` and `-cpl.csv`. On the part-check page every line should match; JP1 (the boot jumper) and ANT1 (the printed loop) are not in the parts list on purpose.
4. **Check the placement preview** part by part, especially U1, U6, U7, U9, U10, the LEDs and J2/J3, and the pin-1 dot of every IC. Bottom-side rotations are the usual source of mistakes. Fix any turned part by adding its footprint to `ROT_FIX` in `gen_fab.py` and regenerating.
5. Run `python3 tools/jlc_stock.py` on the day of the order. When this was written, every part was in stock, but the TCS34725 colour sensor had only 37 left.

Expect 25 or so "extended" parts on each order, each with a small loading fee.

## Assembly

No soldering.

1. Plug the face board's socket onto the main board's header, face board on top, matching the outlines.
2. Plug the speaker into J3 on the underside and the battery into J2 on the top. Before the battery goes in, check its polarity: red to the pin marked `+`.
3. Lay the speaker (facing up) and the battery in their bays on the printed base, battery wires up through the notch in the main board's edge.
4. Push the board stack up into the shell from below, USB-C into its opening, until the main board clicks over its rails. Snap the base in.

The first time, flash the firmware over USB-C from the [build page](https://emu-commits.github.io/open-play-brick/build.html). If the ESP32 does not enter download mode by itself, hold tweezers across JP1 while plugging in the USB cable.

## Not done yet

- **The firmware does not read the battery yet.** It needs to read GPIO4 as an ADC (VBAT = 2 x the reading) instead of the fuel gauge.
- **Nothing has been built.** The NFC antenna in particular is a calculation: expect to change the matching capacitors C40 to C47 on the first boards (`tools/nfc_antenna.py`). The roadmap's bench test of a small antenna (step 2) is still the cheaper first step.
- **Review.** The NFC section (crystal, matching network, loop) and the module's antenna keep-out need review by someone with RF layout experience. The 2.4 GHz antenna sits close to the face board and the battery, so expect less Wi-Fi and Bluetooth range than a bare module.
- **Small battery.** The 2 x 6 bay takes a cell of about 60 to 80 mAh.
- **Fit check of the case** with real boards, battery and speaker.
