"""A small grid router for the brick board, on top of KiCad's pcbnew API.

Why this exists: the boards are generated from code, and the usual
autorouter (Freerouting 2.2) needs Java 25, which the environment these files were
first made in lacked. The boards are small (under 50 x 14 mm, about 60 nets), so a plain
maze router does the job. KiCad's own DRC checks the result afterwards; this
router only has to be right, not clever.

Method
- Copper on each layer is rasterised onto a 0.05 mm grid, each cell holding
  the code of the net whose copper covers it (or -1 for keep-outs, board edge
  and holes).
- To route net N with track width w, every cell within w/2 + clearance of
  copper belonging to another net is blocked (a binary dilation).
- A* searches 8-connected moves on the routing layers plus vias, from the
  net's existing copper to the next pad, nearest pad first, so each net is a
  tree (no loops, which matters for anything inside the NFC antenna).
- Failed connections are retried with a narrower track, then by ripping up
  the nets in the way and routing them again afterwards.
- Ground pads on boards with a ground plane get a short track to a via into
  the plane instead of being routed to each other.
"""
import heapq
import math

import numpy as np
import pcbnew
from scipy import ndimage

MM = 1e6  # internal units per mm


def to_mm(v):
    return v / MM


class Router:
    def __init__(self, board, origin, size, route_layers, via_layers, pitch=0.05,
                 clearance=0.15, edge_clearance=0.3, via=(0.5, 0.3), plane_net=None, log=print):
        self.b = board
        self.ox, self.oy = origin
        self.w, self.h = size
        self.p = pitch
        self.nx = int(round(self.w / pitch)) + 1
        self.ny = int(round(self.h / pitch)) + 1
        self.route_layers = list(route_layers)
        self.via_layers = list(via_layers)
        self.all_layers = sorted(set(self.route_layers) | set(self.via_layers))
        self.clear = clearance
        self.edge_clear = edge_clearance
        self.via_d, self.via_drill = via
        self.plane_net = plane_net
        self.log = log
        self.occ = {l: np.zeros((self.ny, self.nx), np.int32) for l in self.all_layers}
        self.no_via = np.zeros((self.ny, self.nx), bool)
        self.no_track = {l: np.zeros((self.ny, self.nx), bool) for l in self.all_layers}
        yy, xx = np.mgrid[0:self.ny, 0:self.nx]
        self.cx = self.ox + xx * pitch
        self.cy = self.oy + yy * pitch
        self.added = {}      # net code -> list of board items this router added
        self.vmask = {}      # net code -> cells where a via or plated hole joins the layers
        self._disk_cache = {}

    # ------------------------------------------------------------------
    # Rasterising
    # ------------------------------------------------------------------
    def cell(self, x_mm, y_mm):
        return int(round((y_mm - self.oy) / self.p)), int(round((x_mm - self.ox) / self.p))

    def _poly_mask(self, pts):
        """Cells whose centres lie inside a closed polygon (list of (x, y) mm)."""
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        i0 = max(int(math.floor((min(ys) - self.oy) / self.p)) - 1, 0)
        i1 = min(int(math.ceil((max(ys) - self.oy) / self.p)) + 2, self.ny)
        j0 = max(int(math.floor((min(xs) - self.ox) / self.p)) - 1, 0)
        j1 = min(int(math.ceil((max(xs) - self.ox) / self.p)) + 2, self.nx)
        if i0 >= i1 or j0 >= j1:
            return None, None
        X = self.cx[i0:i1, j0:j1]
        Y = self.cy[i0:i1, j0:j1]
        inside = np.zeros(X.shape, bool)
        n = len(pts)
        for k in range(n):
            x1, y1 = pts[k]
            x2, y2 = pts[(k + 1) % n]
            cond = (y1 > Y) != (y2 > Y)
            with np.errstate(divide="ignore", invalid="ignore"):
                xint = (x2 - x1) * (Y - y1) / (y2 - y1 + 1e-30) + x1
            inside ^= cond & (X < xint)
        return (slice(i0, i1), slice(j0, j1)), inside

    def _item_polys(self, item, layer, extra=0):
        ps = pcbnew.SHAPE_POLY_SET()
        item.TransformShapeToPolygon(ps, layer, int(extra * MM), int(0.005 * MM), pcbnew.ERROR_OUTSIDE)
        out = []
        for oi in range(ps.OutlineCount()):
            ol = ps.Outline(oi)
            out.append([(to_mm(ol.CPoint(k).x), to_mm(ol.CPoint(k).y)) for k in range(ol.PointCount())])
        return out

    def paint(self, item, layer, value, extra=0):
        for poly in self._item_polys(item, layer, extra):
            sl, m = self._poly_mask(poly)
            if sl is None:
                continue
            region = self.occ[layer][sl]
            if value < 0:
                region[m] = value
            else:
                region[m & (region >= 0)] = value

    def paint_segment(self, layer, a, b, width, value):
        """Rasterise a straight track of the given width."""
        (x1, y1), (x2, y2) = a, b
        r = width / 2
        i0 = max(int(math.floor((min(y1, y2) - r - self.oy) / self.p)) - 1, 0)
        i1 = min(int(math.ceil((max(y1, y2) + r - self.oy) / self.p)) + 2, self.ny)
        j0 = max(int(math.floor((min(x1, x2) - r - self.ox) / self.p)) - 1, 0)
        j1 = min(int(math.ceil((max(x1, x2) + r - self.ox) / self.p)) + 2, self.nx)
        X = self.cx[i0:i1, j0:j1]
        Y = self.cy[i0:i1, j0:j1]
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        if L2 == 0:
            d2 = (X - x1) ** 2 + (Y - y1) ** 2
        else:
            t = np.clip(((X - x1) * dx + (Y - y1) * dy) / L2, 0, 1)
            d2 = (X - (x1 + t * dx)) ** 2 + (Y - (y1 + t * dy)) ** 2
        m = d2 <= r * r
        region = self.occ[layer][i0:i1, j0:j1]
        region[m & (region >= 0)] = value

    def paint_disc(self, layer, c, d, value):
        self.paint_segment(layer, c, c, d, value)

    def mark_via(self, code, c, d):
        m = self.vmask.setdefault(code, np.zeros((self.ny, self.nx), bool))
        i, j = self.cell(*c)
        r = int(math.ceil(d / 2 / self.p))
        m[max(i - r, 0):i + r + 1, max(j - r, 0):j + r + 1] = True

    def load_board(self, keepouts=(), fixed_only=False):
        """Paint the board. fixed_only leaves out unlocked tracks (used to
        tell an earlier router's tracks, which may be ripped up, from fixed
        copper)."""
        b = self.b
        # KiCad 9.0.9's bindings sometimes return a bare SwigPyObject from
        # GetFootprints()/GetTracks() after many edits, so read them once
        # here and keep our own lists from then on.
        self._pads = [p for f in b.GetFootprints() for p in f.Pads()]
        self._tracks = list(b.GetTracks())
        for (x0, y0, x1, y1) in keepouts:
            m = (self.cx >= self.ox + x0) & (self.cx <= self.ox + x1) & (self.cy >= self.oy + y0) & (self.cy <= self.oy + y1)
            for l in self.all_layers:
                self.occ[l][m] = -1
        # Board edge and the margin inside it.
        m = (self.cx < self.ox + self.edge_clear) | (self.cx > self.ox + self.w - self.edge_clear) | \
            (self.cy < self.oy + self.edge_clear) | (self.cy > self.oy + self.h - self.edge_clear)
        for l in self.all_layers:
            self.occ[l][m] = -1
        for f in b.GetFootprints():
            for pad in f.Pads():
                attr = pad.GetAttribute()
                if attr == pcbnew.PAD_ATTRIB_NPTH:
                    for l in self.all_layers:
                        c = (to_mm(pad.GetPosition().x), to_mm(pad.GetPosition().y))
                        d = max(to_mm(pad.GetDrillSize().x), to_mm(pad.GetDrillSize().y))
                        self.paint_disc(l, c, d + 2 * 0.25, -1)
                    continue
                code = pad.GetNetCode()
                for l in self.all_layers:
                    if pad.IsOnLayer(l):
                        self.paint(pad, l, code if code > 0 else -1)
                if attr == pcbnew.PAD_ATTRIB_PTH and code > 0:
                    self.mark_via(code, (to_mm(pad.GetPosition().x), to_mm(pad.GetPosition().y)),
                                  to_mm(pad.GetDrillSize().x))
                # no vias in pads
                for poly in self._item_polys(pad, pad.GetLayerSet().Seq()[0] if pad.GetLayerSet().Seq() else pcbnew.F_Cu,
                                             extra=self.via_d / 2 + 0.05):
                    sl, mm_ = self._poly_mask(poly)
                    if sl is not None:
                        self.no_via[sl] |= mm_
            # Copper drawn in footprints (the NFC loop) is a hard obstacle.
            for g in f.GraphicalItems():
                if g.GetLayer() in self.all_layers:
                    self.paint(g, g.GetLayer(), -1)
        for t in self._tracks:
            if fixed_only and not t.IsLocked():
                continue
            code = t.GetNetCode()
            if t.GetClass() == "PCB_VIA":
                for l in self.all_layers:
                    self.paint_disc(l, (to_mm(t.GetPosition().x), to_mm(t.GetPosition().y)), to_mm(t.GetWidth(pcbnew.F_Cu)), code)
                self.mark_via(code, (to_mm(t.GetPosition().x), to_mm(t.GetPosition().y)), 0.2)
            else:
                if t.GetLayer() in self.all_layers:
                    self.paint_segment(t.GetLayer(), (to_mm(t.GetStart().x), to_mm(t.GetStart().y)),
                                       (to_mm(t.GetEnd().x), to_mm(t.GetEnd().y)), to_mm(t.GetWidth()), code)
        self.occ_fixed = None
        for z in b.Zones():
            if not z.GetIsRuleArea():
                continue
            o = z.Outline()
            pts = [(to_mm(o.CVertex(k).x), to_mm(o.CVertex(k).y)) for k in range(o.TotalVertices())]
            sl, mk = self._poly_mask(pts)
            if sl is None:
                continue
            for l in self.all_layers:
                if z.IsOnLayer(l):
                    if z.GetDoNotAllowTracks():
                        self.no_track[l][sl] |= mk
                    if z.GetDoNotAllowVias():
                        self.no_via[sl] |= mk

    def freeze(self):
        """Remember the copper that exists before routing (pads, fixed tracks)."""
        self.occ_fixed = {l: self.occ[l].copy() for l in self.all_layers}

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def disk(self, r_mm):
        r = int(math.ceil(r_mm / self.p))
        key = r
        if key not in self._disk_cache:
            yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
            self._disk_cache[key] = (xx * xx + yy * yy) * self.p * self.p <= (r_mm + 0.5 * self.p) ** 2
        return self._disk_cache[key]

    def blocked_for(self, code, width, relaxed=False):
        occ = self.occ_fixed if relaxed else self.occ
        r = width / 2 + self.clear + 1.2 * self.p   # 1.2 cells: 0.6 left occasional 0.12 mm gaps
        out = {}
        for l in self.route_layers:
            other = (occ[l] != 0) & (occ[l] != code)
            bl = ndimage.binary_dilation(other, structure=self.disk(r))
            out[l] = bl | self.no_track[l]
        rv = self.via_d / 2 + self.clear + 1.2 * self.p
        vb = self.no_via.copy()
        for l in self.all_layers:
            other = (occ[l] != 0) & (occ[l] != code)
            vb |= ndimage.binary_dilation(other, structure=self.disk(rv))
        return out, vb

    def astar(self, code, width, sources, targets, via_cost=10.0, turn_cost=0.4, window_mm=None, max_expand=400000,
              relaxed=False):
        """sources/targets: dict layer -> bool mask. Returns list of (layer, i, j).
        With window_mm, the search stays inside the bounding box of sources
        and targets grown by that much. relaxed ignores copper the router
        itself has laid (to find what is in the way)."""
        blocked, via_blocked = self.blocked_for(code, width, relaxed)
        L = self.route_layers
        li = {l: k for k, l in enumerate(L)}
        tgt = {l: targets.get(l, np.zeros((self.ny, self.nx), bool)) & ~blocked[l] for l in L}
        tcells = [(i, j) for l in L for i, j in zip(*np.nonzero(tgt[l]))]
        if not tcells:
            return None
        ti = np.array([c[0] for c in tcells])
        tj = np.array([c[1] for c in tcells])
        ci, cj = ti.mean(), tj.mean()
        rad = max(np.hypot(ti - ci, tj - cj).max(), 0)

        def h(i, j):
            d = math.hypot(i - ci, j - cj) - rad
            return max(d, 0.0)

        if window_mm is not None:
            allm = np.zeros((self.ny, self.nx), bool)
            for m in list(sources.values()) + list(targets.values()):
                allm |= m
            ii, jj = np.nonzero(allm)
            pad_ = int(window_mm / self.p)
            imin, imax = max(ii.min() - pad_, 0), min(ii.max() + pad_, self.ny - 1)
            jmin, jmax = max(jj.min() - pad_, 0), min(jj.max() + pad_, self.nx - 1)
        else:
            imin, imax, jmin, jmax = 0, self.ny - 1, 0, self.nx - 1
        INF = 1e18
        g = np.full((len(L), self.ny, self.nx), INF)
        parent = {}
        heap = []
        for l, m in sources.items():
            if l not in li:
                continue
            for i, j in zip(*np.nonzero(m & ~blocked[l])):
                k = li[l]
                g[k, i, j] = 0.0
                heapq.heappush(heap, (1.2 * h(i, j), 0.0, k, i, j, -1))
        moves = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
                 (-1, -1, 1.4142), (-1, 1, 1.4142), (1, -1, 1.4142), (1, 1, 1.4142)]
        found = None
        expanded = 0
        while heap:
            f, gc, k, i, j, d = heapq.heappop(heap)
            if gc > g[k, i, j]:
                continue
            if tgt[L[k]][i, j]:
                found = (k, i, j)
                break
            expanded += 1
            if expanded > max_expand:
                break
            for di, (a, bb, c) in enumerate(moves):
                ni, nj = i + a, j + bb
                if ni < imin or nj < jmin or ni > imax or nj > jmax:
                    continue
                if blocked[L[k]][ni, nj]:
                    continue
                nc = gc + c + (turn_cost if d >= 0 and d != di else 0.0)
                if nc < g[k, ni, nj]:
                    g[k, ni, nj] = nc
                    parent[(k, ni, nj)] = (k, i, j)
                    heapq.heappush(heap, (nc + 1.2 * h(ni, nj), nc, k, ni, nj, di))
            if len(L) > 1 and not via_blocked[i, j]:
                for k2 in range(len(L)):
                    if k2 == k or blocked[L[k2]][i, j]:
                        continue
                    nc = gc + via_cost
                    if nc < g[k2, i, j]:
                        g[k2, i, j] = nc
                        parent[(k2, i, j)] = (k, i, j)
                        heapq.heappush(heap, (nc + 1.2 * h(i, j), nc, k2, i, j, -1))
        if not found:
            return None
        path = [found]
        while path[-1] in parent:
            path.append(parent[path[-1]])
        path.reverse()
        return [(L[k], i, j) for k, i, j in path]

    # ------------------------------------------------------------------
    # Committing a path to the board
    # ------------------------------------------------------------------
    def pt(self, i, j):
        return (self.ox + j * self.p, self.oy + i * self.p)

    def commit(self, code, path, width, end_snap=None):
        items = self.added.setdefault(code, [])
        netinfo = self.b.FindNet(code)
        # split by layer
        runs = []
        cur = [path[0]]
        for st in path[1:]:
            if st[0] != cur[-1][0]:
                runs.append(cur)
                cur = [st]
            else:
                cur.append(st)
        runs.append(cur)
        for r_idx, run in enumerate(runs):
            layer = run[0][0]
            pts = [self.pt(i, j) for _, i, j in run]
            if r_idx == len(runs) - 1 and end_snap and end_snap[0] == layer:
                pts.append(end_snap[1])
            if r_idx == 0 and getattr(self, "_start_snap", None) and self._start_snap[0] == layer:
                pts.insert(0, self._start_snap[1])
            simp = [pts[0]]
            for k in range(1, len(pts) - 1):
                a, b, c = simp[-1], pts[k], pts[k + 1]
                if abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) > 1e-9:
                    simp.append(b)
            simp.append(pts[-1])
            for a, b in zip(simp, simp[1:]):
                if math.dist(a, b) < 1e-6:
                    continue
                t = pcbnew.PCB_TRACK(self.b)
                t.SetStart(pcbnew.VECTOR2I(int(round(a[0] * MM)), int(round(a[1] * MM))))
                t.SetEnd(pcbnew.VECTOR2I(int(round(b[0] * MM)), int(round(b[1] * MM))))
                t.SetWidth(int(round(width * MM)))
                t.SetLayer(layer)
                t.SetNet(netinfo)
                self.b.Add(t)
                items.append(t)
                self._tracks.append(t)
                self.paint_segment(layer, a, b, width, code)
            if r_idx < len(runs) - 1:
                c = pts[-1]
                v = pcbnew.PCB_VIA(self.b)
                v.SetPosition(pcbnew.VECTOR2I(int(round(c[0] * MM)), int(round(c[1] * MM))))
                v.SetWidth(int(round(self.via_d * MM)))
                v.SetDrill(int(round(self.via_drill * MM)))
                v.SetNet(netinfo)
                self.b.Add(v)
                items.append(v)
                self._tracks.append(v)
                for l in self.all_layers:
                    self.paint_disc(l, c, self.via_d, code)
                self.mark_via(code, c, 0.2)

    def rip(self, code):
        gone = self.added.pop(code, [])
        ids = set(id(it) for it in gone)
        for it in gone:
            self.b.Remove(it)
        self._graveyard = getattr(self, "_graveyard", []) + gone   # keep the wrappers alive
        self._tracks = [t for t in self._tracks if id(t) not in ids]
        self.vmask.pop(code, None)
        for pad in self._pads:
            if pad.GetNetCode() == code and pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                self.mark_via(code, (to_mm(pad.GetPosition().x), to_mm(pad.GetPosition().y)), to_mm(pad.GetDrillSize().x))
        for t in self._tracks:
            if t.GetNetCode() == code and t.GetClass() == "PCB_VIA":
                self.mark_via(code, (to_mm(t.GetPosition().x), to_mm(t.GetPosition().y)), 0.2)
        for l in self.all_layers:
            self.occ[l][self.occ[l] == code] = 0
        # repaint the net's fixed copper (pads, pre-routed items)
        for pad in self._pads:
            if pad.GetNetCode() == code:
                for l in self.all_layers:
                    if pad.IsOnLayer(l):
                        self.paint(pad, l, code)
        for t in self._tracks:
            if t.GetNetCode() == code:
                if t.GetClass() == "PCB_VIA":
                    for l in self.all_layers:
                        self.paint_disc(l, (to_mm(t.GetPosition().x), to_mm(t.GetPosition().y)), to_mm(t.GetWidth(pcbnew.F_Cu)), code)
                elif t.GetLayer() in self.all_layers:
                    self.paint_segment(t.GetLayer(), (to_mm(t.GetStart().x), to_mm(t.GetStart().y)),
                                       (to_mm(t.GetEnd().x), to_mm(t.GetEnd().y)), to_mm(t.GetWidth()), code)

    # ------------------------------------------------------------------
    # Nets
    # ------------------------------------------------------------------
    def pad_mask(self, pad, layer):
        m = np.zeros((self.ny, self.nx), bool)
        for poly in self._item_polys(pad, layer):
            sl, mk = self._poly_mask(poly)
            if sl is not None:
                m[sl] |= mk
        return m

    def net_pads(self, code):
        return [p for p in self._pads if p.GetNetCode() == code and p.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH]

    def islands(self, code):
        """Label the net's copper: returns (labels per layer, root of each label)."""
        labs = {}
        off = 0
        for l in self.all_layers:
            lab, n = ndimage.label(self.occ[l] == code, structure=np.ones((3, 3), int))
            lab[lab > 0] += off
            labs[l] = lab
            off += n
        parent = list(range(off + 1))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a
        vm = self.vmask.get(code)
        if vm is not None and vm.any():
            ii, jj = np.nonzero(vm)
            for i, j in zip(ii, jj):
                ids = [int(labs[l][i, j]) for l in self.all_layers if labs[l][i, j] > 0]
                for a in ids[1:]:
                    ra, rb = find(ids[0]), find(a)
                    if ra != rb:
                        parent[rb] = ra
        return labs, find

    def pad_root(self, pad, labs, find):
        for l in self.all_layers:
            if pad.IsOnLayer(l):
                m = self.pad_mask(pad, l)
                v = labs[l][m]
                v = v[v > 0]
                if v.size:
                    return find(int(v[0]))
        return None

    def island_mask(self, root, labs, find):
        out = {}
        for l in self.route_layers:
            lab = labs[l]
            ids = np.unique(lab[lab > 0])
            keep = [k for k in ids if find(int(k)) == root]
            out[l] = np.isin(lab, keep) if keep else np.zeros((self.ny, self.nx), bool)
        return out

    def route_net(self, code, widths):
        pads = self.net_pads(code)
        if len(pads) < 2:
            return True
        name = self.b.FindNet(code).GetNetname()

        def pc(p):
            return (to_mm(p.GetPosition().x), to_mm(p.GetPosition().y))
        given_up = set()
        ok = True
        for _ in range(4 * len(pads)):
            labs, find = self.islands(code)
            roots = {id(p): self.pad_root(p, labs, find) for p in pads}
            tree = roots[id(pads[0])]
            if tree is None:
                self.log("  %s: first pad has no copper" % name)
                return False
            todo = [p for p in pads if roots[id(p)] != tree and roots[id(p)] not in given_up]
            if not todo:
                break
            tree_pads = [p for p in pads if roots[id(p)] == tree]
            target = min(todo, key=lambda b: min(math.dist(pc(a), pc(b)) for a in tree_pads))
            troot = roots[id(target)]
            src = self.island_mask(tree, labs, find)
            tgt = self.island_mask(troot, labs, find)
            path = None
            for win, w in [(4.0, w) for w in widths] + [(None, widths[-1])]:
                path = self.astar(code, w, src, tgt, window_mm=win,
                                  max_expand=250000 if win else 1200000)
                if path:
                    self.commit(code, path, w)
                    break
            if not path:
                self.log("  could not reach %s pad %s%s" % (name, target.GetParentFootprint().GetReference(), target.GetNumber()))
                self.last_fail = (code, src, tgt, widths[-1])
                given_up.add(troot)
                ok = False
        return ok

    def blockers(self, code, src, tgt, width):
        """Nets laid by this router that sit on the best path for a failed
        connection, found by searching with only fixed copper in the way."""
        path = self.astar(code, width, src, tgt, relaxed=True, max_expand=1500000)
        if not path:
            return None
        r = int(math.ceil((width / 2 + self.clear + 0.3) / self.p))
        found = set()
        for l, i, j in path:
            win = self.occ[l][max(i - r, 0):i + r + 1, max(j - r, 0):j + r + 1]
            fix = self.occ_fixed[l][max(i - r, 0):i + r + 1, max(j - r, 0):j + r + 1]
            for v in np.unique(win[(win > 0) & (win != fix)]):
                if int(v) != code:
                    found.add(int(v))
        return found

    def stitch_grid(self, code, step=1.2, margin=0.6, keep=()):
        """Ground vias on a grid wherever one fits on every layer, so the
        pours on the outer layers join the inner planes everywhere."""
        r = self.via_d / 2 + self.clear
        made = 0
        y = margin
        while y <= self.h - margin:
            x = margin
            while x <= self.w - margin:
                if not any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in keep):
                    c = (self.ox + x, self.oy + y)
                    i0, j0 = self.cell(*c)
                    k = int(math.ceil(r / self.p))
                    sl = (slice(max(i0 - k, 0), i0 + k + 1), slice(max(j0 - k, 0), j0 + k + 1))
                    ok = not self.no_via[sl].any()
                    if ok:
                        for l in self.all_layers:
                            win = self.occ[l][sl]
                            if ((win != 0) & (win != code)).any() or self.no_track[l][sl].any():
                                ok = False
                                break
                    if ok:
                        v = pcbnew.PCB_VIA(self.b)
                        v.SetPosition(pcbnew.VECTOR2I(int(round(c[0] * MM)), int(round(c[1] * MM))))
                        v.SetWidth(int(round(self.via_d * MM)))
                        v.SetDrill(int(round(self.via_drill * MM)))
                        v.SetNet(self.b.FindNet(code))
                        self.b.Add(v)
                        for l in self.all_layers:
                            self.paint_disc(l, c, self.via_d, code)
                        made += 1
                x += step
            y += step
        return made

    def stitch_to_plane(self, code, width=0.25, max_mm=2.0):
        """Give every SMD pad of the plane net a short track and a via."""
        made = 0
        for pad in self.net_pads(code):
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                continue
            layer = pcbnew.F_Cu if pad.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
            if layer not in self.route_layers:
                continue
            blocked, vb = self.blocked_for(code, width)
            src = {layer: self.pad_mask(pad, layer)}
            c = (to_mm(pad.GetPosition().x), to_mm(pad.GetPosition().y))
            i0, j0 = self.cell(*c)
            r = int(max_mm / self.p)
            tgt = np.zeros((self.ny, self.nx), bool)
            ys = slice(max(i0 - r, 0), min(i0 + r + 1, self.ny))
            xs = slice(max(j0 - r, 0), min(j0 + r + 1, self.nx))
            tgt[ys, xs] = ~vb[ys, xs] & ~blocked[layer][ys, xs]
            if not tgt.any():
                self.log("  no room for a ground via at %s%s" % (pad.GetParentFootprint().GetReference(), pad.GetNumber()))
                continue
            self.route_layers_backup = self.route_layers
            self.route_layers = [layer]
            path = self.astar(code, width, src, {layer: tgt}, window_mm=max_mm + 0.5)
            self.route_layers = self.route_layers_backup
            if not path:
                continue
            # track from the pad centre to the via
            path = [(layer, *self.cell(*c))] + path if path[0][1:] != self.cell(*c) else path
            if len(path) >= 2:
                self.commit(code, path, width)
            li, lj = path[-1][1], path[-1][2]
            v = pcbnew.PCB_VIA(self.b)
            v.SetPosition(pcbnew.VECTOR2I(int(round(self.pt(li, lj)[0] * MM)), int(round(self.pt(li, lj)[1] * MM))))
            v.SetWidth(int(round(self.via_d * MM)))
            v.SetDrill(int(round(self.via_drill * MM)))
            v.SetNet(self.b.FindNet(code))
            self.b.Add(v)
            self._stitched = getattr(self, "_stitched", []) + [v]
            self.added.setdefault(code, []).append(v)
            for l in self.all_layers:
                self.paint_disc(l, self.pt(li, lj), self.via_d, code)
            self.mark_via(code, self.pt(li, lj), 0.2)
            made += 1
        return made
