#!/usr/bin/env python3
"""NFC loop antenna and PN5180 matching network for the brick board.

What this does, in order:

1. Works out the inductance of the printed loop on the face board from its
   geometry, by summing the partial inductances of its straight segments
   (Greenhouse's method: Ruehli's self term, Grover's mutual term for parallel
   filaments, geometric-mean-distance correction for neighbouring tracks).
2. Subtracts the effect of the main board's ground plane underneath, treated
   as a perfect conductor at 13.56 MHz (its copper is about two skin depths
   thick), using an image loop at twice the spacing.
3. Estimates the loop's resistance at 13.56 MHz.
4. Solves the asymmetric matching network of NXP AN11740 (EMC filter L0/C0,
   series C1, parallel C2, damping Rq) for a target impedance between TX1 and
   TX2, and checks the solver against the worked example in that note.
5. Picks real capacitor values (1 % C0G parts JLCPCB stocks), then runs a
   tolerance sweep to show how far the result can move.

Everything here is a calculation, not a measurement. NXP's own procedure
measures the coil with a network analyser and then trims the capacitors. This
script gives first-board values; tools/README in this folder says how to
check and correct them.

Run:  python3 nfc_antenna.py            (prints the design)
      python3 nfc_antenna.py --check    (exit 1 if the solver disagrees with
                                         NXP's worked example)
"""
import cmath
import math
import random
import sys

MU0 = 4e-7 * math.pi
F = 13.56e6
W = 2 * math.pi * F
RHO_CU = 1.72e-8

# --------------------------------------------------------------------------
# Loop geometry (millimetres). Must agree with the face board layout, which
# reads these numbers from here (see gen_board.py).
# --------------------------------------------------------------------------
LOOP = dict(
    outer_x=22.6,       # outer size along the brick
    outer_y=12.8,       # outer size across the brick
    turns=6,
    width=0.20,         # track width
    space=0.15,         # gap between turns
    copper_um=35.0,     # 1 oz outer layer
    ground_gap_mm=6.6,  # loop copper to the main board's top copper (see the stack in README.md)
)

# --------------------------------------------------------------------------
# Inductance
# --------------------------------------------------------------------------

def spiral_segments(outer_x, outer_y, turns, width, space, step=0.6, stub=0.8):
    """Centre-line polyline of a rectangular spiral, as straight segments
    ((x0, y0), (x1, y1)) in mm.

    It starts half-way up the left side (the outer terminal, which a short
    lead takes out to a via beyond the loop), runs anticlockwise in screen
    terms (down, right, up, left), and steps one pitch inwards on the left
    side just above the start, each turn's step one pitch higher than the
    last. The inner end finishes with a short stub into the loop's middle,
    where the inner terminal's via sits clear of the turns."""
    pitch = width + space
    x0, y0 = width / 2, width / 2
    x1, y1 = outer_x - width / 2, outer_y - width / 2
    ys = (y0 + y1) / 2
    pts = [(x0, ys)]
    for k in range(turns):
        e = k * pitch
        pts += [(x0 + e, y0 + e), (x1 - e, y0 + e), (x1 - e, y1 - e), (x0 + e, y1 - e),
                (x0 + e, ys + step + e)]
        if k < turns - 1:
            pts.append((x0 + e + pitch, ys + step + e))
    pts.append((pts[-1][0] + stub, pts[-1][1]))
    return list(zip(pts[:-1], pts[1:]))


def self_l(length_m, w_m, t_m):
    """Ruehli: straight rectangular bar."""
    return MU0 / (2 * math.pi) * length_m * (math.log(2 * length_m / (w_m + t_m)) + 0.5 + 0.2235 * (w_m + t_m) / length_m)


def _H(u, d):
    return u * math.asinh(u / d) - math.sqrt(u * u + d * d)


def mutual_parallel(a0, a1, b0, b1, d):
    """Grover: two parallel filaments along one axis, spans [a0,a1] and
    [b0,b1], perpendicular distance d (metres). Positive for same direction
    when a0<a1 and b0<b1."""
    return MU0 / (4 * math.pi) * (_H(a1 - b0, d) - _H(a0 - b0, d) - _H(a1 - b1, d) + _H(a0 - b1, d))


def gmd(d, w):
    """Geometric mean distance between two equal thin strips side by side."""
    r = d / w
    return d * math.exp(-(1 / (12 * r * r) + 1 / (60 * r ** 4) + 1 / (168 * r ** 6) + 1 / (360 * r ** 8)))


