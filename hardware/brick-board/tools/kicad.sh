#!/bin/sh
# Run a command in the KiCad 9 container with the repo mounted.
#   tools/kicad.sh python3 gen_board.py check
# Freerouting: set FREEROUTING_HOME to an unpacked freerouting-*-linux-x64
# release (it bundles its own Java 25); it is mounted at /opt/freerouting.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
FR=${FREEROUTING_HOME:-$HOME/.local/opt/freerouting/linux/freerouting-2.5.0-linux-x64}
IMG=opb-kicad:9
docker image inspect $IMG >/dev/null 2>&1 || docker build -q -t $IMG "$HERE/docker"
exec docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$REPO:$REPO" -v "$FR:/opt/freerouting:ro" ${KICAD_EXTRA_MOUNT:+-v "$KICAD_EXTRA_MOUNT:$KICAD_EXTRA_MOUNT"} \
  -e FREEROUTING=/opt/freerouting/bin/freerouting ${MAIN_LAYERS:+-e MAIN_LAYERS=$MAIN_LAYERS} ${CONTINUE:+-e CONTINUE=$CONTINUE} -e PYTHONHASHSEED=${PYTHONHASHSEED:-0} -w "$(pwd)" $IMG "$@"
