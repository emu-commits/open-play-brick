#!/usr/bin/env python3
"""Build the brick board's two circuit boards in KiCad from design.py.

Run with KiCad's Python (it needs the pcbnew module):

    /usr/bin/python3 gen_board.py place    # place parts, write ../kicad/*.kicad_pcb (unrouted)
    /usr/bin/python3 gen_board.py route [face|main]   # route with the built-in maze router (router.py)
    /usr/bin/python3 gen_board.py freeroute [main]    # export DSN, run Freerouting, import, fill zones
    /usr/bin/python3 gen_board.py check    # DRC and connectivity report

The face board is routed with route; the main board, which is too dense for
the maze router, with freeroute. Freerouting 2.2 needs Java 25 or later; set
FREEROUTING_JAR and JAVA if they are not in the default places.

Everything about where parts sit is in PLACEMENT below, in board coordinates
in mm with (0, 0) at the corner of each board nearest the USB socket, x along
the brick and y across it, seen from above. Bottom-side parts are given in the
same top view.
"""
import math
import os
import re
import subprocess
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import design  # noqa: E402
import nfc_antenna  # noqa: E402

LIB = os.path.join(ROOT, "lib", "lcsc.pretty")
KICAD_FP = "/usr/share/kicad/footprints"
OUT = os.path.join(ROOT, "kicad")
# Freerouting: a jar run with JAVA, or (FREEROUTING) the launcher from a
# freerouting-*-linux-x64 release, which bundles its own Java. tools/kicad.sh
# mounts that release at /opt/freerouting and sets FREEROUTING.
FREEROUTING = os.environ.get("FREEROUTING") or os.environ.get("FREEROUTING_JAR", "/opt/freerouting/freerouting-2.2.4-executable.jar")
JAVA = os.environ.get("JAVA", "/usr/lib/jvm/java-25-openjdk-amd64/bin/java")

OX, OY = 100.0, 100.0          # KiCad page offset of each board's origin
MAIN_W, MAIN_H = 45.4, 13.4
FACE_W, FACE_H = 24.4, 13.4
FACE_X = 15.8                  # face board origin in main board coordinates
ANT_KEEPOUT_X = 40.0           # main board: no copper beyond this x (module antenna)
NOTCH = (17.4, 19.6, 1.6)      # main board edge notch for the battery wires: x0, x1, depth
MAIN_LAYERS = int(os.environ.get("MAIN_LAYERS", "6"))   # copper layers on the main board: 6 (4 left 33 open)
FANOUT = 0.8                   # main board: clear ring round U6 (PN5180) for its pads to escape

mm = pcbnew.FromMM


def P(x, y):
    return pcbnew.VECTOR2I(mm(OX + x), mm(OY + y))


# ---------------------------------------------------------------------------
# Placement: ref -> (x, y, rotation in degrees). See the module docstring.
# ---------------------------------------------------------------------------
PLACEMENT = {
    # ---- main board: parts placed by hand, (x, y, rotation, side) ------------
    "J1": (3.9, 6.7, 270, "T"),   # USB-C, mouth flush with the outside of the end wall
    # JST-SH sockets: the plug goes in on the side of the two large mounting
    # pads (footprint +y), so at 90 degrees on top it enters from +x.
    "J2": (10.6, 3.4, 90, "T"),   # battery; plug enters from +x, wires drop through NOTCH
    "J3": (10.6, 6.7, 90, "B"),   # speaker; plug enters from -x, wires drop to the speaker bay
    "U6": (23.4, 7.0, 0, "T"),    # PN5180; TX pins at the top right corner
    # The reader's EMC filter coils, VMID capacitor and receiver taps, by hand
    # in the strip between its TX/RX side and the module's fan-out vias, each
    # a short stub from its pin. The placer scattered them past the vias, and
    # neither router could get the pins out (13 to 17 connections open).
    "L1": (28.2, 2.6, 0, "T"),    # TX1 (pin 21, top right corner) -> TX1F; clear of U1.24's fan-out via
    "L2": (28.6, 4.5, 0, "T"),    # TX2 (pin 18) -> TX2F
    "C19": (28.0, 6.0, 0, "T"),   # VMID (pin 17)
    "R11": (28.0, 6.75, 0, "T"),  # RXP (pin 16) -> RXP_C
    "R12": (28.0, 7.5, 0, "T"),   # RXN (pin 15) -> RXN_C
    "C13": (21.15, 2.45, 90, "T"),  # V1V8 (pins 28-30), straight above them: placed by the
    "C12": (22.15, 2.45, 90, "T"),  # placer, the VSYS capacitors took this spot and V1V8 stayed open
    "C14": (23.65, 2.45, 90, "T"),  # VDHF (pin 25), likewise
    "U9": (18.0, 11.9, 0, "T"),   # accelerometer: on the free top side left of the reader; under the
                                  # board beside the module's pads it boxed in its own nets
    "J4": (36.2, 6.7, 0, "T"),    # to the face board
    "U1": (34.4, 6.7, 90, "B"),   # module; body x 28.8..45.4, antenna at +x
    # ---- face, top ----------------------------------------------------------
    # Pixels in two rows, a ring 1-2-3-4 / 8-7-6-5. The colour sensor and its
    # lamp sit on the centre line, under windows between the studs (top wall
    # holes at brick x 32 and 28, y 8).
    "ANT1": (0.0, 0.0, 0),
    # Rotated so each pixel's data out (pad 1) faces the next one's data in.
    "LED1": (6.8, 4.0, 180), "LED2": (10.2, 4.0, 180), "LED3": (16.4, 4.0, 180), "LED4": (19.8, 4.0, 180),
    "LED5": (19.8, 9.4, 0), "LED6": (16.4, 9.4, 0), "LED7": (10.2, 9.4, 0), "LED8": (6.8, 9.4, 0),
    "U20": (15.0, 6.8, 0), "LED9": (11.0, 6.8, 0),
    # ---- face, bottom -------------------------------------------------------
    "J5": (20.4, 6.7, 0, "B"),
}


