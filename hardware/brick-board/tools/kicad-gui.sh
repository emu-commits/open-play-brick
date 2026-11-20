#!/bin/sh
# Open a board in KiCad 9's PCB editor, from the same container as the tools,
# on this machine's display (X11).
#   tools/kicad-gui.sh                      # the main board
#   tools/kicad-gui.sh ../kicad/brick-face.kicad_pcb
# The editor's interactive router (X, then drag; "Route > Interactive Router
# Settings > Shove") is the quickest way to finish the last connections.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
BOARD=$(realpath "${1:-$HERE/../kicad/brick-main.kicad_pcb}")
IMG=opb-kicad:9
docker image inspect $IMG >/dev/null 2>&1 || docker build -q -t $IMG "$HERE/docker"
command -v xhost >/dev/null && xhost +si:localuser:"$(id -un)" >/dev/null 2>&1 || true
exec docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -e DISPLAY="${DISPLAY:-:0}" \
  -v /tmp/.X11-unix:/tmp/.X11-unix -v "$REPO:$REPO" -w "$(dirname "$BOARD")" $IMG pcbnew "$BOARD"
