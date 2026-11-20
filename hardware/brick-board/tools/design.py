"""Open Play Brick, brick board (rev C): every part, pin and net.

This file is the source of truth for the circuit. gen_board.py builds the two
circuit boards from it, gen_sch.py draws the schematic from it, and
gen_fab.py writes the JLCPCB parts list from it. A check in gen_board.py
fails if the GPIO numbers here drift from firmware/core/pins.h.

Two boards, stacked inside the brick:

  main  4-layer, 45.4 x 13.4 mm. ESP32-C6 module on the underside, everything
        else on top: USB-C, charger, regulator, fuel gauge, NFC reader,
        amplifier, microphone, accelerometer, connectors.
  face  4-layer, 24.4 x 13.4 mm, sits 5.8 mm above the main board on a
        1.27 mm board-to-board header. The NFC loop, its matching
        capacitors, eight RGB pixels, the colour sensor and its lamp.

Part fields: ref, board, side ('top'/'bottom'), footprint (in lib/lcsc.pretty
unless it contains ':'), value, lcsc (JLCPCB part number, None = not
assembled), pins {pad: net}.
"""

# GPIO numbers. These are the rev B module build's numbers, so the same
# firmware image runs on both. Checked against firmware/core/pins.h.
GPIO = {
    "NFC_NSS": 0, "IMU_INT1": 1, "NFC_BUSY": 2, "NFC_RST": 3,
    "I2S_BCLK": 5, "I2S_LRCLK": 6, "I2S_DOUT": 7,
    "USB_DN": 12, "USB_DP": 13, "LED_DATA": 14, "LAMP_EN": 16, "PERIPH_EN": 17,
    "I2C_SCL": 18, "I2C_SDA": 19, "SPI_SCK": 21, "SPI_MOSI": 22, "SPI_MISO": 23,
}
# GPIO4 was the microphone's data line (I2S_DIN) on rev B. Rev C has no
# microphone; GPIO4 (ADC1 channel 4) reads the battery through a divider
# instead, net VBAT_SENSE. The firmware needs a small change to use it.
#
# QT_PWR (GPIO20) switched the Feather's sensor connector. The brick board
# powers its sensors from 3V3 all the time, so GPIO20 is left unconnected; the
# firmware still drives it, harmlessly.

# ESP32-C6-MINI-1 module pad for each GPIO (datasheet table 3-1).
MODULE_PAD = {0: "12", 1: "13", 2: "5", 3: "6", 4: "9", 5: "10", 6: "15", 7: "16",
              8: "22", 9: "23", 12: "17", 13: "18", 14: "19", 15: "20", 16: "31",
              17: "30", 18: "24", 19: "25", 20: "26", 21: "27", 22: "28", 23: "29"}

# Board-to-board header, main J4 pin n mates with face J5 pin n.
HEADER = {"1": "TX2F", "2": "TX1F", "3": "GND", "4": "GND", "5": "3V3", "6": "VLED",
          "7": "I2C_SDA", "8": "I2C_SCL", "9": "LED_DIN", "10": "LAMP_EN"}

PARTS = []


def part(ref, board, side, footprint, value, lcsc, pins, note=""):
    PARTS.append(dict(ref=ref, board=board, side=side, footprint=footprint, value=value,
                      lcsc=lcsc, pins={str(k): v for k, v in pins.items()}, note=note))


def R(ref, board, side, value, lcsc, a, b, note=""):
    part(ref, board, side, "R0402", value, lcsc, {1: a, 2: b}, note)


def C(ref, board, side, value, lcsc, a, b, note="", fp="C0402"):
    part(ref, board, side, fp, value, lcsc, {1: a, 2: b}, note)


# Common parts
C100N, C1U, C1N, C4U7, C470N = "C1525", "C52923", "C1523", "C23733", "C47339"
C10U, C22U = "C19702", "C59461"
R100K, R10K, R4K7, R5K1, R20K, R1K, R3K3, R33, R100 = ("C25741", "C25744", "C25900", "C25905",
                                                        "C25765", "C11702", "C25890", "C25105", "C25076")

# ===========================================================================
# Main board
# ===========================================================================
M = "main"

# --- ESP32-C6 module (underside) -------------------------------------------
mod = {str(p): "GND" for p in (1, 2, 11, 14, 36) + tuple(range(37, 54))}
mod.update({"3": "3V3", "8": "EN", "4": "NC_M4", "7": "NC_M7", "21": "NC_M21"})
for p in ("32", "33", "34", "35"):
    mod[p] = "NC_M" + p