# Main board, placed by autoplace.py in this order: ref -> (anchor ref, anchor
# pad, sides to try). Each part goes as close as it can to its anchor pad.
T, B = "T", "B"
AUTO_MAIN = [
    # larger parts first, so the small ones fill in around them
    ("Y1", "U6", "36", T),
    ("U7", "J3", "1", B),
    ("U2", "J1", "A6", B + T), ("D1", "J1", "A4B9", T + B),
    ("U3", "J2", "2", T + B), ("Q1", "J2", "2", T + B), ("U4", "Q1", "2", T + B),
    ("Q2", "J4", "6", B + T), ("Q3", "Q2", "1", B + T),
    # NFC frontend passives, top
    ("C16", "U6", "22", T), ("C17", "U6", "22", T), ("C15", "U6", "26", T),
    ("C18", "U6", "6", T),
    ("R10", "U6", "10", T),
    # TX1F/TX2F filter and coupling capacitors beside the header pins they feed
    ("C24", "J4", "2", T), ("C20", "J4", "2", T), ("C21", "J4", "2", T),
    ("C25", "J4", "1", T), ("C22", "J4", "1", T), ("C23", "J4", "1", T), ("C10", "Y1", "1", T), ("C11", "Y1", "3", T),
    # module support
    ("C1", "U1", "3", T + B), ("C2", "U1", "3", T + B), ("R1", "U1", "8", B + T), ("C3", "U1", "8", B + T),
    ("R2", "U1", "22", B + T), ("JP1", "U1", "23", B + T),
    # power passives
    ("R4", "J1", "A5", B + T), ("R5", "J1", "B5", B + T),
    ("C4", "U3", "4", T + B), ("R7", "U3", "5", T + B), ("C5", "U3", "3", T + B), ("R6", "Q1", "1", T + B),
    ("C6", "U4", "1", T + B), ("C8", "U4", "5", T + B),
    ("R18", "U1", "9", B + T), ("R19", "R18", "2", B + T), ("C31", "R18", "2", B + T),
    # audio, sensors, switches
    ("C26", "U7", "7", B + T), ("C27", "U7", "8", B + T), ("C29", "U9", "9", B + T),
    ("R8", "J4", "7", B + T), ("R9", "J4", "8", B + T),
    ("R15", "Q2", "1", B + T), ("R16", "Q3", "1", B + T), ("U10", "J4", "9", B + T), ("C30", "U10", "5", B + T),
    ("R17", "U10", "4", B + T),
]
# Face board: matching network beside the loop terminals on the bottom;
# pixel decoupling on top beside each pixel's supply pin, so it needs no via.
# The face placer keeps 0.3 mm around each part (the main board's 0.12 mm
# left pads boxed in, with no room for a track or a via).
AUTO_FACE = [
    ("R30", "ANT1", "1", B), ("C42", "R30", "1", B), ("C43", "R30", "1", B), ("C40", "R30", "1", B), ("C41", "R30", "1", B),
    ("R31", "ANT1", "2", B), ("C46", "R31", "1", B), ("C47", "R31", "1", B), ("C44", "R31", "1", B), ("C45", "R31", "1", B),
    ("C50", "LED1", "4", T + B), ("C51", "LED4", "4", T + B), ("C52", "LED6", "4", T + B), ("C53", "LED8", "4", T + B),
    ("C54", "J5", "6", B), ("C55", "U20", "1", B), ("R32", "LED9", "2", B),
]

# Areas the placer must leave empty (board mm, x0, y0, x1, y1, side).
KEEPOUT_MAIN = [
    (13.2, 1.0, 19.8, 5.8, "T"),     # the battery plug and its wires, partly under the face board
    (3.4, 4.6, 8.0, 8.8, "B"),       # the speaker plug, over the speaker bay
    (ANT_KEEPOUT_X - 0.2, 0, MAIN_W, MAIN_H, "both"),   # module antenna
    (NOTCH[0] - 0.3, 0, NOTCH[1] + 0.3, NOTCH[2] + 0.3, "both"),   # battery wire notch
    (29.95, 0.3, 31.35, 13.1, "both"),  # the module's side-column fan-out vias (fanout_module)
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_fp(name):
    if ":" in name:
        lib, fp = name.split(":")
        f = pcbnew.FootprintLoad(os.path.join(KICAD_FP, lib + ".pretty"), fp)
    else:
        f = pcbnew.FootprintLoad(LIB, name)
    if f is None:
        raise RuntimeError("footprint not found: " + name)
    f.Models().clear()
    return f


def net(board, name, cache):
    if name not in cache:
        n = pcbnew.NETINFO_ITEM(board, name)
        board.Add(n)
        cache[name] = n
    return cache[name]


def outline(board, pts, layer=pcbnew.Edge_Cuts, width=0.1):
    for a, b in zip(pts, pts[1:] + pts[:1]):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(P(*a))
        s.SetEnd(P(*b))
        s.SetLayer(layer)
        s.SetWidth(mm(width))
        board.Add(s)


def circle_hole(board, x, y, d):
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(pcbnew.SHAPE_T_CIRCLE)
    s.SetCenter(P(x, y))
    s.SetEnd(P(x + d / 2, y))
    s.SetLayer(pcbnew.Edge_Cuts)
    s.SetWidth(mm(0.1))
    board.Add(s)


def zone(board, pts, layer, netinfo=None, keepout=None, priority=0, name=None):
    z = pcbnew.ZONE(board)
    z.SetLayer(layer)
    o = z.Outline()
    o.NewOutline()
    for x, y in pts:
        o.Append(mm(OX + x), mm(OY + y))
    if keepout:
        z.SetIsRuleArea(True)
        z.SetDoNotAllowTracks("tracks" in keepout)
        z.SetDoNotAllowVias("vias" in keepout)
        z.SetDoNotAllowCopperPour("pour" in keepout)
        z.SetDoNotAllowPads("pads" in keepout)
        z.SetDoNotAllowFootprints("footprints" in keepout)
        if layer == "all":
            pass
    else:
        z.SetNet(netinfo)
        z.SetAssignedPriority(priority)
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetThermalReliefGap(mm(0.2))
        z.SetThermalReliefSpokeWidth(mm(0.25))
        z.SetLocalClearance(mm(0.2))
        z.SetMinThickness(mm(0.2))
    if name:
        z.SetZoneName(name)
    board.Add(z)
    return z


def keepout_all_layers(board, pts, what, name):
    z = pcbnew.ZONE(board)
    ls = pcbnew.LSET()
    for l in copper_layers(board):
        ls.AddLayer(l)
    z.SetLayerSet(ls)
    o = z.Outline()
    o.NewOutline()
    for x, y in pts:
        o.Append(mm(OX + x), mm(OY + y))
    z.SetIsRuleArea(True)
    z.SetDoNotAllowTracks("tracks" in what)
    z.SetDoNotAllowVias("vias" in what)
    z.SetDoNotAllowCopperPour("pour" in what)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowFootprints(False)
    z.SetZoneName(name)
    board.Add(z)


def setup_rules(board):
    ds = board.GetDesignSettings()
    ds.m_TrackMinWidth = mm(0.1)        # JLCPCB multilayer minimum is 0.09 mm; Freerouting necks to ~0.11 at the USB-C pads
    ds.m_ViasMinSize = mm(0.45)
    ds.m_ViasMinDrill = mm(0.25)
    ds.m_MinThroughDrill = mm(0.25)
    ds.m_CopperEdgeClearance = mm(0.25)
    ds.m_MinClearance = mm(0.09)       # floor for the USB-C rule; net classes ask 0.127 and more
    ds.m_HoleClearance = mm(0.2)
    nc = ds.m_NetSettings.GetDefaultNetclass()
    nc.SetClearance(mm(0.127))
    nc.SetTrackWidth(mm(0.15))
    nc.SetViaDiameter(mm(0.5))
    nc.SetViaDrill(mm(0.3))
    power = pcbnew.NETCLASS("Power")
    power.SetClearance(mm(0.127))
    # 0.2 mm: wide enough for the 0.5 A peaks here, narrow enough to reach the
    # 0.25 mm pads of the 0.5 mm-pitch chips (Freerouting will not neck down a
    # power track, and at 0.3 mm left every supply pin of U6, U7 and U9 open).
    power.SetTrackWidth(mm(0.2))
    power.SetViaDiameter(mm(0.6))
    power.SetViaDrill(mm(0.3))
    ds.m_NetSettings.SetNetclass("Power", power)
    rf = pcbnew.NETCLASS("NFC")
    rf.SetClearance(mm(0.127))
    rf.SetTrackWidth(mm(0.25))
    rf.SetViaDiameter(mm(0.6))
    rf.SetViaDrill(mm(0.3))
    ds.m_NetSettings.SetNetclass("NFC", rf)
    for pat in ("VSYS", "VBUS", "VBAT", "3V3", "VLED", "GND", "SPK_P", "SPK_N"):
        ds.m_NetSettings.SetNetclassPatternAssignment(pat, "Power")
    for pat in ("TX1", "TX2", "TX1F", "TX2F", "MA1", "MB1", "ANT_A", "ANT_B"):
        ds.m_NetSettings.SetNetclassPatternAssignment(pat, "NFC")


def place(board, p, nets, positioned=True):
    f = load_fp(p["footprint"])
    f.SetReference(p["ref"])
    f.SetValue(p["value"])
    f.SetFPID(pcbnew.LIB_ID("lcsc" if ":" not in p["footprint"] else p["footprint"].split(":")[0],
                            p["footprint"].split(":")[-1]))
    board.Add(f)
    if positioned:
        spec = PLACEMENT[p["ref"]]
        x, y, rot = spec[:3]
        side = spec[3] if len(spec) > 3 else ("B" if p["side"] == "bottom" else "T")
        f.SetPosition(P(x, y))
        f.SetOrientationDegrees(rot)
        if side == "B":
            f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
    if p["lcsc"]:
        f.SetField("LCSC", p["lcsc"]) if hasattr(f, "SetField") else None
    for pad in f.Pads():
        if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH and pad.GetNumber() == "":
            ds_ = pad.GetDrillSize()
            sz = pad.GetSize(pcbnew.F_Cu) if hasattr(pad, "GetSize") else pad.GetSize()
            if sz.x <= ds_.x + mm(0.05) and sz.y <= ds_.y + mm(0.05):
                pad.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
                ls = pcbnew.LSET()
                for l in (pcbnew.F_Cu, pcbnew.B_Cu, pcbnew.F_Mask, pcbnew.B_Mask):
                    ls.AddLayer(l)
                pad.SetLayerSet(ls)
    used = set()
    for pad in f.Pads():
        num = pad.GetNumber()
        if num == "" or pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
            if p["ref"] == "U1" and pad.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH:
                pad.SetNet(net(board, "GND", nets))
            continue
        if num not in p["pins"]:
            raise RuntimeError("%s pad %s has no net in design.py" % (p["ref"], num))
        pad.SetNet(net(board, p["pins"][num], nets))
        used.add(num)
    missing = set(p["pins"]) - used
    if missing:
        raise RuntimeError("%s: design.py names pads the footprint lacks: %s" % (p["ref"], sorted(missing)))
    # Silkscreen reference: small, or hidden on dense boards.
    ref = f.Reference()
    ref.SetTextSize(pcbnew.VECTOR2I(mm(0.5), mm(0.5)))
    ref.SetTextThickness(mm(0.08))
    ref.SetVisible(False)
    f.Value().SetVisible(False)
    for fld in f.GetFields():
        if not fld.IsReference():
            fld.SetVisible(False)
    for g in list(f.GraphicalItems()):
        if g.GetClass() in ("PCB_TEXT", "FP_TEXT") and g.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS, pcbnew.F_Fab, pcbnew.B_Fab):
            f.Remove(g)
    return f


