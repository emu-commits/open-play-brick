#!/bin/sh
# render.sh board-name [layers] [out-suffix]: SVG of a board to ../render/
B=${1:-brick-main}; L=${2:-F.Cu,F.Fab,Edge.Cuts}; O=${3:-top}; M=${4:-}
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$HERE/../render"
"$HERE/kicad.sh" kicad-cli pcb export svg --mode-single $M -l "$L" --fit-page-to-board --exclude-drawing-sheet \
  -o "$HERE/../render/$B-$O.svg" "$HERE/../kicad/$B.kicad_pcb" >/dev/null
