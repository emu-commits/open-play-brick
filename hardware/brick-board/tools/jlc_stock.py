#!/usr/bin/env python3
"""Check every JLCPCB part number in design.py against JLCPCB's live stock.

    python3 jlc_stock.py [--qty N]     # stock needed for N boards (default 5)

Prints each part with its stock and library type (basic parts carry no
loading fee; extended parts cost a few dollars each per order) and flags any
part that is missing or short. Needs only the Python standard library.
"""
import collections
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design  # noqa: E402

URL = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"


def lookup(code):
    req = urllib.request.Request(URL, data=json.dumps({"keyword": code, "currentPage": 1, "pageSize": 5}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    d = json.load(urllib.request.urlopen(req, timeout=30))
    for c in ((d.get("data") or {}).get("componentPageInfo") or {}).get("list") or []:
        if c["componentCode"] == code:
            return c
    return None


def main():
    qty = int(sys.argv[sys.argv.index("--qty") + 1]) if "--qty" in sys.argv else 5
    use = collections.defaultdict(list)
    for p in design.PARTS:
        if p["lcsc"]:
            use[p["lcsc"]].append(p["ref"])
    bad = 0
    ext = 0
    for code, refs in sorted(use.items(), key=lambda t: t[1][0]):
        c = lookup(code)
        time.sleep(0.2)
        if c is None:
            print("%-10s %-26s NOT FOUND %s" % (code, "", ",".join(refs)), flush=True)
            bad += 1
            continue
        need = qty * len(refs)
        short = c["stockCount"] < need
        bad += short
        ext += c["componentLibraryType"] != "base"
        print("%-10s %-26.26s %-8s stock %7d need %4d %-5s %s" % (
            code, c["componentModelEn"], c["componentLibraryType"], c["stockCount"], need,
            "SHORT" if short else "", ",".join(refs)), flush=True)
    print("%d part numbers, %d extended, %d problems" % (len(use), ext, bad))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
