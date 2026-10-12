// Behavioural models of the chips on the board. Each one answers the same
// bytes, on the same pins, in the same order as the real part's datasheet
// describes, for the subset of features the firmware uses. Time is the
// board's virtual clock, in microseconds.

// ---------------------------------------------------------------------------
// ISO 15693 tag
// ---------------------------------------------------------------------------
export class Iso15693Tag {
  constructor({ name, uid, mem, blocks = 66, placeholder = false }) {
    this.name = name;
    this.uid = uid;                    // 8 bytes, E0 first
    this.mem = mem;
    this.blocks = blocks;
    this.placeholder = placeholder;
  }

  // request and response are byte arrays without the CRC (the reader chip
  // adds and checks it).
  respond(req) {
    const flags = req[0], cmd = req[1];
    const uidLsb = Array.from(this.uid).reverse();
    const inventory = flags & 0x04;
    if (inventory) {
      if (cmd !== 0x01) return null;
      return [0x00, 0x00, ...uidLsb];
    }
    let p = 2;
    if (flags & 0x20) {                 // addressed: UID follows the command
      for (let i = 0; i < 8; i++) if (req[p + i] !== uidLsb[i]) return null;
      p += 8;
    }
    const error = code => [0x01, code];
    switch (cmd) {
      case 0x20: {
        const b = req[p];
        if (b >= this.blocks) return error(0x10);
        return [0x00, ...this.mem.subarray(b * 4, b * 4 + 4)];
      }
      case 0x23: {
        const first = req[p], n = req[p + 1] + 1;
        if (first + n > this.blocks) return error(0x10);
        return [0x00, ...this.mem.subarray(first * 4, (first + n) * 4)];
      }
      case 0x2B:
        // Info flags 0x0F, UID, DSFID, AFI, memory size (66 blocks of 4), IC reference 0x17.
        return [0x00, 0x0F, ...uidLsb, 0x00, 0x00, this.blocks - 1, 0x03, 0x17];
      default:
        return error(0x01);
    }
  }
}

// ---------------------------------------------------------------------------
// PN5180 NFC frontend
// ---------------------------------------------------------------------------
const PN = {
  WRITE_REGISTER: 0x00, WRITE_REGISTER_OR_MASK: 0x01, WRITE_REGISTER_AND_MASK: 0x02,
  READ_REGISTER: 0x04, READ_EEPROM: 0x07, SEND_DATA: 0x09, READ_DATA: 0x0A,
  LOAD_RF_CONFIG: 0x11, RF_ON: 0x16, RF_OFF: 0x17,
  REG_SYSTEM_CONFIG: 0x00, REG_IRQ_STATUS: 0x02, REG_IRQ_CLEAR: 0x03, REG_RX_STATUS: 0x13, REG_RF_STATUS: 0x1D,
  IRQ_RX: 1 << 0, IRQ_TX: 1 << 1, IRQ_IDLE: 1 << 2, IRQ_TX_RFOFF: 1 << 8, IRQ_TX_RFON: 1 << 9, IRQ_RX_SOF: 1 << 14,
};
const BIT_US_15693 = 1e6 / 26480;       // high data rate

export class PN5180 {
  constructor(board) {
    this.board = board;
    this.tag = null;                    // tag in the field, or null
    this.powered = false;
    this.reset(0);
  }

  reset(t) {
    this.reg = new Uint32Array(0x40);
    this.eeprom = new Uint8Array(0x100);
    // Product 4.0, firmware 4.0, EEPROM 153.0: what a current module reports.
    this.eeprom.set([0x00, 0x04, 0x00, 0x04, 0x00, 0x99], 0x10);
    this.rfOn = false;
    this.rfOnSince = 0;
    this.rfConfig = null;
    this.nss = 1;
    this.frame = [];
    this.response = null;               // bytes waiting to be clocked out
    this.rxBuffer = [];
    this.busyUntil = t + 1500;          // boot time after reset
    this.pending = [];                  // [{t, bits}] IRQ bits that become set later
    this.clocked = false;
  }

