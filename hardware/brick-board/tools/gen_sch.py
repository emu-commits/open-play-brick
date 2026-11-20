#!/usr/bin/env python3
"""Draw the brick board's circuit as a PDF, from design.py.

Every chip is a box with its pins named as in its datasheet and the net on
each pin. Passive parts are drawn as two-terminal parts between their nets,
grouped with the chip they serve. Nets are joined by name, as in a
label-style schematic: the same name means the same wire.

    python3 gen_sch.py      ->  ../docs/schematic.pdf
"""
import os
import sys

from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfgen import canvas

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import design  # noqa: E402

OUT = os.path.join(HERE, "..", "docs", "schematic.pdf")

# Pin names from the datasheets (pad number -> name).
PIN_NAMES = {
    "ESP32-C6-MINI-1-N4": {"3": "3V3", "8": "EN", "12": "IO0", "13": "IO1", "5": "IO2", "6": "IO3", "9": "IO4/MTMS",
                           "10": "IO5/MTDI", "15": "IO6/MTCK", "16": "IO7/MTDO", "17": "IO12/USB_D-", "18": "IO13/USB_D+",
                           "19": "IO14", "20": "IO15", "22": "IO8", "23": "IO9", "24": "IO18", "25": "IO19", "26": "IO20",
                           "27": "IO21", "28": "IO22", "29": "IO23", "30": "RXD0/IO17", "31": "TXD0/IO16", "1": "GND"},
    "PN5180A0HN/C3E": {"1": "NSS", "2": "AUX2", "3": "MOSI", "4": "PVSS", "5": "MISO", "6": "PVDD", "7": "SCK", "8": "BUSY",
                       "9": "VSS", "10": "RESET_N", "12": "VBAT", "13": "VBAT", "15": "RXN", "16": "RXP", "17": "VMID",
                       "18": "TX2", "19": "TVSS", "21": "TX1", "22": "TVDD", "23": "ANT1", "24": "ANT2", "25": "VDHF",
                       "26": "VBAT", "27": "VSS", "28": "AVDD", "29": "VDD", "30": "DVDD", "36": "CLK1", "37": "CLK2",
                       "38": "GPO1", "39": "IRQ", "40": "AUX1", "41": "EP"},
    "MAX98357AETE+T": {"1": "DIN", "2": "GAIN_SLOT", "3": "GND", "4": "SD_MODE", "7": "VDD", "8": "VDD", "9": "OUTP",
                       "10": "OUTN", "11": "GND", "14": "LRCLK", "15": "GND", "16": "BCLK", "17": "EP"},
    "ICS-43434": {"1": "WS", "2": "LR", "3": "GND", "4": "SCK", "5": "VDD", "6": "SD"},
    "LIS2DH12TR": {"1": "SCL", "2": "CS", "3": "SDO/SA0", "4": "SDA", "5": "RES", "6": "GND", "7": "GND", "8": "GND",
                   "9": "VDD", "10": "VDD_IO", "11": "INT2", "12": "INT1"},
    "MAX17048G+T10": {"1": "CTG", "2": "CELL", "3": "VDD", "4": "GND", "5": "ALRT", "6": "QSTRT", "7": "SCL", "8": "SDA", "9": "EP"},
    "TP4054": {"1": "CHRG", "2": "GND", "3": "BAT", "4": "VCC", "5": "PROG"},
    "RT9080-33GJ5": {"1": "VIN", "2": "GND", "3": "EN", "4": "NC", "5": "VOUT"},
    "USBLC6-2SC6": {"1": "I/O1", "2": "GND", "3": "I/O2", "4": "I/O2", "5": "VBUS", "6": "I/O1"},
    "TCS34725FN": {"1": "VDD", "2": "SCL", "3": "GND", "4": "NC", "5": "INT", "6": "SDA"},
    "WS2812B-2020": {"1": "DOUT", "2": "GND", "3": "DIN", "4": "VDD"},
    "AO3401A": {"1": "G", "2": "S", "3": "D"},
    "2N7002": {"1": "G", "2": "S", "3": "D"},
    "SN74LV1T34DBVR": {"1": "NC", "2": "A", "3": "GND", "4": "Y", "5": "VCC"},
    "B5819W": {"1": "K", "2": "A"},
    "27.12MHz 10pF": {"1": "X1", "2": "GND", "3": "X2", "4": "GND"},
}

SHEETS = [
    ("Main board: ESP32-C6 module and USB", ["U1", "J1", "U2", "R4", "R5", "C1", "C2", "R1", "C3", "R2", "JP1", "R8", "R9"]),
    ("Main board: power", ["D1", "Q1", "R6", "U3", "R7", "C4", "C5", "U4", "C6", "C8", "J2", "R18", "R19", "C31"]),
    ("Main board: NFC reader", ["U6", "Y1", "C10", "C11", "C12", "C13", "C14", "C15", "C16", "C17", "C18", "C19", "R10",
                                "L1", "L2", "C20", "C21", "C22", "C23", "R11", "C24", "R12", "C25"]),
    ("Main board: audio, motion, pixel supply, header", ["U7", "C26", "C27", "J3", "U9", "C29",
                                                          "Q2", "R15", "Q3", "R16", "U10", "C30", "R17", "J4"]),
    ("Face board: NFC loop and matching", ["J5", "ANT1", "R30", "C40", "C41", "C42", "C43", "R31", "C44", "C45", "C46", "C47"]),
    ("Face board: pixels, colour sensor, lamp", ["LED1", "LED2", "LED3", "LED4", "LED5", "LED6", "LED7", "LED8",
                                                 "C50", "C51", "C52", "C53", "C54", "U20", "C55", "LED9", "R32"]),
]

