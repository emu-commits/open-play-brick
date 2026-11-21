#!/usr/bin/env python3
"""Route the NFC reader's own nets on the placed, unrouted main board with
router.py, and lock them, before Freerouting routes the rest.

    tools/kicad.sh python3 preroute.py      # works on ../kicad/brick-main.kicad_pcb

Left to Freerouting, the supply tracks it laid first looped round the
PN5180's 0.5 mm-pitch pads, and its receiver, VMID, filter and SPI pins
stayed boxed in (13 to 17 open after every run). Routed first, while the
board is empty, they take the short paths; Freerouting sees them as fixed
copper (locked tracks go out as `(type fix)` in the DSN).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np  # noqa: E402
import pcbnew  # noqa: E402

import gen_board as g  # noqa: E402

g.np = np
args = [a for a in sys.argv[1:] if not a.startswith("-")]
path = args[0] if args else os.path.join(g.OUT, "brick-main.kicad_pcb")
SKIP = {"GND", "VSYS", "3V3"}
b = pcbnew.LoadBoard(path)
nets = set()
for ref in ("U6", "L1", "L2", "R11", "R12", "C24", "C25", "C19", "C14", "Y1"):
    for p in b.FindFootprintByReference(ref).Pads():
        n = p.GetNetname()
        if n and n not in SKIP and not n.startswith("NC_"):
            nets.add(n)
# --analog: only the antenna-side nets, leaving the SPI and control lines
# (which run off to the module's far side) to Freerouting
if "--analog" in sys.argv:
    nets = {n for n in nets if n in ("TX1", "TX2", "TX1F", "TX2F", "RXP", "RXN", "RXP_C", "RXN_C",
                                     "VMID", "VDHF", "V1V8", "XTAL1", "XTAL2")}
nets |= set(args[1:])
print("prerouting: %s" % ", ".join(sorted(nets)))
before = set(t.m_Uuid.AsString() for t in b.GetTracks())
inner = [pcbnew.In2_Cu, pcbnew.In3_Cu] if b.GetCopperLayerCount() == 6 else [pcbnew.In2_Cu]
failed = g.route_board(b, (g.MAIN_W, g.MAIN_H), [pcbnew.F_Cu] + inner + [pcbnew.B_Cu], g.copper_layers(b), "GND",
                       "brick-main", via=(0.45, 0.25), clearance=0.13, rounds=20, only=nets, stitch=False)
n = 0
for t in b.GetTracks():
    if t.m_Uuid.AsString() not in before:
        t.SetLocked(True)
        n += 1
g.save_board(path, b)
print("prerouted and locked %d tracks and vias; %s" % (n, "all connected" if not failed else "open: %s" % failed))