def nfc_loop_footprint(board, nets, x0, y0):
    """The printed loop as a net-tie footprint: two pads, copper between."""
    g = nfc_antenna.LOOP
    f = pcbnew.FOOTPRINT(board)
    f.SetReference("ANT1")
    f.SetValue("NFC loop")
    f.SetFPID(pcbnew.LIB_ID("brick", "NFC_LOOP_%dT" % g["turns"]))
    board.Add(f)
    f.SetPosition(P(0, 0))
    segs = nfc_antenna.spiral_segments(g["outer_x"], g["outer_y"], g["turns"], g["width"], g["space"])
    start = segs[0][0]
    end = segs[-1][1]
    lead_end = (start[0] - 0.31, start[1])
    # One filled polygon for the whole loop and its lead: KiCad's net-tie check
    # accepts copper that joins the tied pads only as a single shape.
    poly = pcbnew.SHAPE_POLY_SET()
    for (a, b) in segs + [(start, lead_end)]:
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(P(x0 + a[0], y0 + a[1]))
        t.SetEnd(P(x0 + b[0], y0 + b[1]))
        t.SetWidth(mm(g["width"]))
        piece = pcbnew.SHAPE_POLY_SET()
        t.TransformShapeToPolygon(piece, pcbnew.F_Cu, 0, mm(0.002), pcbnew.ERROR_INSIDE)
        poly.BooleanAdd(piece)
    poly.Simplify()
    shp = pcbnew.PCB_SHAPE(f)
    shp.SetShape(pcbnew.SHAPE_T_POLY)
    shp.SetPolyShape(poly)
    shp.SetFilled(True)
    shp.SetWidth(0)
    shp.SetLayer(pcbnew.F_Cu)
    f.Add(shp)
    # Terminals. Each is a pad holding a via; the loop copper reaches into the
    # pad but stays 0.15 mm clear of the via, which keeps DRC's net-tie rules
    # (copper may touch the tied pads, not other items) satisfied.
    p1 = (start[0] - 0.79, start[1])
    p2 = (end[0] + 0.5, end[1])
    for num, (px, py), netname, d in (("1", p1, "ANT_A", 0.92), ("2", p2, "ANT_B", 1.0)):
        pad = pcbnew.PAD(f)
        pad.SetNumber(num)
        pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
        pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        ls = pcbnew.LSET()
        ls.AddLayer(pcbnew.F_Cu)
        ls.AddLayer(pcbnew.F_Mask)
        pad.SetLayerSet(ls)
        pad.SetSize(pcbnew.VECTOR2I(mm(d), mm(d)))
        pad.SetPosition(P(x0 + px, y0 + py))
        pad.SetNet(net(board, netname, nets))
        f.Add(pad)
    start, end = p1, p2
    f.AddNetTiePadGroup("1,2")
    f.SetAttributes(pcbnew.FP_EXCLUDE_FROM_POS_FILES | pcbnew.FP_EXCLUDE_FROM_BOM)
    f.Reference().SetVisible(False)
    f.Value().SetVisible(False)
    return f, (x0 + start[0], y0 + start[1]), (x0 + end[0], y0 + end[1])


def add_track(board, nets, netname, pts, width, layer):
    for a, b in zip(pts, pts[1:]):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(P(*a))
        t.SetEnd(P(*b))
        t.SetWidth(mm(width))
        t.SetLayer(layer)
        t.SetNet(net(board, netname, nets))
        t.SetLocked(True)
        board.Add(t)


def add_via(board, nets, netname, x, y, d=0.5, drill=0.3, locked=True, net_obj=None):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(P(x, y))
    v.SetWidth(mm(d))
    v.SetDrill(mm(drill))
    v.SetNet(net_obj if net_obj is not None else net(board, netname, nets))
    v.SetLocked(locked)
    board.Add(v)
    return v


def check_gpio_against_firmware():
    pins_h = open(os.path.join(ROOT, "..", "..", "firmware", "core", "pins.h")).read()
    fw = {m.group(1): int(m.group(2)) for m in re.finditer(r"#define PIN_(\w+)\s+(\d+)", pins_h)}
    bad = [(k, v, fw.get(k)) for k, v in design.GPIO.items() if fw.get(k) != v]
    if bad:
        raise SystemExit("GPIO numbers differ from firmware/core/pins.h: %s" % bad)


