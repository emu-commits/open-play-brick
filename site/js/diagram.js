// Draws the wiring diagram from netlist.json and animates it from the
// board's live state. Only the placement of the boxes is decided here;
// which pin connects to which net comes from the netlist.

export const BUS_COLOUR = {
  spi: '#f2a93b', i2c: '#4cc9f0', i2s: '#c58cff', led: '#ff6b9a', gpio: '#9be564',
  usb: '#9aa5b8', rf: '#ffd166', audio: '#c58cff', power: '#ff7a59',
};
export const BUS_LABEL = { spi: 'SPI', i2c: 'I2C', i2s: 'I2S audio', led: 'Pixel data', gpio: 'GPIO', usb: 'USB', rf: 'RF', power: 'Power' };

const W = 1180, H = 880;

// x, y, w, h and the y position of each signal pin, by side.
const LAYOUT = {
  ANT1: { x: 12, y: 110, w: 146, h: 150, R: { LOOP: 205 } },
  U2:   { x: 172, y: 86, w: 174, h: 222, R: { SCK: 150, MOSI: 175, MISO: 200, NSS: 225, BUSY: 250, RESET_N: 275 }, L: { 'ANT1/2': 205 } },
  U3:   { x: 196, y: 318, w: 150, h: 128, R: { SDA: 377, SCL: 397, INT1: 417 } },
  U4:   { x: 196, y: 456, w: 150, h: 138, R: { LED: 524, SDA: 544, SCL: 564 } },
  U5:   { x: 196, y: 604, w: 150, h: 100, R: { SDA: 654, SCL: 674 } },
  U1:   { x: 500, y: 76, w: 180, h: 628,
          L: { GPIO21: 150, GPIO22: 175, GPIO23: 200, GPIO0: 225, GPIO2: 250, GPIO3: 275, GPIO19: 377, GPIO18: 397, GPIO1: 417, GPIO16: 524 },
          R: { GPIO5: 150, GPIO6: 175, GPIO7: 200, GPIO4: 308, GPIO14: 430, GPIO17: 542, GPIO13: 632, GPIO12: 657 } },
  U6:   { x: 834, y: 76, w: 150, h: 172, L: { BCLK: 150, LRCLK: 175, DIN: 200, SD_MODE: 222 }, R: { 'OUT+/-': 175 } },
  LS1:  { x: 1040, y: 110, w: 124, h: 110, L: { '+/-': 175 } },
  MK1:  { x: 834, y: 254, w: 150, h: 124, L: { DOUT: 308, BCLK: 328, LRCLK: 348 } },
  D1:   { x: 834, y: 384, w: 330, h: 96, L: { DIN: 430 } },
  Q1:   { x: 834, y: 488, w: 176, h: 88, L: { GATE: 542 } },
  J1:   { x: 834, y: 582, w: 150, h: 108, L: { 'D+': 632, 'D-': 657 } },
  U8:   { x: 290, y: 784, w: 160, h: 76 },
  BT1:  { x: 500, y: 784, w: 180, h: 76 },
  U7:   { x: 730, y: 784, w: 160, h: 76 },
};
const TRUNK_X = { I2C_SDA: 396, I2C_SCL: 426, I2S_BCLK: 716, I2S_LRCLK: 742, PERIPH_EN: 790 };
const SIGNAL_BUSES = new Set(['spi', 'i2c', 'i2s', 'led', 'gpio', 'usb', 'rf', 'audio']);

const NS = 'http://www.w3.org/2000/svg';
function el(name, attrs = {}, text) {
  const e = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text != null) e.textContent = text;
  return e;
}