def loop_inductance(geo, with_ground=True):
    segs = spiral_segments(geo["outer_x"], geo["outer_y"], geo["turns"], geo["width"], geo["space"])
    w = geo["width"] * 1e-3
    t = geo["copper_um"] * 1e-6
    total = 0.0
    image = 0.0
    h2 = 2 * geo["ground_gap_mm"] * 1e-3
    for i, (p0, p1) in enumerate(segs):
        horiz_i = abs(p1[1] - p0[1]) < 1e-9
        li = math.dist(p0, p1) * 1e-3
        total += self_l(li, w, t)
        for j, (q0, q1) in enumerate(segs):
            horiz_j = abs(q1[1] - q0[1]) < 1e-9
            if horiz_i != horiz_j:
                continue
            if horiz_i:
                a0, a1, b0, b1 = p0[0], p1[0], q0[0], q1[0]
                d = abs(p0[1] - q0[1])
            else:
                a0, a1, b0, b1 = p0[1], p1[1], q0[1], q1[1]
                d = abs(p0[0] - q0[0])
            sa = 1 if a1 > a0 else -1
            sb = 1 if b1 > b0 else -1
            lo_a, hi_a = sorted((a0, a1))
            lo_b, hi_b = sorted((b0, b1))
            if j != i:
                if d < 1e-6:          # collinear pieces of the same side, end to end
                    dd = 1e-4
                else:
                    dd = gmd(d, geo["width"]) if d < 3 * geo["width"] else d
                total += sa * sb * mutual_parallel(lo_a * 1e-3, hi_a * 1e-3, lo_b * 1e-3, hi_b * 1e-3, dd * 1e-3)
            if with_ground:
                dz = math.hypot(d * 1e-3, h2)
                image += sa * sb * mutual_parallel(lo_a * 1e-3, hi_a * 1e-3, lo_b * 1e-3, hi_b * 1e-3, dz)
    return total - image, total, segs


def loop_resistance(geo, segs):
    length = sum(math.dist(a, b) for a, b in segs) * 1e-3
    w = geo["width"] * 1e-3
    t = geo["copper_um"] * 1e-6
    delta = math.sqrt(RHO_CU / (math.pi * F * MU0))
    # Current flows in a skin on both faces of the track; neighbouring turns
    # crowd it further (proximity effect), here a flat factor of 1.6.
    r_skin = RHO_CU * length / (2 * w * delta * (1 - math.exp(-t / (2 * delta))))
    return r_skin * 1.6, length, delta

# --------------------------------------------------------------------------
# Matching network (asymmetric tuning, AN11740 Fig. 21)
# --------------------------------------------------------------------------

def par(a, b):
    return a * b / (a + b)


def z_diff(La, Ra, Ca, Rq, C1, C2, L0, C0, f=F):
    """Impedance between TX1 and TX2 with the PN5180 removed."""
    w = 2 * math.pi * f
    za = par(Ra / 2 + 1j * w * La / 2, 1 / (1j * w * 2 * Ca))
    z = Rq + za
    z = par(z, 1 / (1j * w * C2))
    z = z + 1 / (1j * w * C1)
    z = par(z, 1 / (1j * w * C0))
    z = z + 1j * w * L0
    return 2 * z


def solve_match(La, Ra, Ca, Q, Rmatch, L0, C0):
    """Return Rq (per side), C1 and C2 (per side) so that z_diff is real and
    equal to Rmatch at 13.56 MHz. Solved in closed form on the half circuit,
    working back from the target impedance."""
    Rq = max((W * La / Q - Ra) / 2, 0.0)
    zb = Rq + par(Ra / 2 + 1j * W * La / 2, 1 / (1j * W * 2 * Ca))   # antenna side of C2
    ze = Rmatch / 2 - 1j * W * L0                                   # what C0 || (C1 + ...) must be
    zd = 1 / (1 / ze - 1j * W * C0)                                 # what C1 + (C2 || zb) must be
    yb = 1 / zb
    g, b = yb.real, yb.imag
    disc = g / zd.real - g * g
    if disc <= 0:
        raise ValueError("target impedance not reachable with this coil")
    best = None
    for root in (math.sqrt(disc), -math.sqrt(disc)):
        c2 = (root - b) / W
        if c2 <= 0:
            continue
        zc = 1 / (g + 1j * root)
        x1 = zc.imag - zd.imag            # reactance C1 must cancel, = 1/(w C1)
        if x1 <= 0:
            continue
        c1 = 1 / (W * x1)
        if best is None or c2 < best[1]:
            best = (c1, c2)
    if best is None:
        raise ValueError("no positive C1, C2 solution")
    return Rq, best[0], best[1]


def itvdd(z, tvdd, r_driver=2.0):
    """Rough supply current: fundamental of a full-swing differential square
    wave into the antenna, plus driver loss."""
    v1 = 4 / math.pi * tvdd               # peak of the fundamental, differential
    zt = z + 2 * r_driver
    i_pk = v1 / abs(zt)
    p = 0.5 * i_pk ** 2 * zt.real
    return p / tvdd

