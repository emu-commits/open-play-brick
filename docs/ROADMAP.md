# Next steps, and how achievable a brick-sized version is

Written 2026-10-12. Nothing here has been tested on hardware. This is a plan and an honest estimate, not a result.

The goal is a brick that fits the same space as the original: 2 x 4 studs, five plates tall. The [module build](../site/BUILD.md) is the first step towards it, not the end.

## The sequence

1. **Breadboard build.** Ready-made boards on a breadboard, as in the [build guide](../site/BUILD.md). This proves the firmware on real chips and that the reader reads real tags. It is cheap and nothing is permanent.
2. **Small-antenna test.** The breadboard reader has an antenna about 40 x 60 mm. A brick allows roughly 28 x 12 mm. Passing step 1 says nothing about whether the small one works, so test a brick-sized antenna on the bench before paying for a full board.
3. **Custom board.** The design files go to a board house that fabricates the board and solders the chips on. It arrives assembled. Someone designs it once; after that anyone can order copies from the published files.
4. **Shell.** A 3D-printed, brick-shaped case, with the battery and speaker attached by hand (a few solder joints or plugs).

Decide on step 3 only after step 2. If the small antenna cannot read a tag through plastic, the size target needs rethinking before any money goes into a board.

## Is the custom board orderable?

Mostly yes, but it has not been checked part by part.

- **Chips.** Every chip in the design is a standard catalogue part in a package that assembly houses handle routinely. Stock at any specific assembler has not been checked. The PN5180 and the colour sensor are the two to check first.
- **Quantity and cost.** Assemblers have small minimum orders, typically a handful of boards, so ordering exactly one is not really an option. There is no verified price yet. Treat any figure as a guess until a board house has quoted it.
- **Who designs it.** This is not a consumer task. The board has two radio sections (2.4 GHz and 13.56 MHz) that cannot be verified without hardware. It needs review by someone with board-design experience. Expect two or three revisions.

## Will it fit in a 2 x 4 brick?

The volume arithmetic says yes. The layout is where it could fail.

- **Height.** A stack estimate (speaker, board with parts on both sides, battery, tolerances) comes to about 11.4 mm of the roughly 12 mm available inside. That leaves almost no margin.
- **Board area.** About 360 mm² of board for about 110 mm² of chips, before the dozens of small support parts, two crystals and the USB-C socket.
- **Antenna clearance.** The 2.4 GHz antenna needs a clear area with no copper or battery near it. The ready-made ESP32-C6 module with a built-in antenna is 13.2 x 16.6 mm, too wide for the cavity, so the board would need the bare chip and a separate chip antenna. The estimates above do not include this.
- **Why the original fits.** It uses one custom chip to do what takes this design about eight.

These figures are arithmetic. Nothing has been drawn in CAD or laid out.

## What a brick-sized version gives up

Compared with the breadboard build:

- a battery of around 100 mAh instead of 500
- a much smaller, quieter speaker
- shorter read range

## If it does not fit

The fallback is a slightly larger brick: 2 x 6, 4 x 4, or one plate taller. That loses exact form-factor parity and keeps everything else.

## What would move this forward

- Someone building the module build and reporting what happens, especially read range.
- A bench test of a small loop antenna with a PN5180 and a real tag.
- A reviewer with RF board-layout experience.
- Scans of tags not yet in the catalogue.
EOF