# ---------------------------------------------------------------------------
# Boards
# ---------------------------------------------------------------------------

def copper_layers(board):
    n = board.GetCopperLayerCount()
    return [pcbnew.F_Cu] + [getattr(pcbnew, "In%d_Cu" % i) for i in range(1, n - 1)] + [pcbnew.B_Cu]


def new_board(layers=4):
    b = pcbnew.CreateEmptyBoard()
    b.SetCopperLayerCount(layers)
    ds = b.GetDesignSettings()
    ds.SetBoardThickness(mm(0.8))
    ds.SetAuxOrigin(P(0, 0))       # Gerbers, drill and placement files measured from the board corner
    setup_rules(b)
    return b


def fanout_module(b, via=(0.45, 0.25), width=0.2, clearance=0.15):
    """A via under the module for each signal pad on its two long sides,
    joined by a short stub on the bottom layer. The module is 13.2 mm wide on
    a 13.4 mm board, so those pads sit 0.4 mm from the edge and can only
    escape inward, and Freerouting will not place vias under a part by
    itself: left to it, nearly every one of them stayed open."""
    u1 = b.FindFootprintByReference("U1")
    cx, cy = pcbnew.ToMM(u1.GetPosition().x) - OX, pcbnew.ToMM(u1.GetPosition().y) - OY
    obstacles = []      # (x, y, half-w, half-h, net, on the bottom layer) of every pad and via
    for f in b.GetFootprints():
        for p in f.Pads():
            bb = p.GetBoundingBox()
            obstacles.append(((pcbnew.ToMM(bb.GetLeft() + bb.GetRight()) / 2) - OX,
                              (pcbnew.ToMM(bb.GetTop() + bb.GetBottom()) / 2) - OY,
                              pcbnew.ToMM(bb.GetWidth()) / 2, pcbnew.ToMM(bb.GetHeight()) / 2, p.GetNetname(),
                              p.IsOnLayer(pcbnew.B_Cu)))
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA":
            r = pcbnew.ToMM(t.GetWidth(pcbnew.F_Cu)) / 2
            obstacles.append((pcbnew.ToMM(t.GetPosition().x) - OX, pcbnew.ToMM(t.GetPosition().y) - OY, r, r, t.GetNetname(), True))
    vr = via[0] / 2

    def free(x, y, netname, r=None):
        stub = r is not None        # a bottom-layer stub: only bottom-layer copper is in its way
        r = vr if r is None else r
        for ox, oy, hw, hh, n, on_b in obstacles:
            if n == netname or (stub and not on_b):
                continue
            dx = max(abs(x - ox) - hw, 0)
            dy = max(abs(y - oy) - hh, 0)
            if math.hypot(dx, dy) < r + clearance:
                return False
        return True

    made = 0
    for p in sorted(u1.Pads(), key=lambda p: p.GetNumber()):
        n = p.GetNetname()
        if not n or n == "GND" or n.startswith("NC_") or p.GetNumber() == "":
            continue
        px, py = pcbnew.ToMM(p.GetPosition().x) - OX, pcbnew.ToMM(p.GetPosition().y) - OY
        bb = p.GetBoundingBox()
        w, h = pcbnew.ToMM(bb.GetWidth()), pcbnew.ToMM(bb.GetHeight())
        if w > h:
            # The side column's vias go inward, under the module, between its
            # signal pads and its centre ground pads, staggered in two columns
            # by pad row. Outward, beside the module, they took the strip the
            # NFC reader's filter and receiver parts need. In a single column
            # 0.8 mm apart they left 0.35 mm between vias, less than any track
            # needs: a wall on every layer. Staggered, each diagonal gap is
            # about 0.68 mm, room for one track per layer.
            ux, uy, half = (1 if cx > px else -1), 0, w / 2
            depths = (1.25, 1.45, 0.55, 0.85) if round((py - cy) / 0.8) % 2 else (0.55, 0.85, 1.25, 1.45)
        else:
            ux, uy, half = 0, (1 if cy > py else -1), h / 2
            depths = (0.55, 0.85, 1.15, 1.45, 1.75)
        for d, side in [(d, sd) for d in depths for sd in (0, 0.45, -0.45)]:
            # inward by d, and sideways by sd when the straight spot is taken
            vx = px + ux * (half + d - 0.25) + uy * side
            vy = py + uy * (half + d - 0.25) + ux * side
            # the via, and the stub to it, which crosses the pad's neighbours' vias
            steps = max(2, int(math.hypot(vx - px, vy - py) / 0.05))
            if free(vx, vy, n) and all(free(px + (vx - px) * k / steps, py + (vy - py) * k / steps, n, width / 2)
                                       for k in range(steps + 1)):
                break
        else:
            print("  fanout: no room for a via at U1.%s (%s)" % (p.GetNumber(), n))
            continue
        t = pcbnew.PCB_TRACK(b)
        t.SetStart(P(px, py))
        t.SetEnd(P(vx, vy))
        t.SetWidth(mm(width))
        t.SetLayer(pcbnew.B_Cu)
        t.SetNet(p.GetNet())
        t.SetLocked(True)
        b.Add(t)
        add_via(b, {}, None, vx, vy, via[0], via[1], net_obj=p.GetNet())
        obstacles.append((vx, vy, vr, vr, n, True))
        made += 1
    print("  fanout: %d module pads given a via" % made)


def fanout_reader(b):
    """Fixed escapes for the PN5180's supply and ground pins and C19's
    ground, laid before any routing. Left to the routers, the signal pins on
    each side of them took the room first: 3V3 (pin 6, between two SPI
    pins), VSYS (pins 12 and 13) and C19's ground pad stayed open."""
    u6 = b.FindFootprintByReference("U6")
    def pad(ref, num):
        p = b.FindFootprintByReference(ref).FindPadByNumber(num)
        return p, pcbnew.ToMM(p.GetPosition().x) - OX, pcbnew.ToMM(p.GetPosition().y) - OY
    def stub(p, pts, width, layer=pcbnew.F_Cu):
        for a, c in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(b)
            t.SetStart(P(*a))
            t.SetEnd(P(*c))
            t.SetWidth(mm(width))
            t.SetLayer(layer)
            t.SetNet(p.GetNet())
            t.SetLocked(True)
            b.Add(t)
    ep, ex, ey = pad("U6", "41")
    half = pcbnew.ToMM(ep.GetSize().x) / 2
    # ground pins: a stub inward to the exposed pad (which has its own via)
    for num in ("4", "9", "19", "27"):
        p, x, y = pad("U6", num)
        if abs(y - ey) > abs(x - ex):     # top or bottom row
            stub(p, [(x, y), (x, ey + math.copysign(half - 0.1, y - ey))], 0.2)
        else:
            stub(p, [(x, y), (ex + math.copysign(half - 0.1, x - ex), y)], 0.2)
    # 3V3, pin 6: straight down to a via; the SPI pins either side pass it
    p, x, y = pad("U6", "6")
    stub(p, [(x, y), (x, y + 0.95)], 0.2)
    add_via(b, {}, None, x, y + 0.95, 0.45, 0.25, net_obj=p.GetNet())
    # VSYS, pins 12 and 13: joined, with a via between them (filled and
    # capped, JLCPCB's default on 6 layers)
    p12, x12, y12 = pad("U6", "12")
    p13, x13, y13 = pad("U6", "13")
    stub(p12, [(x12, y12), (x12, y13)], 0.2)
    add_via(b, {}, None, x12, (y12 + y13) / 2, 0.45, 0.25, net_obj=p12.GetNet())
    # C19's ground pad: boxed in by VMID, the RXP tap and L2, with the
    # module's pads under the board beside it; a via in the corner between
    p, x, y = pad("C19", "2")
    stub(p, [(x, y), (x + 0.32, y - 0.5)], 0.2)
    add_via(b, {}, None, x + 0.32, y - 0.5, 0.45, 0.25, net_obj=p.GetNet())