  setPower(on, t) {
    if (on === this.powered) return;
    this.powered = on;
    if (on) this.reset(t);
    else { this.rfOn = false; this.board.edge('NFC_BUSY', t, 0); }
  }

  busy(t) {
    if (!this.powered) return 0;
    if (this.nss === 0 && this.clocked) return 1;
    return t < this.busyUntil ? 1 : 0;
  }

  setNss(level, t) {
    if (level === this.nss) return;
    this.nss = level;
    if (!this.powered) return;
    if (level === 0) { this.frame = []; this.clocked = false; return; }
    if (!this.clocked) return;
    this.clocked = false;
    const work = this.execute(t);
    this.busyUntil = t + work;
    this.board.edge('NFC_BUSY', this.busyUntil, 0);
  }

  // Full-duplex byte exchange while NSS is low. Returns MISO bytes.
  transfer(tx, t) {
    const n = tx.length;
    const rx = new Uint8Array(n).fill(0xFF);
    if (!this.powered) return rx.fill(0x00);
    if (this.nss !== 0) return rx;
    if (this.response) {
      rx.set(this.response.slice(0, n));
      this.response = this.response.length > n ? this.response.slice(n) : null;
      this.isReadFrame = true;
    } else {
      this.frame.push(...tx);
      this.isReadFrame = false;
    }
    if (!this.clocked) { this.clocked = true; this.board.edge('NFC_BUSY', t, 1); }
    return rx;
  }

  syncIrq(t) {
    this.pending = this.pending.filter(p => {
      if (p.t > t) return true;
      this.reg[PN.REG_IRQ_STATUS] |= p.bits;
      if (p.rx) { this.rxBuffer = p.rx; this.reg[PN.REG_RX_STATUS] = p.rx.length & 0x1FF; }
      return false;
    });
  }

  // Runs when NSS rises. Returns how long BUSY stays high, in microseconds.
  execute(t) {
    if (this.isReadFrame) return 20;
    const f = this.frame;
    const u32 = () => (f[2] | (f[3] << 8) | (f[4] << 16) | (f[5] << 24)) >>> 0;
    this.syncIrq(t);
    switch (f[0]) {
      case PN.WRITE_REGISTER:
        if (f[1] === PN.REG_IRQ_CLEAR) this.reg[PN.REG_IRQ_STATUS] &= ~u32();
        else this.reg[f[1] & 0x3F] = u32();
        return 30;
      case PN.WRITE_REGISTER_OR_MASK:
        this.reg[f[1] & 0x3F] |= u32();
        return 30;
      case PN.WRITE_REGISTER_AND_MASK:
        this.reg[f[1] & 0x3F] &= u32();
        return 30;
      case PN.READ_REGISTER: {
        const v = this.reg[f[1] & 0x3F];
        this.response = [v & 0xFF, (v >>> 8) & 0xFF, (v >>> 16) & 0xFF, (v >>> 24) & 0xFF];
        return 30;
      }
      case PN.READ_EEPROM:
        this.response = Array.from(this.eeprom.subarray(f[1], f[1] + f[2]));
        return 40;
      case PN.LOAD_RF_CONFIG:
        this.rfConfig = [f[1], f[2]];
        return 250;
      case PN.RF_ON:
        this.rfOn = true;
        this.rfOnSince = t;
        this.reg[PN.REG_IRQ_STATUS] |= PN.IRQ_TX_RFON;
        this.board.rfField(true, t);
        return 400;
      case PN.RF_OFF:
        this.rfOn = false;
        this.reg[PN.REG_IRQ_STATUS] |= PN.IRQ_TX_RFOFF;
        this.board.rfField(false, t);
        return 100;
      case PN.SEND_DATA:
        this.sendData(f.slice(2), t);
        return 40;
      case PN.READ_DATA:
        this.response = this.rxBuffer.slice();
        return 30;
      default:
        return 30;
    }
  }

