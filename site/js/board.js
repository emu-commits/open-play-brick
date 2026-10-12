// The simulated board. It loads the firmware (the same C code that runs on
// the ESP32-C6, compiled to WebAssembly), implements the firmware's hardware
// calls as activity on named nets, and routes that activity to the chip
// models. Everything is timed on a virtual clock in microseconds.
//
// No DOM here: the browser UI and the Node tests both drive this class.

import { PN5180, LIS3DH, TCS34725, MAX17048, PixelChain, Microphone, Battery, Motion, Iso15693Tag, CURRENT_MA } from './chips.js';

export const TIMING = {
  spiHz: 2_000_000,
  i2cHz: 400_000,
  ledBitUs: 1.25,
  ledResetUs: 80,
  i2sRate: 16_000,
  i2sBufferSamples: 2048,
};

const MODE_INPUT = 0, MODE_OUTPUT = 1;
const PULLED_UP = new Set(['I2C_SDA', 'I2C_SCL']);
const TRACE_MAX = 24000, EDGE_MAX = 4000;

export const STATES = ['Boot', 'Idle', 'Tag active', 'Gesture response', 'Charging', 'Low battery', 'Asleep'];

export class Board {
  constructor({ netlist, catalog, wasm, seed = 12345 }) {
    this.netlist = netlist;
    this.catalog = catalog;                       // Uint8Array, the flash data partition
    this.module = wasm instanceof WebAssembly.Module ? wasm : new WebAssembly.Module(wasm);
    this.gpioNet = {};
    for (const [net, gpio] of Object.entries(netlist.gpio)) this.gpioNet[gpio] = net;

    let x = seed >>> 0 || 1;
    this.random = () => { x ^= x << 13; x >>>= 0; x ^= x >>> 17; x ^= x << 5; x >>>= 0; return x / 4294967296; };

    this.t = 0;
    this.trace = [];
    this.edges = {};
    this.level = {};
    this.listeners = { log: [], audio: [], radio: [], reset: [] };

    const addr = name => parseInt(netlist.parts.find(p => p.name === name).i2c, 16);
    this.motion = new Motion(this.random);
    this.scene = { swatch: null, ambient: 0.05 };
    this.battery = new Battery();
    this.pixels = new PixelChain(8);
    this.mic = new Microphone(this);
    this.nfc = new PN5180(this);
    this.imu = new LIS3DH(this, addr('LIS3DH'));
    this.colour = new TCS34725(this, addr('TCS34725'));
    this.gauge = new MAX17048(this, addr('MAX17048'));
    this.i2cDevices = [this.imu, this.colour, this.gauge];

    this.rail = false;                            // pixel supply and amplifier enable
    this.hold = new Set();                        // pins frozen through deep sleep
    this.micPos = null;
    this.rfOn = false;
    this.asleep = false;
    this.i2sEnd = 0;
    this.loudUntil = 0;
    this.ampLevel = 0;
    this.bootCount = 0;
  }

  on(event, fn) { this.listeners[event].push(fn); }
  emit(event, ...args) { for (const fn of this.listeners[event]) fn(...args); }

  // ---- nets and trace ----------------------------------------------------

  edge(net, t, level) {
    const list = this.edges[net] ??= [];
    if (list.length && list[list.length - 1].t > t) {
      let i = list.length;
      while (i > 0 && list[i - 1].t > t) i--;
      list.splice(i, 0, { t, level });
    } else {
      list.push({ t, level });
    }
    if (list.length > EDGE_MAX) list.splice(0, list.length - EDGE_MAX + 500);
    this.onEdge?.(net);
  }

  setNet(net, level) {
    if (this.level[net] === level) return;
    this.level[net] = level;
    this.edge(net, this.t, level);
    if (net === 'PERIPH_EN') this.setRail(level === 1);
    else if (net === 'NFC_RST') this.nfc.setReset(level, this.t);
    else if (net === 'NFC_NSS') this.nfc.setNss(level, this.t);
  }

  setRail(on) {
    if (on === this.rail) return;
    this.rail = on;
    this.pixels.setPower(on);
  }

  rfField(on, t) {
    this.rfOn = on;
    this.edge('RF_FIELD', t, on ? 1 : 0);
  }

  record(rec) {
    this.trace.push(rec);
    this.onRecord?.(rec);
    if (this.trace.length > TRACE_MAX) this.trace.splice(0, this.trace.length - TRACE_MAX + 1500);
  }

  // ---- time and power ----------------------------------------------------

  loadMa() {
    const c = CURRENT_MA;
    let ma = c.boardDeepSleep + (this.asleep ? 0 : c.mcuActive + c.micActive);
    if (this.level.QT_PWR) ma += c.sensorRail;
    if ((this.colour.reg[0] & 0x03) === 0x03) ma += c.colourActive;
    if (this.level.LAMP_EN) ma += c.lamp;
    if (this.radioOn) ma += c.radio;
    ma += this.nfc.powered ? c.readerIdle + (this.rfOn ? c.readerField : 0) : c.readerDown;
    if (this.rail) {
      ma += this.pixels.count * c.pixelIdle + this.pixels.sum() * c.pixelFull;
      ma += c.ampIdle + (this.t < this.i2sEnd ? this.ampLevel * c.ampFullScale * 0.35 : 0);
    }
    return ma;
  }