net_of_gpio = {v: k for k, v in GPIO.items()}
for g, pad in MODULE_PAD.items():
    mod[pad] = net_of_gpio.get(g, {4: "VBAT_SENSE", 8: "IO8", 9: "IO9", 15: "NC_IO15", 20: "NC_IO20"}.get(g))
part("U1", M, "bottom", "WIFIM-SMD_61P-L16.6-W13.2-P0.80-ESP32-C6-MINI-1-N4", "ESP32-C6-MINI-1-N4", "C5736265", mod)
C("C1", M, "top", "22uF 6.3V", C22U, "3V3", "GND", "module supply", fp="C0603")
C("C2", M, "top", "100nF", C100N, "3V3", "GND", "module supply")
R("R1", M, "bottom", "10k", R10K, "3V3", "EN", "EN pull-up")
C("C3", M, "bottom", "1uF", C1U, "EN", "GND", "EN delay")
R("R2", M, "bottom", "10k", R10K, "3V3", "IO8", "strapping: GPIO8 high")
part("JP1", M, "bottom", "Jumper:SolderJumper-2_P1.3mm_Open_Pad1.0x1.5mm", "BOOT", None,
     {1: "IO9", 2: "GND"}, "bridge with tweezers while plugging in USB to force download mode (GPIO9 has an internal pull-up)")

# --- USB-C, protection, power path -----------------------------------------
part("J1", M, "top", "USB-C_SMD-TYPE-C-31-M-12_1", "USB-C", "C165948",
     {"A1B12": "GND", "B1A12": "GND", "A4B9": "VBUS", "B4A9": "VBUS", "A5": "CC1", "B5": "CC2",
      "A6": "USB_DP", "B6": "USB_DP", "A7": "USB_DN", "B7": "USB_DN", "A8": "NC_SBU1", "B8": "NC_SBU2",
      "1": "GND", "2": "GND", "3": "GND", "4": "GND"})
R("R4", M, "bottom", "5.1k", R5K1, "CC1", "GND", "USB-C sink")
R("R5", M, "bottom", "5.1k", R5K1, "CC2", "GND", "USB-C sink")
part("U2", M, "bottom", "SOT-23-6_L2.9-W1.6-P0.95-LS2.8-BL", "USBLC6-2SC6", "C7519",
     {1: "USB_DN", 2: "GND", 3: "USB_DP", 4: "USB_DP", 5: "VBUS", 6: "USB_DN"})
part("D1", M, "bottom", "SOD-123_L2.7-W1.6-LS3.7-RD-1", "B5819W", "C8598", {1: "VSYS", 2: "VBUS"},
     "USB to system rail (pad 1 = cathode)")
part("Q1", M, "bottom", "SOT-23_L2.9-W1.3-P1.90-LS2.4-BR", "AO3401A", "C15127", {1: "VBUS", 2: "VSYS", 3: "VBAT"},
     "battery to system rail, off while USB is present")
R("R6", M, "bottom", "100k", R100K, "VBUS", "GND", "holds Q1 on when USB is absent")
C("C4", M, "bottom", "4.7uF", C4U7, "VBUS", "GND")
part("U3", M, "bottom", "SOT-23-5_L3.0-W1.7-P0.95-LS2.8-BL", "TP4054", "C32574",
     {1: "NC_CHRG", 2: "GND", 3: "VBAT", 4: "VBUS", 5: "PROG"}, "LiPo charger")
R("R7", M, "bottom", "20k", R20K, "PROG", "GND", "charge current 50 mA")
C("C5", M, "bottom", "4.7uF", C4U7, "VBAT", "GND")
C("C6", M, "bottom", "10uF", C10U, "VSYS", "GND", fp="C0603")
part("U4", M, "bottom", "TSOT-23-5_L2.9-W1.6-P0.95-LS2.8-BL", "RT9080-33GJ5", "C841192",
     {1: "VSYS", 2: "GND", 3: "VSYS", 4: "NC_U4", 5: "3V3"}, "3.3 V regulator, 2 uA quiescent")