  sendData(req, t) {
    const transceive = (this.reg[PN.REG_SYSTEM_CONFIG] & 0x07) === 0x03;
    if (!this.rfOn || !transceive) return;
    const txEnd = t + 150 + (req.length + 2) * 8 * BIT_US_15693;
    this.pending.push({ t: txEnd, bits: PN.IRQ_TX });

    const iso15693 = this.rfConfig && this.rfConfig[0] === 0x0D && this.rfConfig[1] === 0x8D;
    const tagAwake = this.tag && t - this.rfOnSince >= 1000;   // a passive tag needs about 1 ms of field to power up
    const resp = iso15693 && tagAwake ? this.tag.respond(req) : null;
    let end = txEnd;
    if (resp) {
      const sof = txEnd + 320;
      end = sof + 150 + (resp.length + 2) * 8 * BIT_US_15693;
      this.pending.push({ t: sof, bits: PN.IRQ_RX_SOF });
      this.pending.push({ t: end, bits: PN.IRQ_RX | PN.IRQ_IDLE, rx: resp });
    }
    this.board.record({ bus: 'rf', t0: t, t1: end, req: Uint8Array.from(req), resp: resp ? Uint8Array.from(resp) : null });
  }
}

// ---------------------------------------------------------------------------
// LIS2DH12 accelerometer
// ---------------------------------------------------------------------------
export class LIS2DH12 {
  constructor(board, addr) {
    this.board = board;
    this.addr = addr;
    this.reg = new Uint8Array(0x40);
    this.reg[0x0F] = 0x33;              // WHO_AM_I
    this.reg[0x20] = 0x07;              // CTRL_REG1 default: powered down, axes enabled
    this.pointer = 0;
    this.sample = [0, 0, 1];            // g
    this.reference = [0, 0, 1];         // slow average the high-pass filter subtracts
    this.latched = false;
    this.lastUpdate = 0;
    this.int1 = 0;
  }

  get fullScale() { return (this.reg[0x23] >> 4) & 3; }
  get mgPerCount() { return [1, 2, 4, 12][this.fullScale]; }
  get thresholdMg() { return (this.reg[0x32] & 0x7F) * [16, 32, 62, 186][this.fullScale]; }

  // Advance the interrupt logic to time t. Called on every bus access and
  // on a timer while the MCU sleeps.
  update(t) {
    const odrOn = (this.reg[0x20] >> 4) !== 0;
    while (this.lastUpdate + 10000 <= t) {
      this.lastUpdate += 10000;
      if (!odrOn) continue;
      const a = this.board.motion.accelAt(this.lastUpdate);
      this.sample = a;
      const cfg = this.reg[0x30];
      let active = false;
      for (let i = 0; i < 3; i++) {
        const hp = (this.reg[0x21] & 0x01) ? a[i] - this.reference[i] : a[i];
        this.reference[i] += (a[i] - this.reference[i]) * 0.02;
        if ((cfg >> (i * 2 + 1)) & 1 && Math.abs(hp) * 1000 > this.thresholdMg) active = true;
      }
      const latch = this.reg[0x24] & 0x08;
      if (active) this.latched = true;
      else if (!latch) this.latched = false;
      const level = this.latched && (this.reg[0x22] & 0x40) ? 1 : 0;
      if (level !== this.int1) { this.int1 = level; this.board.edge('IMU_INT1', this.lastUpdate, level); }
    }
  }

  write(bytes, t) {
    this.update(t);
    if (!bytes.length) return;
    this.pointer = bytes[0];
    for (let i = 1; i < bytes.length; i++) {
      const r = this.pointer & 0x7F;
      if (r >= 0x1E && r <= 0x3F && r !== 0x27 && r !== 0x31) this.reg[r] = bytes[i];
      if (this.pointer & 0x80) this.pointer = 0x80 | ((r + 1) & 0x7F);
    }
  }

