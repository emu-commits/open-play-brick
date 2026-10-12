// Logic analyzer view. The board records each bus transaction with its start
// and end time; this expands them into pin waveforms for whatever stretch of
// time is on screen, down to single bits.

import { BUS_COLOUR } from './diagram.js';

const ROWS = [
  { net: 'SPI_SCK', bus: 'spi', role: 'sck' },
  { net: 'SPI_MOSI', bus: 'spi', role: 'tx' },
  { net: 'SPI_MISO', bus: 'spi', role: 'rx' },
  { net: 'NFC_NSS', bus: 'spi', idle: 1 },
  { net: 'NFC_BUSY', bus: 'spi' },
  { net: 'RF_FIELD', bus: 'rf' },
  { net: 'I2C_SCL', bus: 'i2c', role: 'scl', idle: 1 },
  { net: 'I2C_SDA', bus: 'i2c', role: 'sda', idle: 1 },
  { net: 'IMU_INT1', bus: 'gpio' },
  { net: 'LED_DATA', bus: 'led', role: 'led' },
  { net: 'I2S_BCLK', bus: 'i2s', role: 'bclk' },
  { net: 'I2S_LRCLK', bus: 'i2s', role: 'lrclk' },
  { net: 'I2S_DOUT', bus: 'i2s', role: 'dout' },
  { net: 'PERIPH_EN_N', bus: 'gpio', idle: 1 },
];
const LABEL_W = 104, ROW_H = 21, TOP = 20;
const hex2 = v => v.toString(16).toUpperCase().padStart(2, '0');

// Bit-slot descriptions per bus. slot(rec, k) -> [levelFirstHalf, levelSecondHalf].
const BUS = {
  spi: {
    slots: r => r.tx.length * 8,
    level(r, role, k) {
      if (role === 'sck') return [0, 1];
      const byte = (role === 'tx' ? r.tx : r.rx)[k >> 3];
      const bit = (byte >> (7 - (k & 7))) & 1;
      return [bit, bit];
    },
    group: 8,
    text: (r, role, g) => role === 'sck' ? null : hex2((role === 'tx' ? r.tx : r.rx)[g]),
  },
  led: {
    slots: r => r.grb.length * 8,
    level(r, role, k) {
      const bit = (r.grb[k >> 3] >> (7 - (k & 7))) & 1;
      return bit ? [1, 0, 0.48] : [1, 0, 0.24];      // third value: fraction of the slot spent high
    },
    group: 8,
    text: (r, role, g) => hex2(r.grb[g]),
  },
  i2s: {
    slots: r => r.samples.length * 32,
    level(r, role, k) {
      if (role === 'bclk') return [0, 1];
      const pos = k & 31;
      if (role === 'lrclk') return pos < 16 ? [0, 0] : [1, 1];
      const j = pos - 1;                              // I2S: data is one clock late
      const bit = j >= 0 && j < 16 ? ((r.samples[k >> 5] & 0xFFFF) >> (15 - j)) & 1 : 0;
      return [bit, bit];
    },
    group: 32,
    text: (r, role, g) => role === 'dout' ? String(r.samples[g]) : null,
  },
  i2c: {
    slots: r => layoutI2c(r).length,
    level(r, role, k) {
      const s = layoutI2c(r)[k];
      if (role === 'scl') return s.edge ? [1, 1] : [0, 1];
      return s.edge ? s.edge : [s.bit, s.bit];
    },
    group: 0,
    text: null,
  },
};

function layoutI2c(r) {
  if (r._slots) return r._slots;
  const slots = [];
  const byte = (v, ack, label) => {
    const first = slots.length;
    for (let i = 7; i >= 0; i--) slots.push({ bit: (v >> i) & 1 });
    slots.push({ bit: ack ? 0 : 1, ack: true });
    slots[first].label = label;
    slots[first].span = 9;
  };
  slots.push({ edge: [1, 0] });                                          // START
  byte(r.addr << 1, !r.nack, `${hex2(r.addr << 1)} W`);
  if (!r.nack) {
    for (const b of r.wr) byte(b, true, hex2(b));
    if (r.rd.length) {
      slots.push({ edge: [1, 0] });                                      // repeated START
      byte((r.addr << 1) | 1, true, `${hex2((r.addr << 1) | 1)} R`);
      r.rd.forEach((b, i) => byte(b, i < r.rd.length - 1, hex2(b)));
    }
  }
  slots.push({ edge: [0, 1] });                                          // STOP
  return (r._slots = slots);
}