  advance(us) {
    this.battery.step(us, this.loadMa());
    this.t += us;
  }

  // ---- firmware hardware calls -------------------------------------------

  imports() {
    const mem = () => new Uint8Array(this.wasm.exports.memory.buffer);
    const bytes = (ptr, len) => mem().slice(ptr, ptr + len);
    const cstr = ptr => {
      const m = mem();
      let end = ptr;
      while (m[end]) end++;
      return new TextDecoder().decode(m.subarray(ptr, end));
    };

    return {
      hal_gpio_mode: (pin, mode) => {
        const net = this.gpioNet[pin];
        this.mode[pin] = mode;
        this.advance(0.5);
        this.drive(pin);
      },
      hal_gpio_write: (pin, level) => {
        this.latch[pin] = level ? 1 : 0;
        this.advance(0.5);
        this.drive(pin);
      },
      hal_gpio_hold: (pin, on) => {
        if (on) this.hold.add(pin);
        else { this.hold.delete(pin); this.drive(pin); }
      },
      hal_gpio_read: (pin) => {
        const net = this.gpioNet[pin];
        this.advance(0.5);
        if (net === 'NFC_BUSY') return this.nfc.busy(this.t);
        if (net === 'IMU_INT1') { this.imu.update(this.t); return this.imu.int1; }
        return this.level[net] ?? 0;
      },
      hal_spi_transfer: (txPtr, rxPtr, len) => {
        const tx = txPtr ? bytes(txPtr, len) : new Uint8Array(len).fill(0xFF);
        const t0 = this.t;
        const rx = this.nfc.transfer(tx, t0);
        this.advance(len * 8 * 1e6 / TIMING.spiHz);
        if (rxPtr) mem().set(rx, rxPtr);
        this.record({ bus: 'spi', t0, t1: this.t, tx, rx, read: !txPtr });
      },
      hal_i2c_write: (addr, ptr, len) => this.i2c(addr, bytes(ptr, len), 0, 0),
      hal_i2c_write_read: (addr, wPtr, wLen, rPtr, rLen) => this.i2c(addr, bytes(wPtr, wLen), rPtr, rLen),
      hal_led_write: (ptr, n) => {
        const grb = bytes(ptr, n * 3);
        const t0 = this.t;
        this.advance(n * 24 * TIMING.ledBitUs + TIMING.ledResetUs);
        this.pixels.shift(grb);
        this.record({ bus: 'led', t0, t1: this.t, grb });
      },
      hal_i2s_space: () => {
        const queued = Math.max(0, this.i2sEnd - this.t) * TIMING.i2sRate / 1e6;
        return Math.floor(TIMING.i2sBufferSamples - queued);
      },
      hal_i2s_write: (ptr, n) => {
        const m = this.wasm.exports.memory.buffer;
        const samples = new Int16Array(m.slice(ptr, ptr + n * 2));
        const t0 = Math.max(this.t, this.i2sEnd);
        this.i2sEnd = t0 + n * 1e6 / TIMING.i2sRate;
        let peak = 0;
        for (const s of samples) peak = Math.max(peak, Math.abs(s));
        this.ampLevel = peak / 32768;
        if (peak > 0) this.loudUntil = this.i2sEnd;
        this.record({ bus: 'i2s', t0, t1: this.i2sEnd, samples, peak });
        if (this.micPos == null) this.micPos = t0;          // the microphone starts with the clocks
        if (this.rail && peak > 0) {                        // SD_MODE high: the amplifier is on
          this.mic.speaker(samples, t0);
          this.emit('audio', samples, t0);
        }
      },
      hal_i2s_read: (ptr, n) => {
        if (this.micPos == null) return 0;
        const period = 1e6 / TIMING.i2sRate;
        let waiting = (this.t - this.micPos) / period;
        if (waiting > TIMING.i2sBufferSamples) {            // receive buffer overran: oldest samples are lost
          this.micPos = this.t - TIMING.i2sBufferSamples * period;
          waiting = TIMING.i2sBufferSamples;
        }
        if (waiting < n) return 0;
        const samples = this.mic.capture(this.micPos, n);
        new Int16Array(this.wasm.exports.memory.buffer, ptr, n).set(samples);
        this.record({ bus: 'i2sin', t0: this.micPos, t1: this.micPos + n * period, samples });
        this.micPos += n * period;
        return n;
      },
      hal_millis: () => Math.floor(this.t / 1000) >>> 0,
      hal_delay_us: (us) => this.advance(us >>> 0),
      hal_log: (ptr) => this.log(cstr(ptr)),
      hal_storage_read: (offset, dst, len) => {
        const n = Math.max(0, Math.min(len, this.catalog.length - offset));
        mem().set(this.catalog.subarray(offset, offset + n), dst);
        return n;
      },
      hal_radio_enable: (on) => { this.radioOn = !!on; },
      hal_radio_send: (ptr, len) => {
        if (!this.radioOn) return;
        const data = bytes(ptr, len);
        this.record({ bus: 'radio', t0: this.t, t1: this.t + 600, dir: 'tx', data });
        this.emit('radio', data);
      },
      hal_deep_sleep: () => { this.asleep = true; },
    };
  }