export class Diagram {
  constructor(svg, netlist, { onPart, onNet }) {
    this.svg = svg;
    this.netlist = netlist;
    this.wires = {};          // net -> [path elements]
    this.dots = {};           // net -> level indicator
    this.heat = {};           // net -> last time (ms) it was active
    this.badges = {};
    svg.setAttribute('viewBox', `0 64 ${W} ${H - 64}`);

    const gWires = el('g', { class: 'wires' }), gParts = el('g', { class: 'parts' });
    svg.append(gWires, gParts);

    // Where each net touches each part.
    const ends = {};
    for (const part of netlist.parts) {
      const lay = LAYOUT[part.id];
      if (!lay) continue;
      for (const [pin, net] of part.pins) {
        for (const side of ['L', 'R']) {
          if (lay[side]?.[pin] != null) {
            (ends[net] ??= []).push({ part: part.id, pin, side, x: side === 'L' ? lay.x : lay.x + lay.w, y: lay[side][pin] });
          }
        }
      }
    }

    for (const [net, list] of Object.entries(ends)) {
      const bus = netlist.nets[net]?.bus;
      if (!SIGNAL_BUSES.has(bus) || list.length < 2) continue;
      const colour = BUS_COLOUR[bus];
      const hub = list.find(e => e.part === 'U1') ?? list[0];
      const group = el('g', { class: 'net', 'data-net': net, style: `--c:${colour}` });
      const paths = [];
      const line = d => {
        const hit = el('path', { d, class: 'hit' });
        const p = el('path', { d, class: 'wire' });
        group.append(hit, p);
        paths.push(p);
      };
      const others = list.filter(e => e !== hub);
      const trunk = TRUNK_X[net] ?? (hub.x + others[0].x) / 2;
      others.forEach((e, i) => {
        if (e.y === hub.y) line(`M${hub.x} ${hub.y}H${e.x}`);
        else {
          line(`M${trunk} ${hub.y}V${e.y}H${e.x}`);
          group.append(el('circle', { cx: trunk, cy: hub.y, r: 3.2, class: 'junction' }));
          if (i < others.length - 1 && others.slice(i + 1).some(o => Math.abs(o.y - hub.y) > Math.abs(e.y - hub.y)))
            group.append(el('circle', { cx: trunk, cy: e.y, r: 3.2, class: 'junction' }));
        }
      });
      const labelX = hub.side === 'L' ? hub.x - 8 : hub.x + 8;
      group.append(el('text', { x: labelX, y: hub.y - 5, class: 'net-label', 'text-anchor': hub.side === 'L' ? 'end' : 'start' }, net));
      if (hub.part === 'U1') {
        const dot = el('circle', { cx: hub.side === 'L' ? hub.x - 3 : hub.x + 3, cy: hub.y, r: 3.4, class: 'level' });
        group.append(dot);
        this.dots[net] = dot;
      }
      group.addEventListener('click', () => onNet(net));
      gWires.append(group);
      this.wires[net] = paths;
    }

    // Power chain along the bottom: USB -> charger -> battery -> regulator -> rails.
    const power = el('g', { class: 'net power', style: `--c:${BUS_COLOUR.power}` });
    const arrow = (x1, x2, y, label) => {
      power.append(el('path', { d: `M${x1} ${y}H${x2 - 6}`, class: 'wire rail' }), el('path', { d: `M${x2 - 7} ${y - 4}l7 4l-7 4z`, class: 'arrowhead' }));
      power.append(el('text', { x: (x1 + x2) / 2, y: y - 7, class: 'net-label', 'text-anchor': 'middle' }, label));
    };
    arrow(150, 290, 822, 'VBUS 5 V');
    arrow(450, 500, 822, 'VBAT');
    arrow(680, 730, 822, 'VBAT');
    arrow(890, 1010, 822, '3V3');
    power.append(el('text', { x: 148, y: 826, class: 'rail-end', 'text-anchor': 'end' }, 'from J1 USB-C'));
    power.append(el('text', { x: 1016, y: 826, class: 'rail-end' }, 'to the MCU, reader, sensors, mic'));
    gWires.append(power);

    for (const part of netlist.parts) {
      const lay = LAYOUT[part.id];
      if (!lay) continue;
      const g = el('g', { class: 'part', 'data-part': part.id, tabindex: 0 });
      g.append(el('rect', { x: lay.x, y: lay.y, width: lay.w, height: lay.h, rx: 6 }));
      g.append(el('text', { x: lay.x + lay.w / 2, y: lay.y + 18, class: 'part-name', 'text-anchor': 'middle' }, `${part.id} · ${part.name}`));
      g.append(el('text', { x: lay.x + lay.w / 2, y: lay.y + 33, class: 'part-role', 'text-anchor': 'middle' }, part.role));
      for (const side of ['L', 'R']) {
        for (const [pin, y] of Object.entries(lay[side] ?? {})) {
          const x = side === 'L' ? lay.x : lay.x + lay.w;
          g.append(el('rect', { x: x - 3, y: y - 3, width: 6, height: 6, class: 'pad' }));
          g.append(el('text', { x: side === 'L' ? x + 8 : x - 8, y: y + 3.5, class: 'pin', 'text-anchor': side === 'L' ? 'start' : 'end' }, pin));
        }
      }
      const rails = part.pins.filter(([pin, net]) => netlist.nets[net]?.bus === 'power' && net !== 'GND' && !(lay.L?.[pin] != null || lay.R?.[pin] != null)).map(([pin, net]) => `${pin}: ${net}`);
      if (rails.length) g.append(el('text', { x: lay.x + lay.w / 2, y: lay.y + lay.h - 7, class: 'rails', 'text-anchor': 'middle' }, rails.join(' · ')));
      const badge = el('text', { x: lay.x + lay.w / 2, y: lay.y + 50, class: 'badge', 'text-anchor': 'middle' });
      g.append(badge);
      this.badges[part.id] = badge;
      g.addEventListener('click', () => onPart(part));
      g.addEventListener('keydown', e => { if (e.key === 'Enter') onPart(part); });
      gParts.append(g);
    }

    // Extras drawn inside parts.
    const d1 = LAYOUT.D1;
    this.pixelEls = [];
    for (let i = 0; i < 8; i++) {
      const x = d1.x + 60 + i * 31;
      const r = el('rect', { x, y: d1.y + 44, width: 18, height: 14, rx: 2, class: 'pixel' });
      gParts.append(r, el('text', { x: x + 9, y: d1.y + 70, class: 'pixel-n', 'text-anchor': 'middle' }, String(i)));
      this.pixelEls.push(r);
    }
    const a = LAYOUT.ANT1;
    this.coil = el('g', { class: 'coil' });
    for (let i = 0; i < 3; i++) this.coil.append(el('rect', { x: a.x + 22 + i * 8, y: a.y + 56 + i * 7, width: a.w - 60 - i * 16, height: 78 - i * 14, rx: 6 }));
    gParts.append(this.coil);
    this.tagEl = el('g', { class: 'tag-chip', visibility: 'hidden' });
    this.tagEl.append(el('rect', { x: a.x, y: a.y + 162, width: a.w, height: 40, rx: 6 }));
    this.tagName = el('text', { x: a.x + a.w / 2, y: a.y + 179, 'text-anchor': 'middle', class: 'tag-name' });
    this.tagSub = el('text', { x: a.x + a.w / 2, y: a.y + 194, 'text-anchor': 'middle', class: 'tag-sub' });
    this.tagEl.append(this.tagName, this.tagSub);
    gParts.append(this.tagEl);
    const s = LAYOUT.LS1;
    this.cone = el('path', { d: `M${s.x + 44} ${s.y + 68}h10l14 -10v34l-14 -10h-10z`, class: 'cone' });
    this.waves = el('path', { d: `M${s.x + 76} ${s.y + 62}q8 13 0 26M${s.x + 84} ${s.y + 56}q14 19 0 38`, class: 'waves' });
    gParts.append(this.cone, this.waves);
  }