  read(n, t) {
    this.update(t);
    const out = new Uint8Array(n);
    for (let i = 0; i < n; i++) {
      const r = this.pointer & 0x7F;
      out[i] = this.readReg(r, t);
      if (this.pointer & 0x80) this.pointer = 0x80 | ((r + 1) & 0x7F);
    }
    return out;
  }

  readReg(r, t) {
    if (r >= 0x28 && r <= 0x2D) {
      if (r === 0x28) {
        // Latch a fresh conversion at the start of a burst (block data update).
        const a = this.board.motion.accelAt(t);
        const limit = 2047;
        this.out = a.map(g => Math.max(-limit - 1, Math.min(limit, Math.round(g * 1000 / this.mgPerCount))) << 4);
      }
      const v = (this.out ?? [0, 0, 0])[(r - 0x28) >> 1] & 0xFFFF;
      return (r & 1) ? v >> 8 : v & 0xFF;
    }
    if (r === 0x26) { this.reference = this.sample.slice(); return this.reg[r]; }   // REFERENCE read resets the filter
    if (r === 0x31) {                                                              // INT1_SRC read clears the latch
      const v = this.latched ? 0x40 : 0x00;
      this.latched = false;
      if (this.int1) { this.int1 = 0; this.board.edge('IMU_INT1', t, 0); }
      return v;
    }
    if (r === 0x27) return 0x0F;
    return this.reg[r];
  }
}

// ---------------------------------------------------------------------------
// TCS34725 colour sensor
// ---------------------------------------------------------------------------
export class TCS34725 {
  constructor(board, addr) {
    this.board = board;
    this.addr = addr;
    this.reg = new Uint8Array(0x20);
    this.reg[0x01] = 0xFF;              // ATIME: 1 cycle
    this.reg[0x12] = 0x44;              // ID
    this.pointer = 0;
    this.autoInc = false;
    this.enabledAt = 0;
    this.data = [0, 0, 0, 0];
  }

  write(bytes, t) {
    if (!bytes.length) return;
    const cmd = bytes[0];
    if (!(cmd & 0x80)) return;
    this.pointer = cmd & 0x1F;
    this.autoInc = (cmd & 0x60) === 0x20;
    for (let i = 1; i < bytes.length; i++) {
      const r = this.pointer;
      if (r === 0x00 && (bytes[i] & 0x03) === 0x03 && (this.reg[0] & 0x03) !== 0x03) this.enabledAt = t;
      if (r <= 0x0F) this.reg[r] = bytes[i];
      if (this.autoInc) this.pointer = (r + 1) & 0x1F;
    }
  }

  convert(t) {
    const on = (this.reg[0] & 0x03) === 0x03;
    const cycles = 256 - this.reg[0x01];
    const integrationUs = cycles * 2400;
    if (!on) { this.data = [0, 0, 0, 0]; return false; }
    if (t - this.enabledAt < integrationUs + 2400) return false;   // first conversion not finished
    const gain = [1, 4, 16, 60][this.reg[0x0F] & 3];
    const scene = this.board.scene;
    const lamp = this.board.pixels.level(8);                        // the pixel beside the sensor, 0..1
    const max = Math.min(65535, cycles * 1024);
    const k = cycles * gain * 60;
    const noise = () => 1 + (this.board.random() - 0.5) * 0.04;
    let rgb;
    if (scene.swatch) rgb = scene.swatch.map(refl => refl * (scene.ambient + lamp) * k * noise());
    else rgb = [0.5, 0.5, 0.5].map(v => v * scene.ambient * k * noise());
    const clear = rgb[0] + rgb[1] + rgb[2];
    this.data = [clear, ...rgb].map(v => Math.max(0, Math.min(max, Math.round(v))));
    return true;
  }

  read(n, t) {
    const out = new Uint8Array(n);
    const valid = this.convert(t);
    for (let i = 0; i < n; i++) {
      const r = this.pointer;
      if (r >= 0x14 && r <= 0x1B) {
        const v = this.data[(r - 0x14) >> 1];
        out[i] = (r & 1) ? v >> 8 : v & 0xFF;
      } else if (r === 0x13) {
        out[i] = valid ? 0x01 : 0x00;
      } else {
        out[i] = this.reg[r];
      }
      if (this.autoInc) this.pointer = (r + 1) & 0x1F;
    }
    return out;
  }
}