# 1 % C0G 0402 values in stock at JLCPCB (Yageo CC0402FRNPO9BN series).
E12 = [10, 12, 15, 18, 22, 27, 33, 39, 47, 56, 68, 82]
STOCK_PF = sorted({v * m for v in E12 for m in (1, 10)} | {1.0, 1.5, 2.2, 3.3, 4.7, 5.6, 6.8, 8.2})


def best_pair(target_pf):
    """One or two standard values in parallel closest to the target."""
    best = None
    for a in STOCK_PF:
        for b in [0.0] + STOCK_PF:
            s = a + b
            err = abs(s - target_pf)
            cost = (err, b != 0.0)
            if best is None or cost < best[0]:
                best = (cost, a, b)
    return best[1], best[2]

# --------------------------------------------------------------------------

def check_against_nxp():
    """AN11740 section 4.2.1.4: La 1533 nH, Ra 3 ohm, Ca 0.1 pF, Q 25,
    Rmatch 20 ohm, L0 470 nH, C0 124 pF -> Rq 1.1, C1 41.6 pF, C2 125.6 pF."""
    Rq, C1, C2 = solve_match(1533e-9, 3.0, 0.1e-12, 25, 20.0, 470e-9, 124e-12)
    ok = abs(Rq - 1.1) < 0.05 and abs(C1 * 1e12 - 41.6) < 1.5 and abs(C2 * 1e12 - 125.6) < 3.0
    return ok, Rq, C1, C2


# Q 12 and 50 ohm rather than NXP's 20 to 25 and 20 ohm: the brick reads tags
# lying on it, so it needs robustness to coil tolerance and low battery drain
# more than maximum field. AN11740 suggests 50 to 80 ohm for battery devices.
DESIGN = dict(Q=12, Rmatch=50.0, L0=470e-9, C0_pf=(56, 68), Ca=2.5e-12)
RQ_STOCK = [1.0, 1.2, 1.5, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.7]


def coil_current(La, Ra, Ca, Rq, C1, C2, L0, C0, tvdd, r_driver=2.0):
    """Peak current in the loop for a full-swing square-wave drive."""
    v = 4 / math.pi * tvdd / 2                      # half circuit
    zc0, zc1, zc2 = 1 / (1j * W * C0), 1 / (1j * W * C1), 1 / (1j * W * C2)
    zcoil = Ra / 2 + 1j * W * La / 2
    za = par(zcoil, 1 / (1j * W * 2 * Ca))
    zb = Rq + za
    zc = par(zb, zc2)
    zd = zc + zc1
    ze = par(zd, zc0)
    i_in = v / (ze + 1j * W * L0 + r_driver)
    i_coil = i_in * ze / zd * zc / zb * za / zcoil
    return abs(i_coil)


def field_on_axis(i_pk, z_mm, geo=None):
    """Rough rms field on the loop's axis, treating each turn as a circle of
    equal area."""
    geo = geo or LOOP
    pitch = geo["width"] + geo["space"]
    h = 0.0
    for k in range(geo["turns"]):
        a = (geo["outer_x"] - 2 * k * pitch) * (geo["outer_y"] - 2 * k * pitch) * 1e-6
        r = math.sqrt(a / math.pi)
        h += i_pk * r * r / (2 * (r * r + (z_mm * 1e-3) ** 2) ** 1.5)
    return h / math.sqrt(2)


