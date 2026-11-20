#!/usr/bin/env python3
"""Write the JLCPCB order files for both boards.

Run with KiCad's Python (tools/kicad.sh python3 gen_fab.py). For each board
it writes ../fab/<board>/:

    <board>-gerbers.zip   Gerbers and drill files: upload this as the PCB
    <board>-bom.csv       parts list (Comment, Designator, Footprint, LCSC Part #)
    <board>-cpl.csv       placement (Designator, Mid X, Mid Y, Layer, Rotation)

It refuses to write anything for a board that fails DRC or has unrouted
connections, unless --force is given.

Rotations: every assembled footprint comes from the LCSC/EasyEDA library,
which is JLCPCB's own, so top-side parts need no correction. Bottom-side
angles are mirrored (180 - angle), as JLCPCB views the bottom from above.
Check the placement preview on JLCPCB's site before paying either way.
"""
import collections
import csv
import json
import os
import shutil
import subprocess
import sys
import zipfile

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import design  # noqa: E402

KICAD = os.path.join(ROOT, "kicad")
FAB = os.path.join(ROOT, "fab")
BOARDS = {"brick-main": "main", "brick-face": "face"}

# Per-footprint rotation corrections, degrees, added before mirroring. Empty
# because the footprints come from JLCPCB's own library; add an entry here if
# the JLCPCB preview shows a part turned.
ROT_FIX = {}


def drc_ok(name):
    path = os.path.join(KICAD, name + ".kicad_pcb")
    rpt = os.path.join(KICAD, name + "-drc.json")
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-error", "--units", "mm",
                    "-o", rpt, path], check=False, capture_output=True)
    d = json.load(open(rpt))
    v, u = d.get("violations", []), d.get("unconnected_items", [])
    print("%s: %d DRC errors, %d unconnected" % (name, len(v), len(u)))
    return not v and not u


def gerbers(name, out):
    path = os.path.join(KICAD, name + ".kicad_pcb")
    b = pcbnew.LoadBoard(path)
    n = b.GetCopperLayerCount()
    cu = ["F.Cu"] + ["In%d.Cu" % i for i in range(1, n - 1)] + ["B.Cu"]
    layers = cu + ["F.Paste", "B.Paste", "F.Silkscreen", "B.Silkscreen", "F.Mask", "B.Mask", "Edge.Cuts"]
    g = os.path.join(out, "gerbers")
    shutil.rmtree(g, ignore_errors=True)
    os.makedirs(g)
    subprocess.run(["kicad-cli", "pcb", "export", "gerbers", "--layers", ",".join(layers), "--subtract-soldermask",
                    "--use-drill-file-origin", "-o", g + "/", path], check=True, capture_output=True)
    subprocess.run(["kicad-cli", "pcb", "export", "drill", "--format", "excellon", "--excellon-units", "mm",
                    "--excellon-separate-th", "--drill-origin", "plot", "-o", g + "/", path],
                   check=True, capture_output=True)
    z = os.path.join(out, name + "-gerbers.zip")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(os.listdir(g)):
            zf.write(os.path.join(g, f), f)
    print("  %s (%d files, %d copper layers)" % (os.path.relpath(z, ROOT), len(os.listdir(g)), n))
    return b


def bom_cpl(name, b, out):
    by_ref = {p["ref"]: p for p in design.parts(BOARDS[name])}
    groups = collections.OrderedDict()
    rows = []
    org = b.GetDesignSettings().GetAuxOrigin()
    for f in sorted(b.GetFootprints(), key=lambda f: f.GetReference()):
        ref = f.GetReference()
        p = by_ref.get(ref)
        if p is None or not p["lcsc"]:
            continue                          # the printed loop, the boot jumper
        fp = p["footprint"].split(":")[-1]
        key = (p["value"], fp, p["lcsc"])
        groups.setdefault(key, []).append(ref)
        pos = f.GetPosition()
        x = pcbnew.ToMM(pos.x - org.x)
        y = -pcbnew.ToMM(pos.y - org.y)
        rot = f.GetOrientation().AsDegrees() + ROT_FIX.get(fp, 0)
        bottom = f.IsFlipped()
        if bottom:
            rot = 180 - rot
        rows.append((ref, "%.3f" % x, "%.3f" % y, "Bottom" if bottom else "Top", "%g" % (rot % 360)))
    missing = set(r for r, p in by_ref.items() if p["lcsc"]) - set(r[0] for r in rows)
    if missing:
        raise SystemExit("%s: parts in design.py missing from the board: %s" % (name, sorted(missing)))
    with open(os.path.join(out, name + "-bom.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for (val, fp, lcsc), refs in groups.items():
            w.writerow([val, ",".join(refs), fp, lcsc])
    with open(os.path.join(out, name + "-cpl.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        w.writerows(rows)
    sides = collections.Counter(r[3] for r in rows)
    print("  %d parts placed (%s), %d BOM lines" % (len(rows), ", ".join("%d %s" % (n, s.lower()) for s, n in sides.items()),
                                                    len(groups)))


def main():
    force = "--force" in sys.argv
    bad = False
    for name in BOARDS:
        if not drc_ok(name) and not force:
            print("  not written: fix DRC first (or --force)")
            bad = True
            continue
        out = os.path.join(FAB, name)
        os.makedirs(out, exist_ok=True)
        b = gerbers(name, out)
        bom_cpl(name, b, out)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