export class Analyzer {
  constructor(canvas, board, readout) {
    this.canvas = canvas;
    this.board = board;
    this.readout = readout;
    this.ctx = canvas.getContext('2d');
    this.span = 2_000_000;
    this.end = 0;
    this.follow = true;
    this.cursor = null;
    this.onFollowChange = () => {};
    canvas.height = TOP + ROWS.length * ROW_H + 6;
    this.height = canvas.height;

    canvas.addEventListener('wheel', e => {
      e.preventDefault();
      const t = this.timeAt(e.offsetX);
      const factor = e.deltaY > 0 ? 1.35 : 1 / 1.35;
      const span = Math.max(8, Math.min(60e6, this.span * factor));
      this.end = t + (this.end - t) * (span / this.span);
      this.span = span;
      this.setFollow(false);
    }, { passive: false });
    let drag = null;
    canvas.addEventListener('pointerdown', e => { drag = { x: e.clientX, end: this.end }; canvas.setPointerCapture(e.pointerId); });
    canvas.addEventListener('pointermove', e => {
      this.cursor = e.offsetX;
      if (!drag) return;
      const dx = e.clientX - drag.x;
      if (Math.abs(dx) > 3) this.setFollow(false);
      this.end = drag.end - dx * this.span / this.plotW;
    });
    canvas.addEventListener('pointerup', () => { drag = null; });
    canvas.addEventListener('pointerleave', () => { this.cursor = null; });
  }

  get plotW() { return this.canvas.clientWidth - LABEL_W; }
  timeAt(x) { return this.end - this.span + (x - LABEL_W) / this.plotW * this.span; }
  setFollow(on) { this.follow = on; this.onFollowChange(on); }
  setSpan(us) { const mid = this.end - this.span / 2; this.span = us; if (!this.follow) this.end = mid + us / 2; }

  // Frame a stretch of time with a little margin.
  frame(t0, t1) {
    const len = Math.max(20, t1 - t0);
    this.span = len * 1.3;
    this.end = t1 + len * 0.15;
    this.setFollow(false);
  }

  jumpTo(bus) {
    const trace = this.board.trace;
    for (let i = trace.length - 1; i >= 0; i--) {
      const r = trace[i];
      if (r.bus !== bus || r.t0 > this.board.t) continue;
      let t0 = r.t0, t1 = r.t1;
      if (bus === 'spi') {                       // show the whole chip-select frame
        t0 -= 6; t1 += 30;
      } else if (bus === 'i2s') {
        t1 = t0 + 4 * 62.5;                      // a few samples
      }
      this.frame(t0, t1);
      return true;
    }
    return false;
  }