def build_main():
    import autoplace
    b = new_board(MAIN_LAYERS)
    nets = {}
    by_ref = {p["ref"]: p for p in design.parts("main")}
    for ref in PLACEMENT:
        if ref in by_ref:
            place(b, by_ref[ref], nets)
    # Thermal vias in exposed pads, ground vias in the module's centre pads.
    def ep_vias(ref, padnum, offsets):
        pad = b.FindFootprintByReference(ref).FindPadByNumber(padnum)
        cx, cy = pcbnew.ToMM(pad.GetPosition().x) - OX, pcbnew.ToMM(pad.GetPosition().y) - OY
        for dx, dy in offsets:
            add_via(b, {}, None, cx + dx, cy + dy, 0.45, 0.25, net_obj=pad.GetNet())
    ep_vias("U6", "41", [(0, 0)])   # one via: the reader dissipates about 0.15 W here
    u1 = b.FindFootprintByReference("U1")
    for pad in [p for p in u1.Pads() if p.GetNumber() == "" and pcbnew.ToMM(p.GetSize().x) > 1.0]:
        add_via(b, {}, None, pcbnew.ToMM(pad.GetPosition().x) - OX, pcbnew.ToMM(pad.GetPosition().y) - OY,
                0.45, 0.25, net_obj=pad.GetNet())
    fanout_module(b)
    fanout_reader(b)
    pl = autoplace.Placer(b, (OX, OY), (MAIN_W, MAIN_H), margin=0.2)
    for f in b.GetFootprints():
        pl.block_footprint(f)
    pl.block_vias()
    for x0, y0, x1, y1, side in KEEPOUT_MAIN:
        pl.block_rect(side, x0, y0, x1, y1)
    # Fan-out ring round the NFC reader's 0.5 mm-pitch pads: room for each pad
    # to leave on a track and drop a via. Packed tight against the chip, its
    # support parts walled several pads into pockets that no route could leave.
    bb = b.FindFootprintByReference("U6").GetBoundingBox(False)
    pl.block_rect("T", pcbnew.ToMM(bb.GetLeft()) - OX - FANOUT, pcbnew.ToMM(bb.GetTop()) - OY - FANOUT,
                  pcbnew.ToMM(bb.GetRight()) - OX + FANOUT, pcbnew.ToMM(bb.GetBottom()) - OY + FANOUT)
    for ref, aref, apad, sides in AUTO_MAIN:
        f = place(b, by_ref[ref], nets, positioned=False)
        ap = b.FindFootprintByReference(aref).FindPadByNumber(apad)
        axy = (pcbnew.ToMM(ap.GetPosition().x) - OX, pcbnew.ToMM(ap.GetPosition().y) - OY)
        res = pl.place(f, axy, ap.GetNetname(), list(sides))
        if res is None:
            try:
                from PIL import Image
                import numpy as np
                img = np.concatenate([pl.occ["T"], np.ones((5, pl.nx), bool), pl.occ["B"][:, ::-1]], 0)
                Image.fromarray((~img * 255).astype("uint8")).resize((pl.nx * 4, img.shape[0] * 4)).save(
                    os.path.join(OUT, "placer-occupancy.png"))
            except Exception as e:
                print(e)
            raise SystemExit("no room for %s near %s.%s" % (ref, aref, apad))
        PLACEMENT[ref] = (res[1], res[2], res[3], res[0])
        print("  placed %-4s %s (%.1f, %.1f) rot %d  anchor %s.%s" % (ref, res[0], res[1], res[2], res[3], aref, apad))
        if ref == "U7":
            ep_vias(ref, "17", [(0, 0)])
            pl.block_vias()
    missing = set(by_ref) - set(PLACEMENT)
    if missing:
        raise SystemExit("not placed: %s" % sorted(missing))
    # Outline with a notch for the speaker wires (they rise from the speaker
    # bay to J3 under the board) and one for the battery wires.
    W, H = MAIN_W, MAIN_H
    nx0, nx1, nd = NOTCH
    outline(b, [(0, 0), (nx0, 0), (nx0, nd), (nx1, nd), (nx1, 0), (W, 0), (W, H), (0, H)])
    # GND pours: inner layer 1 solid, other layers flooded, all kept off the
    # module antenna's end.
    pour = [(0.3, 0.3), (nx0 - 0.3, 0.3), (nx0 - 0.3, nd + 0.3), (nx1 + 0.3, nd + 0.3), (nx1 + 0.3, 0.3),
            (ANT_KEEPOUT_X, 0.3), (ANT_KEEPOUT_X, H - 0.3), (0.3, H - 0.3)]
    g = net(b, "GND", nets)
    zone(b, pour, pcbnew.In1_Cu, g, priority=0, name="GND_IN1")
    zone(b, pour, pcbnew.B_Cu, g, priority=0, name="GND_B")
    zone(b, pour, pcbnew.F_Cu, g, priority=0, name="GND_F")
    # 3V3/VSYS on inner layer 2 would split it; leave In2 for signals with a
    # GND flood behind them.
    zone(b, pour, pcbnew.In2_Cu, g, priority=0, name="GND_IN2")
    if MAIN_LAYERS == 6:
        zone(b, pour, pcbnew.In3_Cu, g, priority=0, name="GND_IN3")
        zone(b, pour, pcbnew.In4_Cu, g, priority=0, name="GND_IN4")   # second solid plane
    keepout_all_layers(b, [(ANT_KEEPOUT_X, -0.5), (W + 0.5, -0.5), (W + 0.5, H + 0.5), (ANT_KEEPOUT_X, H + 0.5)],
                       ("tracks", "vias", "pour"), "ANTENNA_KEEPOUT")
    # Edge strips: Freerouting keeps only its track clearance from the outline
    # and ran tracks 0.16 mm from the edge (JLCPCB wants 0.2, KiCad 0.25).
    e = 0.32
    for i, r in enumerate([(-0.5, -0.5, ANT_KEEPOUT_X, e), (-0.5, H - e, ANT_KEEPOUT_X, H + 0.5), (-0.5, -0.5, e, H + 0.5),
                           (nx0 - e, -0.5, nx1 + e, nd + e)]):
        x0, y0, x1, y1 = r
        keepout_all_layers(b, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], ("tracks", "vias"), "EDGE_%d" % i)
    silk_labels(b)
    return b


