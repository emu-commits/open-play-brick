#!/usr/bin/env python3
"""Connect what Freerouting left open on the main board, with router.py.

    tools/kicad.sh python3 finish_route.py      # works on ../kicad/brick-main.kicad_pcb

router.py routes each net from the copper it already has, so Freerouting's
tracks stay as they are; its rip-up only removes tracks it laid itself.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np  # noqa: E402
import pcbnew  # noqa: E402

import gen_board as g  # noqa: E402

g.np = np
args = [a for a in sys.argv[1:] if not a.startswith("--")]
path = args[0] if args else os.path.join(g.OUT, "brick-main.kicad_pcb")
# --adopt lets rip-up remove Freerouting's tracks too; it can lose more than it gains
adopt = "--adopt" in sys.argv
b = pcbnew.LoadBoard(path)
inner = [pcbnew.In2_Cu, pcbnew.In3_Cu] if b.GetCopperLayerCount() == 6 else [pcbnew.In2_Cu]
failed = g.route_board(b, (g.MAIN_W, g.MAIN_H), [pcbnew.F_Cu] + inner + [pcbnew.B_Cu], g.copper_layers(b), "GND",
                       "brick-main", via=(0.45, 0.25), clearance=0.13, adopt=adopt, rounds=40 if adopt else 12)
g.fill_zones(b)
g.save_board(path, b)
print("brick-main: %s" % ("all nets connected" if not failed else "still open: %s" % failed))