// ---------------------------------------------------------------------------
// MAX17048 fuel gauge (reads the battery model)
// ---------------------------------------------------------------------------
export class MAX17048 {
  constructor(board, addr) {
    this.board = board;
    this.addr = addr;
    this.pointer = 0;
  }

  write(bytes) { if (bytes.length) this.pointer = bytes[0]; }

  read(n) {
    const b = this.board.battery;
    const word = r => {
      switch (r) {
        case 0x02: return Math.round(b.volts * 1e6 / 78.125) & 0xFFFF;       // VCELL
        case 0x04: return Math.round(b.soc * 256) & 0xFFFF;                   // SOC, 1/256 %
        case 0x08: return 0x0012;                                             // VERSION
        case 0x16: return Math.round(b.ratePctPerHour / 0.208) & 0xFFFF;      // CRATE
        default: return 0;
      }
    };
    const out = new Uint8Array(n);
    for (let i = 0; i < n; i++) {
      const r = (this.pointer + i) & 0xFF;
      const w = word(r & 0xFE);
      out[i] = (r & 1) ? w & 0xFF : w >> 8;                                   // big-endian
    }
    return out;
  }
}

// ---------------------------------------------------------------------------
// SK6805 pixel chain
// ---------------------------------------------------------------------------
export class PixelChain {
  constructor(count) {
    this.count = count;
    this.rgb = new Uint8Array(count * 3);
    this.powered = false;
  }

  setPower(on) {
    this.powered = on;
    if (!on) this.rgb.fill(0);
  }

  // GRB bytes in, as they arrive on the data pin.
  shift(grb) {
    if (!this.powered) return;
    for (let i = 0; i < this.count && i * 3 + 2 < grb.length; i++) {
      this.rgb[i * 3] = grb[i * 3 + 1];
      this.rgb[i * 3 + 1] = grb[i * 3];
      this.rgb[i * 3 + 2] = grb[i * 3 + 2];
    }
  }

  level(i) { return (this.rgb[i * 3] + this.rgb[i * 3 + 1] + this.rgb[i * 3 + 2]) / 765; }
  sum() { let s = 0; for (const v of this.rgb) s += v; return s / 255; }
}

// ---------------------------------------------------------------------------
// Battery, charger and an estimate of what everything draws
// ---------------------------------------------------------------------------
// Typical figures from the part datasheets. They are estimates for sizing the
// battery, not measurements of a built board.
export const CURRENT_MA = {
  mcuActive: 20,            // ESP32-C3, CPU running, radio idle
  mcuDeepSleep: 0.005,
  alwaysOn: 0.06,           // regulator, accelerometer in low-rate mode, fuel gauge, colour sensor asleep
  readerIdle: 7,            // PN5180 powered, field off
  readerField: 75,          // extra while the 13.56 MHz field is on
  pixelIdle: 0.5,           // per pixel, dark
  pixelFull: 4,             // per colour channel at full brightness on 3.3 V
  ampIdle: 2.4,
  ampFullScale: 180,        // peak into 8 ohm from a full-scale sine at 3.7 V
  colourActive: 0.24,
  charge: 50,
};

export class Battery {
  constructor(capacityMah = 100) {
    this.capacityMah = capacityMah;
    this.soc = 80;                      // percent
    this.usb = false;
    this.loadMa = 0;                    // smoothed, for display
    this.ratePctPerHour = 0;
  }

  get volts() {
    // Typical Li-Po open-circuit curve.
    const curve = [[0, 3.0], [5, 3.45], [10, 3.6], [25, 3.7], [50, 3.8], [75, 3.95], [90, 4.1], [100, 4.2]];
    for (let i = 1; i < curve.length; i++) {
      if (this.soc <= curve[i][0]) {
        const [s0, v0] = curve[i - 1], [s1, v1] = curve[i];
        return v0 + (v1 - v0) * (this.soc - s0) / (s1 - s0);
      }
    }
    return 4.2;
  }