C("C8", M, "bottom", "10uF", C10U, "3V3", "GND", fp="C0603")
part("J2", M, "top", "CONN-SMD_2P-P1.00_SM02B-SRSS-TB-LF-SN", "BATTERY JST-SH 1.0mm", "C160402",
     {1: "GND", 2: "VBAT", 3: "GND", 4: "GND"}, "pin 1 -, pin 2 +. Check the battery's polarity before plugging in")
# Battery voltage to GPIO4 (ADC). 1M + 1M draws about 2 uA from the battery;
# the capacitor holds the node while the ADC samples it.
R("R18", M, "bottom", "1M", "C26083", "VBAT", "VBAT_SENSE", "battery sense divider")
R("R19", M, "bottom", "1M", "C26083", "VBAT_SENSE", "GND", "battery sense divider")
C("C31", M, "bottom", "100nF", C100N, "VBAT_SENSE", "GND")
R("R8", M, "bottom", "4.7k", R4K7, "3V3", "I2C_SDA", "I2C pull-up")
R("R9", M, "bottom", "4.7k", R4K7, "3V3", "I2C_SCL", "I2C pull-up")

# --- NFC reader -------------------------------------------------------------
nfc = {1: "NFC_NSS", 2: "NC_AUX2", 3: "SPI_MOSI", 4: "GND", 5: "SPI_MISO", 6: "3V3", 7: "SPI_SCK",
       8: "NFC_BUSY", 9: "GND", 10: "NFC_RST", 11: "NC_N11", 12: "VSYS", 13: "VSYS", 14: "NC_N14",
       15: "RXN", 16: "RXP", 17: "VMID", 18: "TX2", 19: "GND", 20: "NC_N20", 21: "TX1", 22: "VSYS",
       23: "NC_ANT1", 24: "NC_ANT2", 25: "VDHF", 26: "VSYS", 27: "GND", 28: "V1V8", 29: "V1V8",
       30: "V1V8", 31: "NC_N31", 32: "NC_N32", 33: "NC_N33", 34: "NC_N34", 35: "NC_N35",
       36: "XTAL1", 37: "XTAL2", 38: "NC_GPO1", 39: "NC_IRQ", 40: "NC_AUX1", 41: "GND"}
part("U6", M, "top", "HVQFN-40_L6.0-W6.0-PS0.50-BL", "PN5180A0HN/C3E", "C1526287", nfc, "NFC frontend")
part("Y1", M, "top", "CRYSTAL-SMD_4P-L3.2-W2.5-BL-1", "27.12MHz 10pF", "C29975",
     {1: "XTAL1", 2: "GND", 3: "XTAL2", 4: "GND"})
C("C10", M, "top", "15pF C0G", "C1548", "XTAL1", "GND")
C("C11", M, "top", "15pF C0G", "C1548", "XTAL2", "GND")
C("C12", M, "top", "1nF", C1N, "V1V8", "GND", "PN5180 1.8 V (datasheet C3)")
C("C13", M, "top", "100nF", C100N, "V1V8", "GND", "PN5180 1.8 V (C4)")
C("C14", M, "top", "470nF", C470N, "VDHF", "GND", "PN5180 VDHF (C5)")
C("C15", M, "top", "100nF", C100N, "VSYS", "GND", "PN5180 VBAT (C6)")
C("C16", M, "top", "10uF", C10U, "VSYS", "GND", "PN5180 TVDD (C7)", fp="C0603")
C("C17", M, "top", "100nF", C100N, "VSYS", "GND", "PN5180 TVDD")
C("C18", M, "top", "100nF", C100N, "3V3", "GND", "PN5180 PVDD")
C("C19", M, "top", "100nF", C100N, "VMID", "GND", "PN5180 VMID")
R("R10", M, "top", "100k", R100K, "NFC_RST", "GND", "reader held in power-down until the firmware wakes it")
part("L1", M, "top", "L0805", "470nH MLF2012", "C92032", {1: "TX1", 2: "TX1F"}, "EMC filter")
part("L2", M, "top", "L0805", "470nH MLF2012", "C92032", {1: "TX2", 2: "TX2F"}, "EMC filter")
C("C20", M, "top", "56pF 1% C0G", "C526981", "TX1F", "GND", "EMC filter C0")
C("C21", M, "top", "68pF 1% C0G", "C389103", "TX1F", "GND", "EMC filter C0")
C("C22", M, "top", "56pF 1% C0G", "C526981", "TX2F", "GND", "EMC filter C0")
C("C23", M, "top", "68pF 1% C0G", "C389103", "TX2F", "GND", "EMC filter C0")
R("R11", M, "top", "3.3k", R3K3, "RXP", "RXP_C", "receiver tap")
C("C24", M, "top", "1nF", C1N, "RXP_C", "TX1F", "receiver coupling")
R("R12", M, "top", "3.3k", R3K3, "RXN", "RXN_C", "receiver tap")
C("C25", M, "top", "1nF", C1N, "RXN_C", "TX2F", "receiver coupling")