def build_face():
    import autoplace
    b = new_board()
    nets = {}
    g = nfc_antenna.LOOP
    lx = 1.45                      # room on the left for the outer terminal's via
    ly = (FACE_H - g["outer_y"]) / 2
    by_ref = {p["ref"]: p for p in design.parts("face")}
    _, a_pt, b_pt = nfc_loop_footprint(b, nets, lx, ly)
    add_via(b, nets, "ANT_A", a_pt[0], a_pt[1], 0.45, 0.25)
    add_via(b, nets, "ANT_B", b_pt[0], b_pt[1], 0.45, 0.25)
    for ref in PLACEMENT:
        if ref in by_ref and ref != "ANT1":
            place(b, by_ref[ref], nets)
    pl = autoplace.Placer(b, (OX, OY), (FACE_W, FACE_H), margin=0.3)
    for f in b.GetFootprints():
        if f.GetReference() != "ANT1":
            pl.block_footprint(f)
    pl.block_vias()
    # keep bottom parts inside the loop's opening, clear of its turns
    pitch = g["width"] + g["space"]
    band = g["turns"] * pitch + 0.2
    x0, y0, x1, y1 = lx, ly, lx + g["outer_x"], ly + g["outer_y"]
    for r in ((0, 0, FACE_W, y0 + band), (0, y1 - band, FACE_W, FACE_H), (0, 0, x0 + band, FACE_H), (x1 - band, 0, FACE_W, FACE_H)):
        pl.block_rect("B", *r)
    for ref, aref, apad, sides in AUTO_FACE:
        f = place(b, by_ref[ref], nets, positioned=False)
        ap = b.FindFootprintByReference(aref).FindPadByNumber(apad)
        axy = (pcbnew.ToMM(ap.GetPosition().x) - OX, pcbnew.ToMM(ap.GetPosition().y) - OY)
        res = pl.place(f, axy, ap.GetNetname(), list(sides))
        if res is None:
            raise SystemExit("no room for %s near %s.%s" % (ref, aref, apad))
        PLACEMENT[ref] = (res[1], res[2], res[3], res[0])
        print("  placed %-4s %s (%.1f, %.1f) rot %d  anchor %s.%s" % (ref, res[0], res[1], res[2], res[3], aref, apad))
    outline(b, [(0, 0), (FACE_W, 0), (FACE_W, FACE_H), (0, FACE_H)])
    # Nothing but the loop may be copper on the inner layers, and nothing may
    # be poured anywhere: a pour inside the loop would short its field.
    keepout_all_layers(b, [(-0.5, -0.5), (FACE_W + 0.5, -0.5), (FACE_W + 0.5, FACE_H + 0.5), (-0.5, FACE_H + 0.5)],
                       ("pour",), "NO_POUR")
    for layer in (pcbnew.In1_Cu, pcbnew.In2_Cu):
        pass
    pitch = g["width"] + g["space"]
    ring_in = g["turns"] * pitch
    # Feeds: each loop end drops through a via and runs on the bottom layer
    # into the loop's middle, to its damping resistor.
    return b, nets, a_pt, b_pt, (lx, ly, ring_in)


DRU = """(version 1)
# The USB-C socket's own pads are 0.1 mm apart (HRO's land pattern). JLCPCB
# makes 0.09 mm gaps on outer layers.
(rule "USB-C land pattern"
  (constraint clearance (min 0.09mm))
  (condition "A.memberOfFootprint('J1') && B.memberOfFootprint('J1')"))
(rule "USB-C solder mask"
  (constraint solder_mask_sliver (min 0mm))
  (condition "A.memberOfFootprint('J1') || B.memberOfFootprint('J1')"))
"""


def save_board(path, b):
    """SaveBoard, then mark starved thermals as warnings in the project file
    (SaveBoard rewrites it with KiCad's defaults). A small pad on a pour that
    keeps one spoke where two do not fit is still connected."""
    import json
    pcbnew.SaveBoard(path, b)
    pro = path[:-len(".kicad_pcb")] + ".kicad_pro"
    try:
        d = json.load(open(pro))
    except (OSError, ValueError):
        return
    d.setdefault("board", {}).setdefault("design_settings", {}).setdefault("rule_severities", {})["starved_thermal"] = "warning"
    json.dump(d, open(pro, "w"), indent=2)


def save(b, name):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name + ".kicad_pcb")
    save_board(path, b)
    with open(os.path.join(OUT, name + ".kicad_dru"), "w") as fh:
        fh.write(DRU)
    pro = os.path.join(OUT, name + ".kicad_pro")
    if not os.path.exists(pro):
        with open(pro, "w") as fh:
            fh.write('{"meta": {"filename": "%s.kicad_pro", "version": 1}}\n' % name)
    return path


def header_alignment(main, face):
    j4 = {p.GetNumber(): (pcbnew.ToMM(p.GetPosition().x) - OX, pcbnew.ToMM(p.GetPosition().y) - OY, p.GetNetname())
          for p in main.FindFootprintByReference("J4").Pads()}
    j5 = {p.GetNumber(): (pcbnew.ToMM(p.GetPosition().x) - OX + FACE_X, pcbnew.ToMM(p.GetPosition().y) - OY, p.GetNetname())
          for p in face.FindFootprintByReference("J5").Pads()}
    errors = []
    # The pins sit 0.635 mm either side of the header's centre line; the SMD
    # pads run outwards from them, so compare columns and rows, not pad centres.
    c4 = sum(v[1] for v in j4.values()) / len(j4)
    c5 = sum(v[1] for v in j5.values()) / len(j5)
    for n4, (x4, y4, net4) in j4.items():
        mate = [n5 for n5, (x5, y5, _) in j5.items()
                if abs(x5 - x4) < 0.05 and (y5 - c5) * (y4 - c4) > 0 and abs(c5 - c4) < 0.05]
        if len(mate) != 1:
            errors.append("J4 pin %s has no socket contact above it" % n4)
        elif j5[mate[0]][2] != net4:
            errors.append("J4 pin %s (%s) meets J5 pad %s (%s)" % (n4, net4, mate[0], j5[mate[0]][2]))
    return errors


def courtyard_report(b, label):
    """Bounding boxes outside the board, and overlaps between parts on the same side."""
    edge = b.GetBoardEdgesBoundingBox()
    problems = []
    fps = list(b.GetFootprints())
    boxes = []
    for f in fps:
        side = "B" if f.IsFlipped() else "F"
        cy = f.GetCourtyard(pcbnew.B_CrtYd if f.IsFlipped() else pcbnew.F_CrtYd)
        if cy.OutlineCount() == 0:
            continue
        bb = cy.BBox()
        boxes.append((f.GetReference(), side, bb))
    for i, (r1, s1, b1) in enumerate(boxes):
        for r2, s2, b2 in boxes[i + 1:]:
            if s1 == s2 and b1.Intersects(b2):
                inter = b1.Intersect(b2) if hasattr(b1, "Intersect") else None
                problems.append("%s overlaps %s (%s)" % (r1, r2, s1))
    return problems


def cmd_place():
    check_gpio_against_firmware()
    main = build_main()
    face, nets, a_pt, b_pt, ring = build_face()
    lx, ly, ring_in = ring
    # Loop terminals: the outer one leaves through a short lead to a via just
    # outside the loop; the inner one has its via in its own pad. The router
    # takes both on to the matching network on the bottom layer.
    errs = header_alignment(main, face)
    for e in errs:
        print("HEADER:", e)
    for label, b in (("main", main), ("face", face)):
        for pr in courtyard_report(b, label):
            print("%s: %s" % (label, pr))
    pm = save(main, "brick-main")
    pf = save(face, "brick-face")
    print("wrote", pm, pf)
    if errs:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
NET_WIDTHS = {
    "Power": [0.3, 0.2, 0.15, 0.127],
    "NFC": [0.3, 0.2],
    "Default": [0.15, 0.127],
}
FIRST = ["TX1", "TX2", "TX1F", "TX2F", "MA1", "MB1", "ANT_A", "ANT_B", "XTAL1", "XTAL2",
         "USB_DP", "USB_DN", "RXP", "RXN", "RXP_C", "RXN_C", "VMID", "VDHF", "V1V8"]


