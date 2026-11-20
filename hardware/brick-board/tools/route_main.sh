#!/bin/sh
# Route the main board with Freerouting 1.9: export the DSN in the KiCad
# container, run Freerouting on the host (it needs a display, so xvfb-run),
# import the session and fill the pours. Run `gen_board.py place` first.
#
#   FR19_JAR   Freerouting 1.9 jar (default ~/.local/opt/freerouting/freerouting-1.9.0.jar)
#   PASSES     maximum passes (default 60)
#   CONTINUE=1 route on from the tracks already on the board
#   FINISH=0   skip the finishing pass with router.py (finish_route.py)
#
# Freerouting 2.x (gen_board.py freeroute) oscillated between 55 and 130 open
# connections on this board; 1.9 converges.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
JAR=${FR19_JAR:-$HOME/.local/opt/freerouting/freerouting-1.9.0.jar}
W="$HERE/../kicad/.freerouting"
cd "$HERE"
./kicad.sh python3 gen_board.py dsn main 2>&1 | grep -v Debug
rm -f "$W/brick-main.ses"
( cd "$W" && xvfb-run -a java -jar "$JAR" -de brick-main.dsn -do brick-main.ses -mp "${PASSES:-60}" ) >"$W/fr19.log" 2>&1 || true
[ -s "$W/brick-main.ses" ] || { echo "Freerouting wrote no session; see $W/fr19.log"; exit 1; }
./kicad.sh python3 gen_board.py sesimport brick-main 2>&1 | grep -v Debug
[ "${FINISH:-1}" = 1 ] && ./kicad.sh python3 -u finish_route.py 2>&1 | grep -v "Debug\|leak\|could not reach" | tail -3