  touch(net, now) { this.heat[net] = now; }

  // Called once per animation frame.
  update(board, now, extra) {
    for (const [net, paths] of Object.entries(this.wires)) {
      const hot = now - (this.heat[net] ?? -1e9) < 140;
      for (const p of paths) p.classList.toggle('hot', hot);
      const dot = this.dots[net];
      if (dot) dot.classList.toggle('high', !!board.level[net]);
    }
    board.pixels.rgb.forEach((_, i) => {
      if (i % 3) return;
      const [r, g, b] = board.pixels.rgb.subarray(i, i + 3);
      const boost = v => Math.min(255, Math.round(Math.sqrt(v / 255) * 255));
      this.pixelEls[i / 3].style.fill = r + g + b ? `rgb(${boost(r)},${boost(g)},${boost(b)})` : '';
    });
    this.coil.classList.toggle('on', board.rfOn || now - (this.heat.RF ?? -1e9) < 140);
    this.badges.U2.textContent = !board.nfc.powered ? 'held in reset' : board.rfOn ? 'field on' : 'field off';
    this.badges.Q1.textContent = board.rail ? 'pixels powered' : 'pixels off';
    this.badges.MK1.textContent = board.asleep ? 'no clock' : extra.micText;
    this.badges.BT1.textContent = `${board.battery.soc.toFixed(0)}% · ${board.battery.volts.toFixed(2)} V`;
    this.badges.U8.textContent = board.battery.usb ? (board.battery.soc < 100 ? 'charging' : 'full') : 'no USB';
    this.badges.U1.textContent = board.asleep ? 'deep sleep' : board.radioOn ? 'running · radio on' : 'running';
    this.badges.U4.textContent = ((board.colour.reg[0] & 3) === 3 ? 'measuring' : 'asleep') + (board.level.LAMP_EN ? ' · lamp on' : '');
    this.badges.U6.textContent = !board.rail ? 'shut down' : extra.audible ? 'playing' : 'silent';
    this.svg.classList.toggle('sound', !!extra.audible && board.rail);
    this.svg.classList.toggle('rail-off', !board.rail);
    const tag = board.nfc.tag;
    this.tagEl.setAttribute('visibility', tag ? 'visible' : 'hidden');
    if (tag) { this.tagName.textContent = tag.name; this.tagSub.textContent = 'ISO 15693 tag'; }
  }

  select(kind, id) {
    this.svg.querySelectorAll('.selected').forEach(e => e.classList.remove('selected'));
    this.svg.querySelector(kind === 'part' ? `[data-part="${id}"]` : `[data-net="${id}"]`)?.classList.add('selected');
  }
}
