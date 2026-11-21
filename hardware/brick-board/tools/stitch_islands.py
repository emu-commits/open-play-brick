#!/usr/bin/env python3
"""Give every island of the outer ground pours a via to the inner planes.

    tools/kicad.sh python3 stitch_islands.py [board.kicad_pcb]   # default ../kicad/brick-main.kicad_pcb

The top and bottom GND floods fill round the tracks, and on this board some
of their pieces end up with nothing joining them to the rest of the ground
net: DRC reports them as unconnected items (zone to zone, or a capacitor's
ground pad to the module's). This fills the zones, finds each piece of the
F.Cu and B.Cu GND pours with no GND via inside it, and puts a via where one
fits: inside the piece (so clear of other copper on that layer) and clear of
every other net's copper on the other layers. It runs after routing.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pcbnew  # noqa: E402

import gen_board as g  # noqa: E402

VIA, DRILL, CLEAR, HOLE_CLEAR = 0.45, 0.25, 0.15, 0.25
mm, OX, OY = pcbnew.FromMM, g.OX, g.OY


def main(path):
    b = pcbnew.LoadBoard(path)
    g.fill_zones(b)
    gnd = b.FindNet("GND")
    copper = list(g.copper_layers(b))
    others = [t for t in b.GetTracks() if t.GetNetname() != "GND"]
    pads = [p for f in b.GetFootprints() for p in f.Pads() if p.GetNetname() != "GND"]
    holes = [p for f in b.GetFootprints() for p in f.Pads() if p.HasHole()] + \
            [t for t in b.GetTracks() if t.GetClass() == "PCB_VIA"]
    gvias = [t for t in b.GetTracks() if t.GetClass() == "PCB_VIA" and t.GetNetname() == "GND"]
    keep = [z for z in b.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowVias()]

    def fits(x, y):
        v = pcbnew.PCB_VIA(b)
        v.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
        v.SetWidth(mm(VIA))
        v.SetDrill(mm(DRILL))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        pos = v.GetPosition()
        for z in keep:
            if z.Outline().Contains(pos):
                return None
        for layer in copper:
            vs = v.GetEffectiveShape(layer)
            for it in others + pads:
                if it.IsOnLayer(layer) and it.GetEffectiveShape(layer).Collide(vs, mm(CLEAR)):
                    return None
        hs = v.GetEffectiveHoleShape()
        for it in holes:
            hole = it.GetEffectiveHoleShape()
            if hole is not None and hole.Collide(hs, mm(HOLE_CLEAR)):
                return None
        return v

    added = 0
    for z in b.Zones():
        if z.GetIsRuleArea() or z.GetNetname() != "GND":
            continue
        for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
            if not z.IsOnLayer(layer):
                continue
            polys = z.GetFilledPolysList(layer)
            for i in range(polys.OutlineCount()):
                piece = pcbnew.SHAPE_POLY_SET()
                piece.AddOutline(polys.Outline(i))
                for h in range(polys.HoleCount(i)):
                    piece.AddHole(polys.Hole(i, h))
                if any(piece.Contains(v.GetPosition()) for v in gvias):
                    continue
                inner = pcbnew.SHAPE_POLY_SET(piece)
                inner.Deflate(mm(VIA / 2 + 0.01), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, mm(0.01))
                if inner.OutlineCount() == 0:
                    continue
                bb = piece.BBox()
                x0, y0 = pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop())
                x1, y1 = pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom())
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                pts = [(x0 + i * 0.05, y0 + j * 0.05) for i in range(int((x1 - x0) / 0.05) + 1)
                       for j in range(int((y1 - y0) / 0.05) + 1)]
                pts.sort(key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
                for x, y in pts:
                    if not inner.Contains(pcbnew.VECTOR2I(mm(x), mm(y))):
                        continue
                    v = fits(x, y)
                    if v is None:
                        continue
                    v.SetNet(gnd)
                    b.Add(v)
                    gvias.append(v)
                    holes.append(v)
                    added += 1
                    print("  via in a %s ground island at (%.2f, %.2f)" % (b.GetLayerName(layer), x - OX, y - OY))
                    break
                else:
                    print("  no room for a via in a %s ground island at (%.1f..%.1f, %.1f..%.1f)" % (
                        b.GetLayerName(layer), x0 - OX, x1 - OX, y0 - OY, y1 - OY))
    g.fill_zones(b)
    g.save_board(path, b)
    print("%s: %d island vias" % (os.path.basename(path), added))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(g.OUT, "brick-main.kicad_pcb"))