def netclass_of(board, name):
    for pat, cls in (("VSYS", "Power"), ("VBUS", "Power"), ("VBAT", "Power"), ("3V3", "Power"), ("VLED", "Power"),
                     ("GND", "Power"), ("SPK_P", "Power"), ("SPK_N", "Power")):
        if name == pat:
            return cls
    if name in ("TX1", "TX2", "TX1F", "TX2F", "MA1", "MB1", "ANT_A", "ANT_B"):
        return "NFC"
    return "Default"


def route_board(board, size, route_layers, via_layers, plane_net, label, via=(0.5, 0.3), clearance=0.15,
                adopt=False, rounds=12, rip_first=(), only=None, stitch=True):
    """Route every net. adopt: treat the unlocked tracks already on the board
    (an earlier Freerouting pass) as this router's own, so rip-up may remove
    and re-route them."""
    import router as R
    mk = lambda: R.Router(board, (OX, OY), size, route_layers, via_layers, plane_net=plane_net,
                          via=via, clearance=clearance, log=lambda m: print("[%s]%s" % (label, m)))
    rt = mk()
    keep = []
    if label == "brick-main":
        keep.append((NOTCH[0] - 0.3, -1, NOTCH[1] + 0.3, NOTCH[2] + 0.3))
    rt.load_board(keep)
    names = {}
    for f in board.GetFootprints():
        for p in f.Pads():
            if p.GetNetCode() > 0:
                names[p.GetNetname()] = p.GetNetCode()
    todo = [n for n in names if not n.startswith("NC_") and n != plane_net and (only is None or n in only)]
    def size_of(n):
        pads = rt.net_pads(names[n])
        xs = [pcbnew.ToMM(p.GetPosition().x) for p in pads]
        ys = [pcbnew.ToMM(p.GetPosition().y) for p in pads]
        return (max(xs) - min(xs)) + (max(ys) - min(ys)) if pads else 0
    todo.sort(key=lambda n: (0 if n in FIRST else 1, FIRST.index(n) if n in FIRST else 0, size_of(n)))
    if plane_net is None:
        # no ground plane: the multi-pin supply nets go first, while there is room
        lead = [n for n in ("GND", "VLED", "3V3") if n in todo]
        todo = lead + [n for n in todo if n not in lead]
    rt.freeze()
    if adopt:
        fixed = mk()
        fixed.load_board(keep, fixed_only=True)
        rt.occ_fixed = {l: fixed.occ[l].copy() for l in rt.all_layers}
        n = 0
        for t in rt._tracks:
            if not t.IsLocked() and t.GetNetCode() > 0:
                rt.added.setdefault(t.GetNetCode(), []).append(t)
                n += 1
        print("[%s] adopted %d existing tracks and vias" % (label, n))
    if rip_first:
        # Remove these nets' unlocked tracks before routing, to lay them again.
        fixed = mk()
        fixed.load_board(keep, fixed_only=True)
        rt.occ_fixed = {l: fixed.occ[l].copy() for l in rt.all_layers}
        codes = {}
        for t in rt._tracks:
            if not t.IsLocked() and t.GetNetname() in rip_first:
                rt.added.setdefault(t.GetNetCode(), []).append(t)
                codes[t.GetNetname()] = t.GetNetCode()
        for nm, code in codes.items():
            rt.rip(code)
        print("[%s] ripped up %s" % (label, ", ".join(sorted(codes))))
    import time
    t0 = time.time()
    failed = []
    for k, n in enumerate(todo):
        ok = rt.route_net(names[n], NET_WIDTHS[netclass_of(board, n)])
        print("[%s] %3d/%d %-12s %s  %.0fs" % (label, k + 1, len(todo), n, "ok" if ok else "FAILED", time.time() - t0), flush=True)
        if not ok:
            failed.append(n)
    # Rip up and reroute: for each failed net, remove only the nets lying on
    # the path it would take, route it, then route those nets again.
    code_name = {v: k for k, v in names.items()}
    for rnd in range(rounds):
        if not failed:
            break
        n = failed.pop(0)
        rt.rip(names[n])
        if rt.route_net(names[n], NET_WIDTHS[netclass_of(board, n)]):
            print("[%s] rip-up %d: %s now routes" % (label, rnd + 1, n), flush=True)
            continue
        code, src, tgt, w = rt.last_fail
        vict = rt.blockers(code, src, tgt, w) or set()
        vict = [code_name[v] for v in vict if v in code_name and code_name[v] != plane_net]
        print("[%s] rip-up %d: %s blocked by %s" % (label, rnd + 1, n, vict), flush=True)
        for v in vict:
            rt.rip(names[v])
        rt.rip(names[n])
        if not rt.route_net(names[n], NET_WIDTHS[netclass_of(board, n)]):
            failed.append(n)
        for v in vict:
            if not rt.route_net(names[v], NET_WIDTHS[netclass_of(board, v)]):
                failed.append(v)
        failed = list(dict.fromkeys(failed))
    if stitch and plane_net and plane_net in names:
        made = rt.stitch_to_plane(names[plane_net])
        print("[%s] %d ground vias" % (label, made))
        if label == "brick-main":
            # stitch_to_plane does not see rule areas: drop vias it put in the
            # antenna keep-out (those pads reach ground through the pour anyway)
            gone = 0
            for t in list(rt._tracks) + [v for v in getattr(rt, "_stitched", [])]:
                xs = [pcbnew.ToMM(t.GetPosition().x)] if t.GetClass() == "PCB_VIA" else \
                     [pcbnew.ToMM(t.GetStart().x), pcbnew.ToMM(t.GetEnd().x)]
                if t.GetNetname() == plane_net and max(xs) - OX > ANT_KEEPOUT_X - 0.3:
                    board.Remove(t)
                    gone += 1
            print("[%s] removed %d ground stubs and vias from the antenna keep-out" % (label, gone))
            made = rt.stitch_grid(names[plane_net], keep=[(ANT_KEEPOUT_X - 0.5, -1, MAIN_W + 1, MAIN_H + 1)])
            print("[%s] %d ground stitching vias" % (label, made))
    return failed


def fill_zones(board):
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())


def cmd_route():
    global np
    import numpy as np  # noqa: F401
    results = {}
    only = sys.argv[2] if len(sys.argv) > 2 else None
    for name, size, layers, plane, via, clr in (
            ("brick-face", (FACE_W, FACE_H), [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu], None, (0.45, 0.25), 0.15),
            ("brick-main", (MAIN_W, MAIN_H), [pcbnew.F_Cu, pcbnew.In2_Cu, pcbnew.B_Cu], "GND", (0.5, 0.3), 0.15)):
        if only and only not in name:
            continue
        path = os.path.join(OUT, name + ".kicad_pcb")
        b = pcbnew.LoadBoard(path)
        failed = route_board(b, size, layers, [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu], plane, name,
                             via=via, clearance=clr)
        fill_zones(b)
        save_board(path, b)
        results[name] = failed
        print("%s: %s" % (name, "all nets routed" if not failed else "UNROUTED: %s" % failed))
    if any(results.values()):
        sys.exit(1)