  // Put a pin's mode and output latch onto its net, unless the pin is held.
  drive(pin) {
    if (this.hold.has(pin)) return;
    const net = this.gpioNet[pin];
    this.setNet(net, this.mode[pin] === MODE_OUTPUT ? this.latch[pin] ?? 0 : PULLED_UP.has(net) ? 1 : 0);
  }

  i2c(addr, wr, rdPtr, rdLen) {
    const t0 = this.t;
    // The bus pull-ups and the sensors hang off the switched connector supply.
    const dev = this.level.QT_PWR ? this.i2cDevices.find(d => d.addr === addr) : null;
    const bits = 1 + 9 * (1 + wr.length) + (rdLen ? 1 + 9 * (1 + rdLen) : 0) + 1;
    let rd = new Uint8Array(0);
    if (dev) {
      dev.write(wr, t0);
      if (rdLen) {
        rd = dev.read(rdLen, t0);
        new Uint8Array(this.wasm.exports.memory.buffer).set(rd, rdPtr);
      }
    }
    this.advance((dev ? bits : 10) * 1e6 / TIMING.i2cHz);
    this.record({ bus: 'i2c', t0, t1: this.t, addr, wr, rd, nack: !dev });
    return dev ? 0 : -1;
  }

  log(line) {
    this.record({ bus: 'log', t0: this.t, t1: this.t, line });
    this.emit('log', line, this.t);
  }

  // ---- lifecycle ---------------------------------------------------------

  // Power-on or wake from deep sleep: every GPIO is an input again and the
  // firmware starts from scratch with empty RAM.
  boot(reason = 'power on') {
    if (!/^wake/.test(reason)) this.hold.clear();   // only a wake from deep sleep keeps held pins
    this.mode = {};
    this.latch = {};
    this.asleep = false;
    this.radioOn = false;
    this.micPos = null;
    this.bootCount++;
    for (const pin of Object.keys(this.gpioNet)) this.drive(+pin);
    this.wasm = new WebAssembly.Instance(this.module, { env: this.imports() });
    this.emit('reset', reason);
    this.log(`--- reset: ${reason} ---`);
    this.wasm.exports.fw_init();
  }

  // Run the firmware until the virtual clock reaches `until` microseconds.
  run(until) {
    while (this.t < until) {
      if (this.asleep) {
        this.advance(Math.min(10000, until - this.t));
        this.imu.update(this.t);
        if (this.imu.int1) this.boot('wake on IMU_INT1');
        continue;
      }
      this.wasm.exports.fw_loop();
    }
  }

  runFor(ms) { this.run(this.t + ms * 1000); }

  status() {
    const p = this.wasm.exports.fw_status();
    const dv = new DataView(this.wasm.exports.memory.buffer, p, 60);
    const name = new Uint8Array(this.wasm.exports.memory.buffer, p + 32, 24);
    const end = name.indexOf(0);
    return {
      state: this.asleep ? 6 : dv.getUint8(0),
      tagPresent: !!dv.getUint8(1),
      tagIndex: dv.getUint8(2),
      tagExact: !!dv.getUint8(3),
      tagLen: dv.getUint8(4),
      tagKind: dv.getUint8(5),
      colour: dv.getUint8(6),
      hits: dv.getUint8(7),
      damaged: !!dv.getUint8(8),
      charging: !!dv.getUint8(9),
      soc: dv.getUint8(10),
      lastEvent: dv.getUint8(11),
      mv: dv.getUint16(12, true),
      accel: [dv.getInt16(14, true), dv.getInt16(16, true), dv.getInt16(18, true)],
      tagCrc: dv.getUint32(20, true),
      uid: Array.from(new Uint8Array(this.wasm.exports.memory.buffer, p + 24, 8)).reverse(),
      tagName: new TextDecoder().decode(name.subarray(0, end < 0 ? 24 : end)),
      micLevel: dv.getUint16(56, true),
      micFloor: dv.getUint16(58, true),
    };
  }

  // ---- the outside world -------------------------------------------------

  placeTag(tag) { this.nfc.tag = tag ? new Iso15693Tag(tag) : null; }
  removeTag() { this.nfc.tag = null; }

  radioReceive(data) {
    this.record({ bus: 'radio', t0: this.t, t1: this.t + 600, dir: 'rx', data: Uint8Array.from(data) });
    if (this.asleep || !this.radioOn) return;   // nobody is listening
    const ptr = this.wasm.exports.fw_radio_buffer();
    new Uint8Array(this.wasm.exports.memory.buffer).set(data, ptr);
    this.wasm.exports.fw_on_radio(ptr, data.length);
  }
}