  draw() {
    const { canvas, ctx, board } = this;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = this.height;
    if (canvas.width !== Math.round(w * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); canvas.style.height = h + 'px'; }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (this.follow) this.end = board.t;
    const a = this.end - this.span, b = this.end, plotW = w - LABEL_W;
    const X = t => LABEL_W + (t - a) / this.span * plotW;
    const css = getComputedStyle(canvas);
    const ink = css.getPropertyValue('--ink').trim() || '#cdd6e4', dim = css.getPropertyValue('--dim').trim() || '#6b7689';
    const grid = css.getPropertyValue('--grid').trim() || '#232b38';

    ctx.clearRect(0, 0, w, h);
    ctx.font = '11px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';
    ctx.textBaseline = 'middle';

    // Time grid.
    const step = niceStep(this.span / 6);
    ctx.strokeStyle = grid; ctx.fillStyle = dim; ctx.lineWidth = 1; ctx.textAlign = 'left';
    for (let t = Math.ceil(a / step) * step; t < b; t += step) {
      const x = Math.round(X(t)) + 0.5;
      ctx.beginPath(); ctx.moveTo(x, TOP - 4); ctx.lineTo(x, h); ctx.stroke();
      ctx.fillText(formatTime(t, step), x + 3, 8);
    }

    const visible = {};
    for (const r of board.trace) {
      if (r.t1 < a || r.t0 > b || !BUS[r.bus]) continue;
      (visible[r.bus] ??= []).push(r);
    }

    ROWS.forEach((row, i) => {
      const yLow = TOP + i * ROW_H + ROW_H - 5, yHigh = TOP + i * ROW_H + 5;
      const Y = v => (v ? yHigh : yLow);
      const colour = BUS_COLOUR[row.bus];
      ctx.fillStyle = ink; ctx.textAlign = 'right';
      ctx.fillText(row.net, LABEL_W - 8, (yLow + yHigh) / 2);
      ctx.strokeStyle = colour; ctx.fillStyle = colour; ctx.lineWidth = 1.3;

      ctx.save();
      ctx.beginPath(); ctx.rect(LABEL_W, TOP + i * ROW_H, plotW, ROW_H); ctx.clip();
      ctx.beginPath();
      let level = row.idle ?? 0, started = false;
      const to = (t, v) => {
        const x = X(t);
        if (!started) { ctx.moveTo(LABEL_W, Y(level)); started = true; }
        ctx.lineTo(x, Y(level));
        if (v !== level) ctx.lineTo(x, Y(v));
        level = v;
      };

      if (!row.role) {
        const edges = board.edges[row.net] ?? [];
        let k = lowerBound(edges, a);
        if (k > 0) level = edges[k - 1].level;
        for (; k < edges.length && edges[k].t <= b; k++) to(edges[k].t, edges[k].level);
      } else {
        const def = BUS[row.bus];
        const labels = [];
        for (const r of visible[row.bus] ?? []) {
          const n = def.slots(r);
          const slotUs = (r.t1 - r.t0 - (row.bus === 'led' ? 80 : 0)) / n;
          const px = slotUs / this.span * plotW;
          if (px < 2.5) {                        // too dense to draw bits: show a busy block
            const x0 = Math.max(LABEL_W, X(r.t0)), x1 = Math.min(w, X(r.t0 + n * slotUs));
            to(r.t0, row.idle ?? 0);
            ctx.globalAlpha = 0.45; ctx.fillRect(x0, yHigh, Math.max(1, x1 - x0), yLow - yHigh); ctx.globalAlpha = 1;
            continue;
          }
          const k0 = Math.max(0, Math.floor((a - r.t0) / slotUs)), k1 = Math.min(n - 1, Math.ceil((b - r.t0) / slotUs));
          for (let k = k0; k <= k1; k++) {
            const t = r.t0 + k * slotUs;
            const [first, second, frac] = def.level(r, row.role, k);
            to(t, first);
            if (second !== first) to(t + slotUs * (frac ?? 0.5), second);
            if (px * 8 >= 26) {
              if (row.bus === 'i2c') {
                const s = layoutI2c(r)[k];
                if (s.label && row.role === 'sda') labels.push([t + slotUs * 4.5, s.label]);
              } else if (def.text && k % def.group === 0) {
                const text = def.text(r, row.role, k / def.group);
                if (text != null && px * def.group >= 26) labels.push([t + slotUs * def.group / 2, text]);
              }
            }
          }
          to(r.t0 + n * slotUs, row.idle ?? 0);
        }
        if (!started) ctx.moveTo(LABEL_W, Y(level));
        ctx.lineTo(w, Y(level));
        ctx.stroke();
        ctx.textAlign = 'center';
        const panel = css.getPropertyValue('--panel').trim() || '#131922';
        for (const [t, text] of labels) {
          const x = X(t), tw = ctx.measureText(text).width + 6;
          ctx.globalAlpha = 0.82; ctx.fillStyle = panel;
          ctx.fillRect(x - tw / 2, (yLow + yHigh) / 2 - 6, tw, 12);
          ctx.globalAlpha = 1; ctx.fillStyle = ink;
          ctx.fillText(text, x, (yLow + yHigh) / 2 + 0.5);
        }
        ctx.restore();
        return;
      }
      if (!started) ctx.moveTo(LABEL_W, Y(level));
      ctx.lineTo(w, Y(level));
      ctx.stroke();
      ctx.restore();
    });

    // "Now" marker and cursor.
    if (board.t >= a && board.t <= b) {
      ctx.strokeStyle = ink; ctx.globalAlpha = 0.35; ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(X(board.t), TOP - 4); ctx.lineTo(X(board.t), h); ctx.stroke();
      ctx.setLineDash([]); ctx.globalAlpha = 1;
    }
    let text = `window ${formatSpan(this.span)}`;
    if (this.cursor != null && this.cursor > LABEL_W) {
      ctx.strokeStyle = dim;
      ctx.beginPath(); ctx.moveTo(this.cursor + 0.5, TOP - 4); ctx.lineTo(this.cursor + 0.5, h); ctx.stroke();
      text += ` · cursor at ${(this.timeAt(this.cursor) / 1e6).toFixed(6)} s`;
    }
    this.readout.textContent = text;
  }
}

function lowerBound(list, t) {
  let lo = 0, hi = list.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (list[mid].t < t) lo = mid + 1; else hi = mid; }
  return lo;
}

function niceStep(raw) {
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const m = raw / p;
  return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p;
}

function formatTime(us, step) {
  if (step >= 1e5) return (us / 1e6).toFixed(1) + ' s';
  if (step >= 100) return (us / 1e3).toFixed(step >= 1e4 ? 0 : step >= 1e3 ? 0 : 1) + ' ms';
  return (us / 1e3).toFixed(step >= 10 ? 2 : 3) + ' ms';
}

export function formatSpan(us) {
  if (us >= 1e6) return (us / 1e6).toFixed(us >= 1e7 ? 0 : 1) + ' s';
  if (us >= 1e3) return (us / 1e3).toFixed(us >= 1e4 ? 0 : 1) + ' ms';
  return us.toFixed(0) + ' µs';
}