def export_dsn(name):
    """Write ../kicad/.freerouting/<name>.dsn for Freerouting. Only the inner
    ground plane goes out, marked as a power layer so no signal is routed
    through it; the flood pours on the other layers are filled afterwards,
    round the tracks."""
    path = os.path.join(OUT, name + ".kicad_pcb")
    work = os.path.join(OUT, ".freerouting")
    os.makedirs(work, exist_ok=True)
    dsn, ses = os.path.join(work, name + ".dsn"), os.path.join(work, name + ".ses")
    b = pcbnew.LoadBoard(path)
    if any(not t.IsLocked() for t in b.GetTracks()) and os.environ.get("CONTINUE") != "1":
        raise SystemExit("%s already has tracks: run place first (or CONTINUE=1 to route on from them)" % name)
    for z in list(b.Zones()):
        planes = (pcbnew.In1_Cu, pcbnew.In4_Cu) if b.GetCopperLayerCount() == 6 else (pcbnew.In1_Cu,)
        if not z.GetIsRuleArea() and not any(z.GetLayer() == l for l in planes):
            b.Remove(z)
    if not pcbnew.ExportSpecctraDSN(b, dsn):
        raise SystemExit("DSN export failed")
    s = open(dsn).read()
    for lname in ("In1.Cu", "In4.Cu") if b.GetCopperLayerCount() == 6 else ("In1.Cu",):
        s = s.replace("(layer %s\n      (type signal)" % lname, "(layer %s\n      (type power)" % lname, 1)
    open(dsn, "w").write(s)
    if os.path.exists(ses):
        os.remove(ses)
    return dsn, ses


def freeroute(name, passes=40):
    """Route one board with Freerouting 2.x in this process's environment
    (tools/route_main.sh runs Freerouting 1.9 on the host instead)."""
    dsn, ses = export_dsn(name)
    cmd = [JAVA, "-Djava.awt.headless=true", "-jar", FREEROUTING] if FREEROUTING.endswith(".jar") else [FREEROUTING]
    env = dict(os.environ, JAVA_TOOL_OPTIONS="-Djava.awt.headless=true")
    subprocess.run(cmd + ["-de", dsn, "-do", ses, "-mp", str(passes), "--gui.enabled=false"], check=False, env=env)
    if not os.path.exists(ses):
        raise SystemExit("Freerouting wrote no session file")
    # Import in a fresh process: a second LoadBoard in this one can come back
    # as a bare SwigPyObject in KiCad 9.0.9.
    subprocess.run([sys.executable, os.path.abspath(__file__), "sesimport", name], check=True)


def cmd_sesimport():
    name = sys.argv[2]
    path = os.path.join(OUT, name + ".kicad_pcb")
    ses = os.path.join(OUT, ".freerouting", name + ".ses")
    b = pcbnew.LoadBoard(path)
    if not pcbnew.ImportSpecctraSES(b, ses):
        raise SystemExit("SES import failed")
    fill_zones(b)
    save_board(path, b)
    print("%s: imported the Freerouting session, zones filled" % name)


def silk_labels(b):
    """Silkscreen the few markings an assembler needs: battery polarity at J2,
    the speaker socket, and the board name. Idempotent: replaces earlier ones."""
    for d in list(b.GetDrawings()):
        if d.GetClass() == "PCB_TEXT" and d.GetText().startswith(("+", "-", "SPK", "OPEN PLAY", "BAT")):
            b.Remove(d)
    is_main = b.FindFootprintByReference("U1") is not None

    def text(t, x, y, layer, size=0.7, rot=0):
        o = pcbnew.PCB_TEXT(b)
        o.SetText(t)
        o.SetPosition(P(x, y))
        o.SetLayer(layer)
        o.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
        o.SetTextThickness(mm(0.12))
        o.SetTextAngleDegrees(rot)
        if layer == pcbnew.B_SilkS:
            o.SetMirrored(True)
        b.Add(o)

    def pad_xy(ref, num):
        p = b.FindFootprintByReference(ref).FindPadByNumber(num)
        return pcbnew.ToMM(p.GetPosition().x) - OX, pcbnew.ToMM(p.GetPosition().y) - OY

    if is_main:
        # J2 pads 1 (-) and 2 (+) sit one above the other at 90 degrees; label
        # them on the side away from the plug.
        for num, sign in (("1", "-"), ("2", "+")):
            x, y = pad_xy("J2", num)
            text(sign, x - 1.25, y, pcbnew.F_SilkS, 0.9)
        x, y = pad_xy("J2", "1")
        text("BAT", x - 1.3, min(pad_xy("J2", "1")[1], pad_xy("J2", "2")[1]) - 1.1, pcbnew.F_SilkS, 0.6)
        x, y = pad_xy("J3", "1")
        text("SPK", x + 1.6, y + 1.9, pcbnew.B_SilkS, 0.6)
        text("OPEN PLAY BRICK rev C", 20.5, 12.6, pcbnew.B_SilkS, 0.55)
    return b


def cmd_silk():
    for name in ("brick-main",):
        path = os.path.join(OUT, name + ".kicad_pcb")
        b = pcbnew.LoadBoard(path)
        silk_labels(b)
        save_board(path, b)
        print("%s: silkscreen labels added" % name)


def cmd_dsn():
    print("wrote %s" % export_dsn("brick-" + (sys.argv[2] if len(sys.argv) > 2 else "main"))[0])


def cmd_freeroute():
    only = sys.argv[2] if len(sys.argv) > 2 else "main"
    freeroute("brick-" + only)


def cmd_placecheck():
    import json
    for name in ("brick-main", "brick-face"):
        path = os.path.join(OUT, name + ".kicad_pcb")
        rpt = os.path.join(OUT, name + "-place-drc.json")
        subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--units", "mm", "-o", rpt, path],
                       check=False, capture_output=True)
        d = json.load(open(rpt))
        probs = [v for v in d["violations"] if v["type"] in
                 ("clearance", "shorting_items", "courtyards_overlap", "copper_edge_clearance", "hole_clearance",
                  "solder_mask_bridge", "silk_over_copper") and v["severity"] == "error"]
        print("%s: %d placement problems" % (name, len(probs)))
        for v in probs:
            print("   %-22s %s" % (v["type"], " || ".join(i["description"] for i in v["items"])))


def cmd_check():
    bad = 0
    for name in ("brick-main", "brick-face"):
        path = os.path.join(OUT, name + ".kicad_pcb")
        rpt = os.path.join(OUT, name + "-drc.json")
        subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-error", "--schematic-parity" if False else "--units", "mm",
                        "-o", rpt, path], check=False, capture_output=True)
        import json
        d = json.load(open(rpt))
        v = d.get("violations", [])
        u = d.get("unconnected_items", [])
        print("%s: %d DRC errors, %d unconnected" % (name, len(v), len(u)))
        kinds = {}
        for item in v:
            kinds[item["type"]] = kinds.get(item["type"], 0) + 1
        for k, n in sorted(kinds.items(), key=lambda t: -t[1]):
            print("   %-28s %d" % (k, n))
        for item in (v + u)[:12]:
            print("   -", item["type"], "|", item["description"], "|",
                  "; ".join(i.get("description", "") for i in item.get("items", []))[:160])
        bad += len(v) + len(u)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "place"
    {"place": cmd_place, "route": cmd_route, "freeroute": cmd_freeroute, "check": cmd_check, "placecheck": cmd_placecheck,
     "sesimport": cmd_sesimport, "dsn": cmd_dsn, "silk": cmd_silk}[cmd]()