# --- Audio -------------------------------------------------------------------
part("U7", M, "bottom", "TQFN-16_L3.0-W3.0-P0.50-BL-EP1.5", "MAX98357AETE+T", "C910544",
     {1: "I2S_DOUT", 2: "NC_GAIN", 3: "GND", 4: "PERIPH_EN", 5: "NC_A5", 6: "NC_A6", 7: "VSYS", 8: "VSYS",
      9: "SPK_P", 10: "SPK_N", 11: "GND", 12: "NC_A12", 13: "NC_A13", 14: "I2S_LRCLK", 15: "GND",
      16: "I2S_BCLK", 17: "GND"}, "class-D amplifier, 9 dB")
C("C26", M, "bottom", "10uF", C10U, "VSYS", "GND", fp="C0603")
C("C27", M, "bottom", "100nF", C100N, "VSYS", "GND")
part("J3", M, "bottom", "CONN-SMD_2P-P1.00_SM02B-SRSS-TB-LF-SN", "SPEAKER JST-SH 1.0mm", "C160402",
     {1: "SPK_P", 2: "SPK_N", 3: "NC_J3A", 4: "NC_J3B"}, "2.9 mm tall: fits the 3.3 mm over the speaker")

# --- Accelerometer -------------------------------------------------------------
part("U9", M, "bottom", "LGA-12_L2.0-W2.0-P0.50-BL", "LIS2DH12TR", "C110926",
     {1: "I2C_SCL", 2: "3V3", 3: "GND", 4: "I2C_SDA", 5: "GND", 6: "GND", 7: "GND", 8: "GND",
      9: "3V3", 10: "3V3", 11: "NC_INT2", 12: "IMU_INT1"}, "address 0x18 (SA0 low)")
C("C29", M, "bottom", "100nF", C100N, "3V3", "GND")

# --- Pixel supply and level shifter --------------------------------------------
part("Q2", M, "bottom", "SOT-23_L2.9-W1.3-P1.90-LS2.4-BR", "AO3401A", "C15127", {1: "LED_G", 2: "VSYS", 3: "VLED"},
     "pixel supply switch")
R("R15", M, "bottom", "100k", R100K, "VSYS", "LED_G")
part("Q3", M, "bottom", "SOT-23-3_L2.9-W1.3-P1.90-LS2.4-BR", "2N7002", "C8545", {1: "PERIPH_EN", 2: "GND", 3: "LED_G"})
R("R16", M, "bottom", "100k", R100K, "PERIPH_EN", "GND", "pixels and amplifier off until the firmware runs")
# The pixels run from VSYS (up to about 4.7 V on USB), where a WS2812's input
# threshold is 0.7 x VDD, about 3.3 V: a 3.3 V GPIO is marginal. U10 is powered
# from the pixel rail and has TTL-level inputs that tolerate 5.5 V with its
# supply off, so it lifts the data to the pixels' own supply.
part("U10", M, "bottom", "SOT-23-5_L3.0-W1.7-P0.95-LS2.8-BL", "SN74LV1T34DBVR", "C100024",
     {1: "NC_U10", 2: "LED_DATA", 3: "GND", 4: "LED_BUF", 5: "VLED"}, "pixel data level shifter")
C("C30", M, "bottom", "100nF", C100N, "VLED", "GND")
R("R17", M, "bottom", "33", R33, "LED_BUF", "LED_DIN", "pixel data series resistor")

part("J4", M, "top", "HDR-SMD_10P-P1.27-V-M-R2-C5-LS5.5_1", "2x5 1.27mm male", "C27985146", HEADER,
     "to the face board")