POWER = {"GND", "3V3", "VSYS", "VBUS", "VBAT", "VLED", "V1V8"}


def net_colour(n):
    if n == "GND":
        return colors.HexColor("#555555")
    if n in POWER:
        return colors.HexColor("#b03020")
    if n.startswith("NC_"):
        return colors.HexColor("#999999")
    return colors.HexColor("#1f4e9a")


def draw_chip(c, p, x, y, w=150):
    names = PIN_NAMES.get(p["value"], {})
    pins = sorted(p["pins"].items(), key=lambda kv: (int(kv[0]) if kv[0].isdigit() else 999, kv[0]))
    # collapse repeated ground pins on big parts
    shown, gnds = [], []
    for pad, n in pins:
        if n == "GND" and len(pins) > 12:
            gnds.append(pad)
        else:
            shown.append((pad, n))
    if gnds:
        shown.append((",".join(gnds[:6]) + ("…" if len(gnds) > 6 else ""), "GND"))
    half = (len(shown) + 1) // 2
    left, right = shown[:half], shown[half:]
    rows = max(len(left), len(right))
    h = 14 * rows + 26
    c.setStrokeColor(colors.black)
    c.setFillColor(colors.HexColor("#fff8e8"))
    c.rect(x, y - h, w, h, fill=1)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(x + w / 2, y - 12, "%s  %s" % (p["ref"], p["value"]))
    c.setFont("Helvetica", 7)
    for side, lst in ((0, left), (1, right)):
        for k, (pad, n) in enumerate(lst):
            yy = y - 26 - 14 * k
            label = names.get(pad.split(",")[0], "")
            if side == 0:
                c.setFillColor(colors.black)
                c.drawString(x + 4, yy, "%s %s" % (pad, label))
                c.line(x - 18, yy + 2, x, yy + 2)
                c.setFillColor(net_colour(n))
                c.drawRightString(x - 20, yy, n)
            else:
                c.setFillColor(colors.black)
                c.drawRightString(x + w - 4, yy, "%s %s" % (label, pad))
                c.line(x + w, yy + 2, x + w + 18, yy + 2)
                c.setFillColor(net_colour(n))
                c.drawString(x + w + 20, yy, n)
    c.setFillColor(colors.black)
    return h


def draw_two_pin(c, p, x, y):
    pads = list(p["pins"].items())[:2]
    a, b = pads[0][1], pads[1][1]
    c.setFont("Helvetica", 7)
    c.setFillColor(net_colour(a))
    c.drawRightString(x - 4, y, a)
    c.setFillColor(colors.black)
    c.line(x, y + 2, x + 18, y + 2)
    c.setFillColor(colors.HexColor("#eef4ff"))
    c.rect(x + 18, y - 3, 34, 10, fill=1)
    c.setFillColor(colors.black)
    c.line(x + 52, y + 2, x + 70, y + 2)
    c.setFillColor(net_colour(b))
    c.drawString(x + 74, y, b)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 7)
    c.drawCentredString(x + 35, y + 10, p["ref"])
    c.setFont("Helvetica", 6)
    c.drawString(x + 120, y, "%s%s" % (p["value"], ("  -  " + p["note"]) if p["note"] else ""))


def main():
    parts = {p["ref"]: p for p in design.PARTS}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    c = canvas.Canvas(OUT, pagesize=landscape(A3))
    W, H = landscape(A3)
    for page, (title, refs) in enumerate(SHEETS, 1):
        c.setFont("Helvetica-Bold", 14)
        c.drawString(30, H - 36, "Open Play Brick, brick board (rev C) - %s" % title)
        c.setFont("Helvetica", 8)
        c.drawString(30, H - 50, "Generated from hardware/brick-board/tools/design.py. Nets join by name. "
                     "Blue: signals, red: supplies, grey: ground or not connected.   Sheet %d of %d" % (page, len(SHEETS)))
        chips = [parts[r] for r in refs if r in parts and (len(parts[r]["pins"]) > 4 or r.startswith(("J", "U", "Q", "Y")))]
        passives = [parts[r] for r in refs if r in parts and parts[r] not in chips]
        x, y, colh = 110, H - 80, 0
        for p in chips:
            if p["ref"] == "ANT1":
                continue
            hgt = 14 * ((len(p["pins"]) + 1) // 2) + 40
            if y - hgt < 60:
                x += 330
                y = H - 80
            draw_chip(c, p, x, y)
            y -= hgt + 18
        px = x + 330 if x < W - 600 else W - 520
        py = H - 90
        c.setFont("Helvetica-Bold", 10)
        c.drawString(px, py + 12, "Passive parts")
        for p in passives + ([parts["ANT1"]] if "ANT1" in refs else []):
            draw_two_pin(c, p, px + 60, py - 14)
            py -= 26
        c.showPage()
    c.save()
    print("wrote", os.path.normpath(OUT))


if __name__ == "__main__":
    main()
