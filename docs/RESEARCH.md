# What is known about the original, and where it comes from

This is a summary of public reverse-engineering work and press teardowns, checked on 2026-10-12. None of it is from the LEGO Group. Where sources disagree or a fact is thin, it says so.

## The original brick

| Fact | Detail | Source |
| --- | --- | --- |
| Size | 2 x 4 studs, **five plates tall**. No source gives millimetres. From standard brick geometry (8 mm stud pitch less 0.2 mm clearance, 3.2 mm per plate) that is 31.8 x 15.8 x 16.0 mm plus 1.7 mm studs. That figure is derived, not measured. | [StoneWars X-ray][stonewars] |
| Processor | EM Microelectronic EM9305, a Bluetooth 5.4 SoC with a 32-bit ARC core. It runs the play engine. | [node-smartplay][nsp-hw], [Hackaday][hackaday] |
| Custom chip | A 4.1 mm mixed-signal ASIC (marked DA000001-01 in one teardown, -04 in another). It drives the coils, reads and decrypts tags, drives the LEDs, reads the sensors and makes the audio. | [node-smartplay][nsp-hw], [Hackaday][hackaday] |
| Memory | 16 Mbit SPI flash | [Hackaday][hackaday] |
| Battery | 45 mAh, 3.7 V lithium pouch cell in the lower half of the brick, charged inductively | [StoneWars][stonewars] |
| Coils | A wound copper coil on each side wall. The same coils read tags, charge the battery and sense other bricks nearby. | [StoneWars][stonewars], [node-smartplay][nsp-hw] |
| Light | "A number of" RGB LEDs on the main board. The firmware's LED patterns are 8-bit masks (`0x0F` "bottom 4", `0xF0` "top 4"), which suggests eight positions. | [Hackaday][hackaday], [node-smartplay][nsp-hw] |
| Sound | A speaker under the transparent top. All audio is synthesised from instruction sequences, not played from recordings. | [StoneWars][stonewars], [node-smartplay][nsp-hw] |
| Sensors | Accelerometer, colour/light sensor with its own LEDs, microphone (present, said to be disabled at launch). There are no buttons. | [node-smartplay][nsp-hw], [StoneWars][stonewars] |
| Brick to brick | Bluetooth 5.4 Periodic Advertising with Responses ("BrickNet"), plus coil-based position sensing | [node-smartplay][nsp-hw] |

## The tags

This part matters most for a compatible brick, and it is the best documented.

- Tags are passive **ISO/IEC 15693** (NFC-V, 13.56 MHz) chips made by EM Microelectronic (manufacturer code `0x16`, IC reference `0x17`). UIDs start `E0:16:5C:01`.
- Memory is 66 blocks of 4 bytes. It can be read with the standard commands (Inventory `0x01`, Read Single Block `0x20`, Read Multiple Blocks `0x23`, Get System Information `0x2B`) with **no password or authentication**. Any NFC phone can dump one.
- Every tag starts with a 5-byte cleartext header `00 LL 01 0C 01`. `LL` is the **payload length in bytes**. Early projects called this the "Brick ID" or "Content ID". It is really a length, so two different tags could share it.
- Everything after the header is encrypted and authenticated inside the ASIC. The algorithm and key are unknown. Changing one bit makes the original brick reject the tag.
- All tags of the same type hold **byte-for-byte identical memory**, whatever their UID. Clones on blank NXP ICODE SLIX2 tags are accepted by the original brick.
- There are two kinds: identity tags (figures) and item tags (tiles).

Sources: [node-smartplay hardware notes][nsp-hw], [Ellerbach/LegoSmartPlay][ellerbach], [Coffee & Fun first reads][coffee].

### What that makes possible

Because same-type tags are identical, a **CRC-32 of the raw payload is a stable fingerprint** of what the tag is, and it can be computed without decrypting anything. This project identifies a tag by payload length plus that CRC. It needs no key, and it sidesteps the "two tags, same length" weakness of length-only matching.

Known tags (lengths from the sources above; CRC-32 computed here over the first `LL` bytes of the dumps published in node-smartplay):

| Length | CRC-32 | Tag | Kind |
| --- | --- | --- | --- |
| `0x3B` | not published | TIE Fighter | item |
| `0x4A` | `0x3652D8C1` | R2-D2 | identity |
| `0x69` | not published | X-Wing body | item |
| `0x6B` | `0x90A404C8` | X-Wing | item |
| `0x7E` | `0xAB230D12` | Lightsaber | item |
| `0x9D` | `0xE8E68E59` | Luke Skywalker | identity |
| `0x9E` | `0xBCA6DEC1` | Princess Leia | identity |
| `0xA9` | `0x85F392DC` | Darth Vader | identity |
| `0xAB` | `0x705C2646` | Emperor Palpatine | identity |

No Pokémon tag dump was public when this was written, so those catalogue entries are placeholders until someone scans them.

## How the original plays

From [node-smartplay][nsp-hw]:

- The tag is a playlist. After decryption it selects a script, an audio bank and an LED animation bank that already live in the brick's flash.
- Motion triggers come from accelerometer thresholds (shake, swoosh, rotation).
- The colour sensor triggers flavour events. In the Star Wars content, red fires, green sounds like repairs, blue sounds like refuelling.
- Combat between bricks is one counter: four hits put a brick in a damaged state (alarm), two more destroy it (explosion), then it resets.
- Tag polling is scheduled about every 600 ms and yields to audio.

This project copies those behaviours in outline (the event list, the 4 + 2 hit rule, red/green/blue meanings) with its own sounds and light patterns.

## Sets

LEGO sells "compatible" sets that include tags but no brick. Reported Pokémon ones for August 2026 include 72158, 72159, 72161, 72163, 72165 and 72166 ([LEGO newsroom][lego-pokemon], [Rambling Brick][rambling]). The Star Wars all-in-one sets (75421, 75423, 75427) include a brick. Check LEGO's own listing before buying: the fan lists differ on details.

## Earlier open hardware

[Ellerbach/LegoSmartPlay][ellerbach] reads these tags with an ESP32-C3 Super Mini, a PN5180 module, a TCS3472x colour sensor and a YX5300 MP3 module, in .NET nanoFramework. This project uses the same reader and colour sensor, moves to an ESP32-C6, and replaces the MP3 module with a synthesiser and an I2S amplifier.

## What is not known

- Whether the tags answer Read Multiple Blocks reliably on every reader. Phone apps and the PN5180 do it; the firmware falls back to single-block reads anyway.
- The read range of these small tags with a small loop antenna through a plastic wall.
- The official brick's exact outer dimensions and wall thickness.
- Any Pokémon tag's length or CRC.

[stonewars]: https://stonewars.com/in-depth-features/lego-smart-brick-x-rayed/
[hackaday]: https://hackaday.com/2026/03/18/teardown-of-a-2026-lego-smart-brick/
[nsp-hw]: https://github.com/nathankellenicki/node-smartplay/blob/main/research/notes/HARDWARE.md
[ellerbach]: https://github.com/Ellerbach/LegoSmartPlay
[coffee]: https://www.coffeeandfun.com/blog/reverse-engineering-lego-smart-play-nfc-part-1/
[lego-pokemon]: https://www.lego.com/en-us/aboutus/news/2026/june/lego-pokemon-smart-play-sets
[rambling]: https://ramblingbrick.com/2026/06/03/10-new-smart-play-pokemon-sets-revealed/