# ===========================================================================
# Face board
# ===========================================================================
Fb = "face"
# The socket is on the face board's underside, so seen from above its pad
# numbering is mirrored: main J4 pin 2k-1 meets face J5 pad 11-2k, and J4 pin
# 2k meets J5 pad 12-2k. gen_board.py checks this against the geometry.
J5_PINS = {}
for k in range(1, 6):
    J5_PINS[str(11 - 2 * k)] = HEADER[str(2 * k - 1)]
    J5_PINS[str(12 - 2 * k)] = HEADER[str(2 * k)]
part("J5", Fb, "bottom", "HDR-SMD_10P-P1.27-V-F-R2-C5-LS4.8", "2x5 1.27mm female", "C22436130", J5_PINS,
     "to the main board")
part("ANT1", Fb, "top", "NFC_LOOP", "NFC loop 1.0uH", None, {1: "ANT_A", 2: "ANT_B"},
     "printed 6-turn loop, see tools/nfc_antenna.py")
# Matching network, AN11740 asymmetric. Values from tools/nfc_antenna.py.
C("C40", Fb, "bottom", "47pF 1% C0G", "C277503", "TX1F", "MA1", "C1 (series)")
C("C41", Fb, "bottom", "4.7pF C0G", "C325453", "TX1F", "MA1", "C1 (series)")
C("C42", Fb, "bottom", "120pF 1% C0G", "C541468", "MA1", "GND", "C2 (parallel)")
C("C43", Fb, "bottom", "56pF 1% C0G", "C526981", "MA1", "GND", "C2 (parallel)")
R("R30", Fb, "bottom", "3.0", "C309547", "MA1", "ANT_A", "Rq (damping)")
C("C44", Fb, "bottom", "47pF 1% C0G", "C277503", "TX2F", "MB1", "C1 (series)")
C("C45", Fb, "bottom", "4.7pF C0G", "C325453", "TX2F", "MB1", "C1 (series)")
C("C46", Fb, "bottom", "120pF 1% C0G", "C541468", "MB1", "GND", "C2 (parallel)")
C("C47", Fb, "bottom", "56pF 1% C0G", "C526981", "MB1", "GND", "C2 (parallel)")
R("R31", Fb, "bottom", "3.0", "C309547", "MB1", "ANT_B", "Rq (damping)")

# Eight pixels in a chain, 1..8. WS2812B-2020 pads: 1 DOUT, 2 GND, 3 DIN, 4 VDD.
chain = ["LED_DIN"] + ["PIX%d" % i for i in range(1, 8)] + ["NC_PIX8"]
for i in range(8):
    part("LED%d" % (i + 1), Fb, "top", "LED-SMD_4P-L2.2-W2.0-P1.00_WS2815C-2020-4P", "WS2812B-2020", "C52917434",
         {1: chain[i + 1], 2: "GND", 3: chain[i], 4: "VLED"})
for i in range(4):
    C("C%d" % (50 + i), Fb, "bottom", "100nF", C100N, "VLED", "GND", "pixel decoupling")
C("C54", Fb, "bottom", "10uF", C10U, "VLED", "GND", fp="C0603")
part("U20", Fb, "top", "SENSOR-SMD_TCS34725FN", "TCS34725FN", "C2649487",
     {1: "3V3", 2: "I2C_SCL", 3: "GND", 4: "NC_TCS4", 5: "NC_TCS_INT", 6: "I2C_SDA"}, "colour sensor")
C("C55", Fb, "bottom", "100nF", C100N, "3V3", "GND")
part("LED9", Fb, "top", "LED0603-RD_WHITE", "white", "C965808", {1: "GND", 2: "LAMP_A"},
     "lamp for the colour sensor (pad 1 = cathode)")
R("R32", Fb, "bottom", "47", "C25118", "LAMP_EN", "LAMP_A", "lamp, driven straight from GPIO16: about 5 to 10 mA")


def parts(board=None):
    return [p for p in PARTS if board is None or p["board"] == board]


def nets(board=None):
    out = {}
    for p in parts(board):
        for pad, n in p["pins"].items():
            out.setdefault(n, []).append((p["ref"], pad))
    return out


if __name__ == "__main__":
    for b in ("main", "face"):
        ps = parts(b)
        ns = nets(b)
        print("%s: %d parts, %d nets" % (b, len(ps), len([n for n in ns if not n.startswith("NC_")])))
        for n, members in sorted(ns.items()):
            if len(members) == 1 and not n.startswith("NC_"):
                print("  single-pin net:", n, members)
