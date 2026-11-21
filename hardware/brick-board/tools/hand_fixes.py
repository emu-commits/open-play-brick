#!/usr/bin/env python3
"""Small hand edits to the routed main board, kept as code so they are
recorded and can be re-applied.

    tools/kicad.sh python3 hand_fixes.py [board.kicad_pcb]

Each fix names the copper it removes (net, layer, end points) and refuses to
run if that copper is not there, so a fix written for one routing run cannot
land on a different one. Run gen_board.py check afterwards.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pcbnew  # noqa: E402

import gen_board as g  # noqa: E402

mm, OX, OY = pcbnew.FromMM, g.OX, g.OY
TOL = 0.02


def near(v, x, y):
    return abs(pcbnew.ToMM(v.x) - OX - x) < TOL and abs(pcbnew.ToMM(v.y) - OY - y) < TOL


class Board:
    def __init__(self, path):
        self.path = path
        self.b = pcbnew.LoadBoard(path)
        self.removed = []

    def layer(self, name):
        return self.b.GetLayerID(name)

    def remove_track(self, net, layer, a, c):
        for t in self.b.GetTracks():
            if t.GetClass() == "PCB_VIA" or t.GetNetname() != net or t.GetLayer() != self.layer(layer):
                continue
            s, e = t.GetStart(), t.GetEnd()
            if (near(s, *a) and near(e, *c)) or (near(s, *c) and near(e, *a)):
                self.b.Remove(t)
                self.removed.append(t)
                return
        raise SystemExit("not found: %s track on %s %s-%s" % (net, layer, a, c))

    def track(self, net, layer, pts, width):
        for a, c in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(self.b)
            t.SetStart(g.P(*a))
            t.SetEnd(g.P(*c))
            t.SetWidth(mm(width))
            t.SetLayer(self.layer(layer))
            t.SetNet(self.b.FindNet(net))
            self.b.Add(t)

    def via(self, net, x, y, d=0.45, drill=0.25):
        g.add_via(self.b, {}, None, x, y, d, drill, locked=False, net_obj=self.b.FindNet(net))

    def save(self):
        g.fill_zones(self.b)
        g.save_board(self.path, self.b)


def fixes(bd):
    # C4/C5 ground (beside the charger): their top-side ground track had no via
    bd.via("GND", 9.25, 10.504)
    # C21 ground (TX1F filter): boxed in between I2C_SDA and VLED on In2.
    # VLED jogs 0.4 mm down past it, and the pad gets a via.
    bd.remove_track("VLED", "In2.Cu", (34.35, 3.15), (31.5, 3.15))
    bd.track("VLED", "In2.Cu", [(31.5, 3.15), (32.2, 3.15), (32.6, 3.55), (33.2, 3.55), (33.6, 3.15), (34.35, 3.15)], 0.3)
    bd.via("GND", 32.84, 2.85)
    # C1 ground (module supply, 22 uF): its pad sat alone in a fragment of the
    # top pour; a via at the pad's edge
    bd.via("GND", 37.87, 10.80)


def dedupe_ground_vias(bd, min_gap=0.25):
    """Drop one of each pair of ground vias whose holes overlap or sit closer
    than min_gap (JLCPCB's hole-to-hole minimum): the routers' stitching
    passes put some on top of each other. Of each pair, the one fewer tracks
    end on goes; a locked via never does."""
    b = bd.b
    vias = [t for t in b.GetTracks() if t.GetClass() == "PCB_VIA" and t.GetNetname() == "GND"]
    ends = {}
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA" or t.GetNetname() != "GND":
            continue
        for e in (t.GetStart(), t.GetEnd()):
            for v in vias:
                r = v.GetWidth(pcbnew.F_Cu) / 2
                if (e.x - v.GetPosition().x) ** 2 + (e.y - v.GetPosition().y) ** 2 <= r * r:
                    ends[v.m_Uuid.AsString()] = ends.get(v.m_Uuid.AsString(), 0) + 1
    info = [(v.m_Uuid.AsString(), pcbnew.ToMM(v.GetPosition().x), pcbnew.ToMM(v.GetPosition().y),
             pcbnew.ToMM(v.GetDrill()), v.IsLocked()) for v in vias]
    gone = set()
    for i, (ka, xa, ya, da, la) in enumerate(info):
        for kc, xc, yc, dc, lc in info[i + 1:]:
            if ka in gone or kc in gone:
                continue
            if ((xa - xc) ** 2 + (ya - yc) ** 2) ** 0.5 - (da + dc) / 2 >= min_gap:
                continue
            cand = [k for k, locked in ((ka, la), (kc, lc)) if not locked]
            if cand:
                gone.add(min(cand, key=lambda k: ends.get(k, 0)))
    # remove only after the scan: a removed item must not be touched again
    for v in vias:
        if v.m_Uuid.AsString() in gone:
            b.Remove(v)
            bd.removed.append(v)     # keep the Python wrapper alive: freeing it crashed KiCad 9's bindings
    print("removed %d doubled-up ground vias" % len(gone))


if __name__ == "__main__":
    bd = Board(sys.argv[1] if len(sys.argv) > 1 else os.path.join(g.OUT, "brick-main.kicad_pcb"))
    fixes(bd)
    dedupe_ground_vias(bd)
    bd.save()
    print("hand fixes applied")