def design(report=True):
    La, L_free, segs = loop_inductance(LOOP)
    Ra, length, delta = loop_resistance(LOOP, segs)
    C0 = sum(DESIGN["C0_pf"]) * 1e-12
    Rq, C1, C2 = solve_match(La, Ra, DESIGN["Ca"], DESIGN["Q"], DESIGN["Rmatch"], DESIGN["L0"], C0)
    c1 = best_pair(C1 * 1e12)
    c2 = best_pair(C2 * 1e12)
    rq_std = min(RQ_STOCK, key=lambda r: abs(r - Rq))
    z_real = z_diff(La, Ra, DESIGN["Ca"], rq_std, sum(c1) * 1e-12, sum(c2) * 1e-12, DESIGN["L0"], C0)
    out = dict(La=La, L_free=L_free, Ra=Ra, length=length, delta=delta, Rq=Rq, C1=C1, C2=C2,
               c1=c1, c2=c2, rq_std=rq_std, z=z_real, C0=C0)
    if not report:
        return out
    g = LOOP
    print("Face board loop: %.1f x %.1f mm, %d turns, %.2f mm track, %.2f mm gap, %.1f mm above main board copper"
          % (g["outer_x"], g["outer_y"], g["turns"], g["width"], g["space"], g["ground_gap_mm"]))
    print("  track length %.0f mm, skin depth %.1f um" % (length * 1e3, delta * 1e6))
    print("  inductance  %.0f nH in free space, %.0f nH over the main board" % (L_free * 1e9, La * 1e9))
    print("  resistance  about %.2f ohm at 13.56 MHz (estimate)" % Ra)
    print("  coil Q      about %.0f before damping" % (W * La / Ra))
    print()
    print("Matching (asymmetric, AN11740): target %.0f ohm between TX1 and TX2, Q %d" % (DESIGN["Rmatch"], DESIGN["Q"]))
    print("  EMC filter  L0 = 470 nH (TDK MLF2012DR47), C0 = %d + %d pF  -> cut-off %.1f MHz"
          % (DESIGN["C0_pf"][0], DESIGN["C0_pf"][1], 1 / (2 * math.pi * math.sqrt(DESIGN["L0"] * C0)) / 1e6))
    print("  calculated  Rq %.2f ohm, C1 %.1f pF, C2 %.1f pF (each side)" % (Rq, C1 * 1e12, C2 * 1e12))
    print("  fitted      Rq %.1f ohm, C1 = %s pF, C2 = %s pF" % (rq_std, " + ".join("%g" % v for v in c1 if v), " + ".join("%g" % v for v in c2 if v)))
    print("  result      Z(TX1-TX2) = %.1f %+.1fj ohm" % (z_real.real, z_real.imag))
    for tv in (3.5, 4.2, 4.7):
        print("  ITVDD       about %.0f mA at TVDD %.1f V" % (itvdd(z_real, tv) * 1e3, tv))
    i3 = coil_current(La, Ra, DESIGN["Ca"], rq_std, sum(c1) * 1e-12, sum(c2) * 1e-12, DESIGN["L0"], C0, 3.5)
    print("  loop current about %.0f mA peak at 3.5 V; field on axis %.0f A/m at 5 mm, %.1f A/m at 20 mm, %.1f A/m at 30 mm (rms)"
          % (i3 * 1e3, field_on_axis(i3, 5), field_on_axis(i3, 20), field_on_axis(i3, 30)))
    print("  ISO/IEC 15693 tags need at least 0.15 A/m. The tag sits 2 to 4 mm above the loop.")
    print()
    tolerance_sweep(out)
    return out


def tolerance_sweep(d, n=4000, seed=1):
    """Coil inductance +/-12 % (the estimate's uncertainty and the stack's
    tolerance), coil resistance +/-40 %, capacitors +/-1 % (C0G), L0 +/-5 %."""
    rnd = random.Random(seed)
    zs, cur, coil = [], [], []
    for _ in range(n):
        La = d["La"] * rnd.uniform(0.88, 1.12)
        Ra = d["Ra"] * rnd.uniform(0.6, 1.4)
        c1 = sum(d["c1"]) * 1e-12 * rnd.uniform(0.99, 1.01)
        c2 = sum(d["c2"]) * 1e-12 * rnd.uniform(0.99, 1.01)
        c0 = d["C0"] * rnd.uniform(0.99, 1.01)
        l0 = DESIGN["L0"] * rnd.uniform(0.95, 1.05)
        ca = DESIGN["Ca"] * rnd.uniform(0.5, 2.0)
        z = z_diff(La, Ra, ca, d["rq_std"], c1, c2, l0, c0)
        zs.append(abs(z))
        cur.append(itvdd(z, 4.7))
        coil.append(coil_current(La, Ra, ca, d["rq_std"], c1, c2, l0, c0, 3.5))
    zs.sort(); cur.sort(); coil.sort()
    p = lambda a, q: a[int(q * (len(a) - 1))]
    print("Tolerance sweep, %d runs (coil L +/-12 %%, R +/-40 %%, Ca x0.5..2, C0G +/-1 %%, L0 +/-5 %%):" % n)
    print("  |Z(TX1-TX2)|        5th..95th percentile %.0f..%.0f ohm" % (p(zs, 0.05), p(zs, 0.95)))
    print("  ITVDD at 4.7 V      5th..95th percentile %.0f..%.0f mA, worst %.0f mA (PN5180 limit 250 mA, inductors 200 mA)"
          % (p(cur, 0.05) * 1e3, p(cur, 0.95) * 1e3, cur[-1] * 1e3))
    print("  loop current, 3.5 V worst %.0f mA peak -> %.1f A/m at 20 mm (still far above 0.15 A/m)"
          % (coil[0] * 1e3, field_on_axis(coil[0], 20)))
    return dict(itvdd_worst=cur[-1], coil_worst=coil[0])


if __name__ == "__main__":
    ok, Rq, C1, C2 = check_against_nxp()
    print("Solver check against AN11740 worked example: Rq %.2f ohm, C1 %.1f pF, C2 %.1f pF -> %s"
          % (Rq, C1 * 1e12, C2 * 1e12, "agrees" if ok else "DISAGREES"))
    if "--check" in sys.argv:
        sys.exit(0 if ok else 1)
    print()
    design()
