#!/bin/sh
# Route the main board. Run `gen_board.py place` first. Steps:
#   1. preroute.py --analog: the PN5180's antenna-side nets (TX, RX, VMID,
#      VDHF, V1V8, crystal), routed first with router.py and locked
#   2. Freerouting 1.9 on the rest: export the DSN in the KiCad container,
#      run Freerouting on the host (it needs a display, so xvfb-run), import
#   3. finish_route.py: router.py connects what Freerouting left
#   4. stitch_islands.py: a via in each outer ground-pour island
# then, by hand, hand_fixes.py (edits written for one routing run).
#
#   FR19_JAR   Freerouting 1.9 jar (default ~/.local/opt/freerouting/freerouting-1.9.0.jar)
#   PASSES     maximum passes (default 60)
#   CONTINUE=1 route on from the tracks already on the board (skips step 1)
#   FINISH=0   skip steps 3 and 4
#
# Freerouting 2.x (gen_board.py freeroute) oscillated between 55 and 130 open
# connections on this board; 1.9 converges.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
JAR=${FR19_JAR:-$HOME/.local/opt/freerouting/freerouting-1.9.0.jar}
W="$HERE/../kicad/.freerouting"
cd "$HERE"
[ "${CONTINUE:-0}" = 1 ] || ./kicad.sh python3 -u preroute.py --analog 2>&1 | grep -v "Debug\|leak\|could not reach" | tail -1
CONTINUE=1 ./kicad.sh python3 gen_board.py dsn main 2>&1 | grep -v Debug
rm -f "$W/brick-main.ses"
( cd "$W" && xvfb-run -a java -jar "$JAR" -de brick-main.dsn -do brick-main.ses -mp "${PASSES:-60}" ) >"$W/fr19.log" 2>&1 || true
[ -s "$W/brick-main.ses" ] || { echo "Freerouting wrote no session; see $W/fr19.log"; exit 1; }
./kicad.sh python3 gen_board.py sesimport brick-main 2>&1 | grep -v Debug
if [ "${FINISH:-1}" = 1 ]; then
  ./kicad.sh python3 -u finish_route.py 2>&1 | grep -v "Debug\|leak\|could not reach" | tail -3
  ./kicad.sh python3 stitch_islands.py 2>&1 | grep -v "Debug\|leak" | tail -1
fi
