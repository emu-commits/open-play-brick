# Brick board (rev C)

A custom circuit board pair and a printed case for Open Play Brick. This is step 3 of the [roadmap](../../docs/ROADMAP.md): a board a board house can make and assemble from these files.

**Status: a first draft. Nothing here has been built, ordered, or reviewed by anyone with RF board-layout experience.** The roadmap's advice still holds: test a small NFC antenna on the bench (step 2) before paying for these boards.

## Size: 2 x 6, not 2 x 4

Rev C is the roadmap's fallback size: a **2 x 6 brick, six plates (19.2 mm) tall**. It uses the ready-made ESP32-C6-MINI-1 module with its built-in antenna, so there is no bare-chip 2.4 GHz design to verify. The module is 13.2 x 16.6 mm. It fits across the cavity (13.8 mm inside), but with the clear area its antenna needs beyond its end, it takes most of a 2 x 4 brick's length. The extra two studs give room for the rest of the circuit, the battery and the speaker.

A 2 x 4 version would need the bare chip and a chip antenna. That is a separate design.

## What is in it

Two 4-layer boards, stacked and joined by a 1.27 mm 2 x 5 board-to-board header.

| Board | Size | Contents |
|---|---|---|
| main | 45.4 x 13.4 mm | ESP32-C6-MINI-1 (underside), USB-C with ESD protection, LiPo charger (TP4054, 50 mA), battery/USB power path, 3.3 V regulator (RT9080, 2 µA quiescent), fuel gauge (MAX17048), NFC reader (PN5180) with its 27.12 MHz crystal, amplifier (MAX98357A), I2S microphone (ICS-43434), accelerometer (LIS2DH12), battery and speaker connectors |
| face | 24.4 x 13.4 mm | Printed 6-turn NFC loop with its EMC filter and matching network, eight WS2812B-2020 pixels, colour sensor (TCS34725) and its white lamp |

The face board sits on top so the NFC loop is as close as possible to the tag on top of the brick. Its pixels and colour sensor sit inside the loop. For that reason the face board has **no copper pours**: a solid area of copper inside the loop would act as a shorted turn and weaken the field. Its inner layers carry only a few tracks.

The GPIO numbers match the rev B module build, so the same firmware image runs on both. `gen_board.py` fails if they drift from `firmware/core/pins.h`.

## Stack inside the brick

Heights from the bottom of the brick, in mm (from `case/brick_case.scad`):

| From | To | What |
|---|---|---|
| 0.0 | 1.8 | tubes (room for the studs of the brick below) |
| 1.8 | 2.6 | floor (printed base part) |
| 2.6 | 6.6 | speaker at the USB end, battery beside it |
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
tools/nfc_antenna.py   loop inductance and PN5180 matching network
tools/gen_sch.py       draws docs/schematic.pdf
kicad/                 the generated boards, rules and DRC reports
case/brick_case.scad   printed shell and base
lib/lcsc.pretty/       footprints, from the LCSC/EasyEDA library
```

## Regenerating

Needs KiCad 9 (its Python `pcbnew` module), numpy and scipy, and reportlab for the schematic.

```sh
cd tools
python3 gen_board.py place        # place parts, write ../kicad/*.kicad_pcb (unrouted)
python3 gen_board.py placecheck   # placement DRC: overlaps, clearances
python3 gen_board.py route face   # route the face board with the built-in router
python3 gen_board.py freeroute    # route the main board with Freerouting (needs Java 25+)
python3 gen_board.py check        # full DRC and connectivity
python3 gen_sch.py                # ../docs/schematic.pdf
python3 nfc_antenna.py            # print the antenna and matching design
python3 nfc_antenna.py --check    # check the solver against NXP's worked example
```

`place` rewrites both boards, so route the face board again after it.

The case, one part at a time:

```sh
openscad -D 'part="shell"' -o shell.stl case/brick_case.scad
openscad -D 'part="base"'  -o base.stl  case/brick_case.scad
```

### Why a home-made router

The boards are generated from code, and Freerouting 2.2 needs Java 25, which the environment these files were first made in did not have. A grid maze router (A* on a 0.05 mm grid, with rip-up and retry) handles the face board in seconds. KiCad's own DRC checks the result either way.

## NFC antenna

`tools/nfc_antenna.py` calculates the loop's inductance from its geometry (about 1.15 µH over the main board), then solves NXP's AN11740 asymmetric matching network for 50 Ω between TX1 and TX2. It checks its own solver against the worked example in that note.

These are first-board values from a calculation. NXP's procedure measures the real coil with a network analyser and then trims the capacitors. The tolerance sweep in the script's output shows how far the real result could land: the drive current stays within the PN5180's limits, and the field stays well above what ISO/IEC 15693 tags need, even in the worst case. Expect to change C1 and C2 on the first boards anyway.

## Routing status

- **Face board: routed.** KiCad's DRC reports no errors and no missing connections (`python3 gen_board.py route face`, then `check`).
- **Main board: placed, not routed.** Placement passes DRC. Routing does not finish:

  | Attempt | Connections left open |
  |---|---|
  | built-in router (`route main`) | 18 nets |
  | Freerouting, 40 passes (`freeroute main`) | 41 connections, about 31 of them signals |
  | Freerouting with 0.1 mm tracks and gaps, 0.45 mm vias | about 45 |

  Two different routers failing in the same way, and finer rules barely helping, point to the placement. The placer puts each support part as close to its chip as it fits, which suits decoupling but leaves no channels between groups of parts on a 45 x 13 mm board. The next step is to re-place the main board with routing channels in mind (by hand, or by giving the placer channel keep-outs), or to move to a 6-layer board.

  One placement problem is already fixed: support parts packed against the PN5180's 0.5 mm-pitch pads had walled several of its pins into pockets that no route could leave. The placer now keeps a 0.6 mm ring clear round that chip.

## Not done yet

- **Fabrication outputs.** `design.py` mentions `gen_fab.py`, which should write the Gerbers, drill files, parts list and placement file in JLCPCB's format. It does not exist yet.
- **Stock check.** The JLCPCB part numbers have not been checked for stock. The PN5180 and the colour sensor are the ones to check first.
- **Review.** The NFC section (crystal, matching network, loop) and the module's antenna keep-out need review by someone with RF layout experience.
- **Bench test of the antenna** (roadmap step 2), before ordering.
- **Fit check of the case** with real boards, battery and speaker.
