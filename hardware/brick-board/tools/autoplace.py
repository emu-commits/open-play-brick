"""Greedy placer for the brick board's small parts.

The connectors, the module, the NFC chip and the board-to-board header are
placed by hand in gen_board.py. Every other part names the pad it serves
(its anchor), a preferred side and a fallback side. Parts are placed one at a
time, in the order given, at the free spot and rotation that puts the part's
own pad on the anchor's net closest to the anchor pad. "Free" means the part's
footprint (courtyard and pads, plus a margin) overlaps nothing already placed
and no keep-out area, checked on a 0.1 mm occupancy grid with an integral
image so that every candidate position is tested at once.
"""
import math

import numpy as np
import pcbnew

GRID = 0.1
MARGIN = 0.12


class Placer:
    def __init__(self, board, origin, size, edge=0.3, margin=MARGIN):
        self.b = board
        self.margin = margin   # free space kept around every placed part, mm
        self.ox, self.oy = origin
        self.w, self.h = size
        self.nx = int(round(self.w / GRID))
        self.ny = int(round(self.h / GRID))
        self.occ = {"T": np.zeros((self.ny, self.nx), bool), "B": np.zeros((self.ny, self.nx), bool)}
        e = int(round(edge / GRID))
        for s in self.occ.values():
            s[:e, :] = s[-e:, :] = True
            s[:, :e] = s[:, -e:] = True

    # grid helpers ---------------------------------------------------------
    def block_rect(self, side, x0, y0, x1, y1):
        """Block a rectangle given in board mm (relative to origin)."""
        j0 = max(int(math.floor(x0 / GRID)), 0)
        j1 = min(int(math.ceil(x1 / GRID)), self.nx)
        i0 = max(int(math.floor(y0 / GRID)), 0)
        i1 = min(int(math.ceil(y1 / GRID)), self.ny)
        for s in ("T", "B") if side == "both" else (side,):
            self.occ[s][i0:i1, j0:j1] = True

    def footprint_box(self, f, margin=None):
        """Bounding box of courtyard and pads, in board mm, plus margin."""
        margin = self.margin if margin is None else margin
        side = "B" if f.IsFlipped() else "T"
        bb = None
        cy = f.GetCourtyard(pcbnew.B_CrtYd if side == "B" else pcbnew.F_CrtYd)
        if cy.OutlineCount():
            bb = cy.BBox()
        for p in f.Pads():
            pb = p.GetBoundingBox()
            if bb is None:
                bb = pb
            else:
                bb.Merge(pb)
        to = lambda v, o: pcbnew.ToMM(v) - o
        return side, (to(bb.GetLeft(), self.ox) - margin, to(bb.GetTop(), self.oy) - margin,
                      to(bb.GetRight(), self.ox) + margin, to(bb.GetBottom(), self.oy) + margin)

    def block_footprint(self, f):
        side, (x0, y0, x1, y1) = self.footprint_box(f)
        self.block_rect(side, x0, y0, x1, y1)
        # through-hole pads and holes block the other side too
        for p in f.Pads():
            if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                pb = p.GetBoundingBox()
                self.block_rect("both", pcbnew.ToMM(pb.GetLeft()) - self.ox - self.margin, pcbnew.ToMM(pb.GetTop()) - self.oy - self.margin,
                                pcbnew.ToMM(pb.GetRight()) - self.ox + self.margin, pcbnew.ToMM(pb.GetBottom()) - self.oy + self.margin)

    def block_vias(self):
        for t in self.b.GetTracks():
            if t.GetClass() == "PCB_VIA":
                x = pcbnew.ToMM(t.GetPosition().x) - self.ox
                y = pcbnew.ToMM(t.GetPosition().y) - self.oy
                r = pcbnew.ToMM(t.GetWidth(pcbnew.F_Cu)) / 2 + self.margin
                self.block_rect("both", x - r, y - r, x + r, y + r)

    # placing ----------------------------------------------------------------
    def place(self, f, anchor_xy, key_net, sides, radius=30.0):
        """Move footprint f to the best free spot. Returns (side, x, y, rot) or None."""
        best = None
        for side in sides:
            occ = self.occ[side]
            ii = np.zeros((self.ny + 1, self.nx + 1), np.int32)
            ii[1:, 1:] = occ.astype(np.int32).cumsum(0).cumsum(1)
            for rot in (0, 90, 180, 270):
                f.SetOrientationDegrees(0)
                if f.IsFlipped():
                    f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
                f.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(self.ox), pcbnew.FromMM(self.oy)))
                f.SetOrientationDegrees(rot)
                if side == "B":
                    f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
                _, (x0, y0, x1, y1) = self.footprint_box(f)
                # relative to the footprint origin (now at board 0,0)
                key = [p for p in f.Pads() if p.GetNetname() == key_net]
                kx = (pcbnew.ToMM(key[0].GetPosition().x) - self.ox) if key else 0.0
                ky = (pcbnew.ToMM(key[0].GetPosition().y) - self.oy) if key else 0.0
                wj = int(math.ceil((x1 - x0) / GRID))
                hi = int(math.ceil((y1 - y0) / GRID))
                # candidate origins on the grid within radius of the anchor
                ax, ay = anchor_xy
                xs = np.arange(max(ax - radius, -x0), min(ax + radius, self.w - x1), GRID)
                ys = np.arange(max(ay - radius, -y0), min(ay + radius, self.h - y1), GRID)
                if len(xs) == 0 or len(ys) == 0:
                    continue
                X, Y = np.meshgrid(xs, ys)
                j0 = np.floor((X + x0) / GRID).astype(int)
                i0 = np.floor((Y + y0) / GRID).astype(int)
                j1 = np.clip(j0 + wj, 0, self.nx)
                i1 = np.clip(i0 + hi, 0, self.ny)
                j0 = np.clip(j0, 0, self.nx)
                i0 = np.clip(i0, 0, self.ny)
                filled = ii[i1, j1] - ii[i0, j1] - ii[i1, j0] + ii[i0, j0]
                ok = filled == 0
                # through holes must also land on free board on the other side
                other = "B" if side == "T" else "T"
                holes = [p.GetBoundingBox() for p in f.Pads()
                         if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)]
                if holes:
                    io = np.zeros((self.ny + 1, self.nx + 1), np.int32)
                    io[1:, 1:] = self.occ[other].astype(np.int32).cumsum(0).cumsum(1)
                    for hb in holes:
                        hx0 = pcbnew.ToMM(hb.GetLeft()) - self.ox - self.margin
                        hy0 = pcbnew.ToMM(hb.GetTop()) - self.oy - self.margin
                        hx1 = pcbnew.ToMM(hb.GetRight()) - self.ox + self.margin
                        hy1 = pcbnew.ToMM(hb.GetBottom()) - self.oy + self.margin
                        a0 = np.clip(np.floor((X + hx0) / GRID).astype(int), 0, self.nx)
                        b0 = np.clip(np.floor((Y + hy0) / GRID).astype(int), 0, self.ny)
                        a1 = np.clip(np.ceil((X + hx1) / GRID).astype(int), 0, self.nx)
                        b1 = np.clip(np.ceil((Y + hy1) / GRID).astype(int), 0, self.ny)
                        ok &= (io[b1, a1] - io[b0, a1] - io[b1, a0] + io[b0, a0]) == 0
                if not ok.any():
                    continue
                d = np.hypot(X + kx - ax, Y + ky - ay) + 0.15 * np.hypot(X - ax, Y - ay)
                d = np.where(ok, d, np.inf)
                k = np.unravel_index(np.argmin(d), d.shape)
                cost = d[k] + (0.0 if side == sides[0] else 1.5)
                if best is None or cost < best[0]:
                    best = (cost, side, float(X[k]), float(Y[k]), rot)
        if best is None:
            return None
        _, side, x, y, rot = best
        f.SetOrientationDegrees(0)
        if f.IsFlipped():
            f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        f.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(self.ox + x), pcbnew.FromMM(self.oy + y)))
        f.SetOrientationDegrees(rot)
        if side == "B":
            f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        self.block_footprint(f)
        return side, round(x, 2), round(y, 2), rot