  step(dtUs, loadMa) {
    const hours = dtUs / 3.6e9;
    const net = (this.usb && this.soc < 100 ? CURRENT_MA.charge : 0) - (this.usb ? 0 : loadMa);
    this.soc = Math.max(0, Math.min(100, this.soc + net * hours / this.capacityMah * 100));
    this.ratePctPerHour = net / this.capacityMah * 100;
    this.loadMa += (loadMa - this.loadMa) * Math.min(1, dtUs / 300000);
  }
}

// ---------------------------------------------------------------------------
// What the brick is being put through: orientation plus gestures, expressed
// as the acceleration the sensor would feel (in g, brick axes: x along the
// long side, y across, z up through the studs).
// ---------------------------------------------------------------------------
const HALF_SINE = (u) => Math.sin(Math.PI * u);

export const GESTURES = {
  // name: { ms, accel(u, s) -> [x, y, z] linear acceleration in g, u = 0..1 }
  shake:  { ms: 800, accel: (u, s) => [2.2 * Math.sin(2 * Math.PI * 7 * s) * HALF_SINE(Math.min(1, u * 1.2)), 0, 0] },
  swing:  { ms: 600, accel: (u) => [0, 1.5 * Math.sin(2 * Math.PI * u), 0.3 * Math.sin(2 * Math.PI * u)] },
  impact: { ms: 50,  accel: () => [0.6, 0.4, 4.2] },
  throw:  { ms: 700, accel: (u) => u < 0.2 ? [0, 0, 1.6 * HALF_SINE(u / 0.2)] : u < 0.86 ? [0, 0, -1] : u < 0.94 ? [0.3, 0.2, 3.6] : [0, 0, 0] },
};

export class Motion {
  constructor(random) {
    this.random = random;
    this.tilt = 0;                      // radians, about the short axis
    this.flip = 0;                      // radians, about the long axis
    this.tiltFrom = 0; this.tiltTo = 0; this.flipFrom = 0; this.flipTo = 0;
    this.turnStart = -1e12; this.turnUs = 1;
    this.active = [];                   // [{g, t0}]
    this.override = null;               // [x, y, z] from a real device sensor, or null
    this.noiseG = 0.006;
  }

  setOrientation(tilt, flip, t, ms = 350) {
    const now = this.orientationAt(t);
    this.tiltFrom = now[0]; this.flipFrom = now[1];
    this.tiltTo = tilt; this.flipTo = flip;
    this.turnStart = t; this.turnUs = ms * 1000;
  }

  orientationAt(t) {
    let u = Math.max(0, Math.min(1, (t - this.turnStart) / this.turnUs));
    u = u * u * (3 - 2 * u);
    return [this.tiltFrom + (this.tiltTo - this.tiltFrom) * u, this.flipFrom + (this.flipTo - this.flipFrom) * u];
  }

  gesture(name, t) {
    if (GESTURES[name]) this.active.push({ g: GESTURES[name], t0: t });
  }

  accelAt(t) {
    if (this.override) return this.override;
    const [tilt, flip] = this.orientationAt(t);
    const a = [Math.sin(tilt), Math.sin(flip) * Math.cos(tilt), Math.cos(flip) * Math.cos(tilt)];
    this.active = this.active.filter(x => t - x.t0 < x.g.ms * 1000 + 50000);
    for (const { g, t0 } of this.active) {
      const s = (t - t0) / 1e6, u = s * 1000 / g.ms;
      if (u < 0 || u > 1) continue;
      const lin = g.accel(u, s);
      a[0] += lin[0]; a[1] += lin[1]; a[2] += lin[2];
    }
    for (let i = 0; i < 3; i++) a[i] += (this.random() - 0.5) * 2 * this.noiseG;
    return a;
  }
}
