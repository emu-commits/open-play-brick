// Browser front end: loads the data and the firmware, builds the board, and
// connects it to the diagram, the analyzer, the logs and the controls.

import { Board, STATES } from './board.js';
import { buildCatalog, tagMemory, EVENTS, ANIMS, KINDS } from './catalog.js';
import { CURRENT_MA } from './chips.js';
import { Diagram, BUS_COLOUR, BUS_LABEL } from './diagram.js';
import { Analyzer, formatSpan } from './analyzer.js';
import { Decoder, DECODE_BUSES } from './decode.js';
import { BrickView } from './brickview.js';

const $ = id => document.getElementById(id);
const hex = (v, w = 2) => v.toString(16).toUpperCase().padStart(w, '0');

// ADD NEW SURFACE COLOURS HERE: [label, reflectance r g b (0..1), css colour]
const SWATCHES = [
  ['Nothing', null, 'transparent'],
  ['Red', [0.8, 0.12, 0.1], '#d6332b'],
  ['Green', [0.15, 0.7, 0.2], '#2fa84a'],
  ['Blue', [0.1, 0.25, 0.8], '#2c62d6'],
  ['Yellow', [0.9, 0.75, 0.1], '#f2c81f'],
  ['White', [0.9, 0.9, 0.9], '#eeeeee'],
];
const COLOUR_NAMES = ['none', 'red', 'green', 'blue', 'yellow', 'white'];

async function load() {
  const get = async (path, type) => {
    const r = await fetch(path);
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
    return type === 'bytes' ? new Uint8Array(await r.arrayBuffer()) : r.json();
  };
  const [netlist, tagsJson, soundsJson, wasm] = await Promise.all([
    get('data/netlist.json'), get('data/tags.json'), get('data/sounds.json'), get('firmware.wasm', 'bytes'),
  ]);
  return { netlist, cat: buildCatalog(tagsJson, soundsJson), wasm };
}

// ---------------------------------------------------------------------------
// Speaker: plays the I2S samples the firmware sends to the amplifier.
// ---------------------------------------------------------------------------
class Speaker {
  constructor() { this.ctx = null; this.pending = []; this.volume = 0.7; }

  enable() {
    if (!this.ctx) {
      this.ctx = new (window.AudioContext || window.webkitAudioContext)();
      this.gain = this.ctx.createGain();
      this.gain.connect(this.ctx.destination);
      this.setVolume(this.volume);
    }
    return this.ctx.resume();
  }

  setVolume(v) { this.volume = v; if (this.gain) this.gain.gain.value = v * v; }
  push(samples, t0) { if (this.ctx) this.pending.push({ samples, t0 }); }

  // Join blocks that follow each other exactly and schedule each run once.
  flush() {
    if (!this.ctx || !this.pending.length) return;
    const runs = [];
    for (const p of this.pending) {
      const last = runs[runs.length - 1];
      if (last && Math.abs(last.end - p.t0) < 1) { last.parts.push(p.samples); last.end = p.t0 + p.samples.length * 62.5; }
      else runs.push({ t0: p.t0, end: p.t0 + p.samples.length * 62.5, parts: [p.samples] });
    }
    this.pending = [];
    for (const run of runs) {
      const n = run.parts.reduce((s, p) => s + p.length, 0);
      const buffer = this.ctx.createBuffer(1, n, 16000);
      const data = buffer.getChannelData(0);
      let o = 0;
      for (const p of run.parts) for (const s of p) data[o++] = s / 32768;
      let when = run.t0 / 1e6 + (this.offset ?? 0);
      const now = this.ctx.currentTime;
      if (this.offset == null || when < now + 0.01 || when > now + 0.5) {
        this.offset = now + 0.08 - run.t0 / 1e6;
        when = now + 0.08;
      }
      const src = this.ctx.createBufferSource();
      src.buffer = buffer;
      src.connect(this.gain);
      src.start(when);
    }
  }
}

// ---------------------------------------------------------------------------

function start({ netlist, cat, wasm }) {
  const board = new Board({ netlist, catalog: cat.blob, wasm, seed: (Math.random() * 2 ** 32) >>> 0 });
  const speaker = new Speaker();
  const decoder = new Decoder();
  const brick = new BrickView($('brick-stage'));
  let running = true, flipped = false, radioSent = 0, radioReceived = 0, peerSeq = 0;
  let avgMa = 0;

  // ---- wiring diagram ----
  const showInfo = html => { $('info').innerHTML = html; };
  const diagram = new Diagram($('diagram'), netlist, {
    onPart(part) {
      diagram.select('part', part.id);
      const pins = part.pins.map(([pin, net]) => `<code>${pin}</code> → <code>${net}</code>`).join(', ');
      const buy = part.buy ? `<br>Buy as: <strong>${part.buy.item}</strong> (${part.buy.sku})${part.buy.optional ? ', optional' : ''}.` : '';
      showInfo(`<strong>${part.id} · ${part.name}</strong> — ${part.role}; ${part.package}${part.i2c ? `; I2C address ${part.i2c}` : ''}.<br>${part.why}${buy}<br><span class="hint">${pins}</span>`);
    },
    onNet(net) {
      diagram.select('net', net);
      const n = netlist.nets[net];
      const gpio = netlist.gpio[net];
      const ends = netlist.parts.flatMap(p => p.pins.filter(([, x]) => x === net).map(([pin]) => `${p.id} ${pin}`)).join(' · ');
      const pad = netlist.feather_pad[net];
      showInfo(`<strong>${net}</strong>${gpio != null ? ` — GPIO${gpio}${pad ? `, Feather pad “${pad}”` : ''}` : ''} · ${BUS_LABEL[n.bus] ?? n.bus}<br>${n.desc}${n.bus === 'usb' ? ' Not simulated here.' : ''}<br><span class="hint">${ends}</span>`);
    },
  });
  $('legend').innerHTML = ['spi', 'i2c', 'i2s', 'led', 'gpio', 'rf', 'usb', 'power']
    .map(b => `<span><i style="background:${BUS_COLOUR[b]}"></i>${BUS_LABEL[b]}</span>`).join('');

  // ---- analyzer ----
  const analyzer = new Analyzer($('scope'), board, $('scope-readout'));
  analyzer.onFollowChange = on => $('scope-follow').setAttribute('aria-pressed', String(on));
  $('scope-follow').onclick = () => analyzer.setFollow(!analyzer.follow);
  for (const us of [2e6, 2e5, 2e4, 2e3, 200, 20]) {
    const b = document.createElement('button');
    b.textContent = formatSpan(us);
    b.onclick = () => analyzer.setSpan(us);
    $('scope-span').append(b);
  }
  document.querySelectorAll('[data-jump]').forEach(b => { b.onclick = () => analyzer.jumpTo(b.dataset.jump); });

  // ---- logs ----
  const consoleEl = $('console');
  const consoleLines = [];
  const decorate = line => line
    .replace(/patch#(\d+)/g, (m, n) => (+n === 255 ? 'no sound' : `sound "${cat.patchNames[+n] ?? n}"`))
    .replace(/anim (\d+)/g, (m, n) => `lights "${ANIMS[+n] ?? n}"`);
  let consoleDirty = false;
  board.on('log', (line, t) => {
    consoleLines.push(`[${(t / 1e6).toFixed(3).padStart(9)}] ${decorate(line)}`);
    if (consoleLines.length > 400) consoleLines.splice(0, 100);
    consoleDirty = true;
  });
  const decoded = [];
  const filters = Object.fromEntries(DECODE_BUSES.map(([bus, , on]) => [bus, on]));
  for (const [bus, label] of DECODE_BUSES) {
    const l = document.createElement('label');
    l.className = 'check';
    l.innerHTML = `<input type="checkbox" ${filters[bus] ? 'checked' : ''}> ${label}`;
    l.querySelector('input').onchange = e => { filters[bus] = e.target.checked; };
    $('decode-filters').append(l);
  }

  // ---- activity hooks ----
  const hot = {};
  const HEAT = {
    spi: r => (r.read ? ['SPI_SCK', 'SPI_MISO'] : ['SPI_SCK', 'SPI_MOSI']),
    i2c: () => ['I2C_SDA', 'I2C_SCL'],
    i2sin: () => ['I2S_DIN'],
    led: () => ['LED_DATA'],
    rf: () => ['ANT', 'RF'],
  };
  board.onRecord = rec => {
    for (const net of HEAT[rec.bus]?.(rec) ?? []) hot[net] = true;
    if (rec.bus === 'log' || (rec.bus === 'i2s' && rec.peak === 0)) return;
    const d = decoder.line(rec);
    if (!d) return;
    const last = decoded[decoded.length - 1];
    if (d.bus === 'i2s' && last?.bus === 'i2s') { last.n++; last.text = `I2S  ${last.n * rec.samples.length} samples (${last.n} blocks)`; return; }
    decoded.push({ ...d, t: rec.t0, n: 1 });
    if (decoded.length > 1500) decoded.splice(0, 500);
  };
  board.onEdge = net => { hot[net] = true; };
  board.on('audio', (samples, t0) => speaker.push(samples, t0));
  board.on('radio', () => { radioSent++; });

  // ---- tag controls ----
  const select = $('tag-select');
  const groups = {};
  cat.tags.forEach((t, i) => {
    const g = groups[t.group] ??= select.appendChild(Object.assign(document.createElement('optgroup'), { label: t.group }));
    g.append(new Option(`${t.name} · 0x${hex(t.len)}${t.placeholder ? ' (placeholder ID)' : ''}`, i));
  });
  let placed = null;
  const place = (tag, meta) => { placed = meta; board.placeTag(tag); renderMemory(); };
  const placeFromCatalogue = i => {
    const t = cat.tags[i];
    select.value = i;
    place({ name: t.name, uid: t.sim.uid, mem: t.sim.mem, placeholder: t.placeholder }, { ...t, uid: t.sim.uid, mem: t.sim.mem });
  };
  $('tag-place').onclick = () => placeFromCatalogue(+select.value);
  $('tag-remove').onclick = () => { placed = null; board.removeTag(); renderMemory(); };
  $('tag-random').onclick = () => placeFromCatalogue(Math.floor(Math.random() * cat.tags.length));
  $('custom-place').onclick = () => {
    const len = Math.max(5, Math.min(255, parseInt($('custom-len').value, 16) || 0x55));
    const m = tagMemory('Unknown tag ' + len, len);
    place({ name: `Unknown 0x${hex(len)}`, uid: m.uid, mem: m.mem }, { name: `Unknown tag, length 0x${hex(len)}`, len, uid: m.uid, mem: m.mem, sim: m, unknown: true });
  };
  $('blank-place').onclick = () => {
    const uid = Uint8Array.from([0xE0, 0x04, 0x01, 0x50, 0x12, 0x34, 0x56, 0x78]);
    const mem = new Uint8Array(264);
    place({ name: 'Blank NFC tag', uid, mem }, { name: 'Blank ISO 15693 tag (not a play tag)', len: 0, uid, mem, blank: true });
  };

  // ---- motion controls ----
  const tiltEl = $('tilt');
  const setTilt = (deg, ms) => {
    tiltEl.value = deg;
    $('tilt-out').textContent = `${deg}°`;
    board.motion.setOrientation(deg * Math.PI / 180, flipped ? Math.PI : 0, board.t, ms);
  };
  $('gestures').addEventListener('click', e => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.gesture) { board.motion.gesture(b.dataset.gesture, board.t); brick.animate(b.dataset.gesture); }
    else if (b.dataset.tilt) setTilt(52 * +b.dataset.tilt, 350);
    else if (b.dataset.flip) { flipped = !flipped; setTilt(+tiltEl.value, 450); }
    else if (b.dataset.level) { flipped = false; setTilt(0, 350); }
  });
  tiltEl.oninput = () => setTilt(+tiltEl.value, 120);

  if (window.DeviceMotionEvent && matchMedia('(pointer: coarse)').matches) {
    const btn = $('btn-device');
    btn.hidden = false;
    let on = false;
    const ios = typeof DeviceMotionEvent.requestPermission === 'function';
    const handler = e => {
      const g = e.accelerationIncludingGravity;
      if (!g || g.x == null) return;
      const k = (ios ? -1 : 1) / 9.81;
      board.motion.override = [g.x * k, g.y * k, g.z * k];
    };
    btn.onclick = async () => {
      if (!on && ios && (await DeviceMotionEvent.requestPermission()) !== 'granted') return;
      on = !on;
      btn.textContent = on ? 'Stop using the motion sensor' : "Use this device's motion sensor";
      if (on) window.addEventListener('devicemotion', handler);
      else { window.removeEventListener('devicemotion', handler); board.motion.override = null; }
    };
  }

  // ---- colour, radio, power, audio ----
  SWATCHES.forEach(([label, refl, css], i) => {
    const b = document.createElement('button');
    b.className = 'swatch';
    b.style.setProperty('--sw', css);
    b.textContent = label;
    b.setAttribute('aria-pressed', String(i === 0));
    b.onclick = () => {
      board.scene.swatch = refl;
      brick.setSwatch(refl ? css : null);
      $('swatches').querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    };
    $('swatches').append(b);
  });
  $('clap').onclick = () => { board.mic.clap(board.t); };
  $('peer-fire').onclick = () => {
    if (!board.radioOn) {
      consoleLines.push('(emulator) The brick only listens to the radio while a combat tag is on it. Place the X-Wing or TIE Fighter first.');
      consoleDirty = true;
      return;
    }
    radioReceived++;
    board.radioReceive([0x4F, 0x50, 0x42, 1, 1, 0, peerSeq & 0xFF, peerSeq >> 8]);
    peerSeq++;
  };
  $('usb').onchange = e => { board.battery.usb = e.target.checked; };
  let socDragging = false;
  $('soc').oninput = e => { socDragging = true; board.battery.soc = +e.target.value; };
  $('soc').onchange = () => { socDragging = false; };
  $('volume').oninput = e => { speaker.setVolume(e.target.value / 100); $('volume-out').textContent = e.target.value; };
  $('btn-sound').onclick = async () => {
    await speaker.enable();
    $('btn-sound').textContent = 'Sound is on';
    $('btn-sound').classList.remove('primary');
  };

  // ---- transport ----
  const setRunning = on => { running = on; $('btn-run').textContent = on ? 'Pause' : 'Run'; $('btn-run').setAttribute('aria-pressed', String(on)); if (on) analyzer.setFollow(true); };
  $('btn-run').onclick = () => setRunning(!running);
  $('btn-step').onclick = () => {
    setRunning(false);
    const t0 = board.t;
    board.run(board.t + 1);
    analyzer.frame(t0, board.t);
  };
  $('btn-reset').onclick = () => board.boot('reset button');

  // ---- tabs ----
  let tab = 'console';
  document.querySelectorAll('[role=tab]').forEach(b => {
    b.onclick = () => {
      tab = b.dataset.tab;
      document.querySelectorAll('[role=tab]').forEach(x => x.setAttribute('aria-selected', String(x === b)));
      document.querySelectorAll('.tab-body').forEach(x => { x.hidden = x.id !== `tab-${tab}`; });
      renderSlow(true);
    };
  });

  function renderMemory() {
    const el = $('memory');
    if (!placed) { el.innerHTML = '<p class="hint">No tag on the brick. Place one to see its memory as the reader sees it.</p>'; return; }
    const { mem, uid, len } = placed;
    let rows = '';
    const used = Math.max(1, Math.ceil(len / 4));
    for (let b = 0; b < used; b++) {
      const cells = Array.from(mem.subarray(b * 4, b * 4 + 4), (v, i) => {
        const at = b * 4 + i;
        const cls = placed.blank ? '' : at < 5 ? 'hdr' : at < len ? 'pay' : '';
        return `<span class="${cls}">${hex(v)}</span>`;
      }).join(' ');
      rows += `<div><b>${String(b).padStart(2, '0')}</b> ${cells}</div>`;
    }
    const real = placed.crcReal ? `0x${hex(placed.crcReal, 8)}` : 'not recorded yet';
    el.innerHTML = `
      <p><strong>${placed.name}</strong> · UID ${Array.from(uid, v => hex(v)).join(':')} · 66 blocks of 4 bytes${placed.placeholder ? ' · <em>placeholder ID, not scanned from a real tag</em>' : ''}</p>
      ${placed.blank ? '' : `<p><span class="hdr">Header</span> <code>00 LL 01 0C 01</code>: byte 1 is the payload length, ${len} bytes here. The brick identifies a tag by that length plus a CRC-32 of the payload. <span class="pay">Payload</span> bytes shown here are simulated filler: on a real tag this region is encrypted, and this project neither copies nor decodes it.</p>
      <p class="hint">CRC-32 of this simulated image: 0x${hex(placed.sim.crc, 8)} · CRC-32 of the real tag: ${real}</p>`}
      <div class="dump">${rows}<div class="hint">blocks ${used}–65: 00 00 00 00</div></div>`;
  }

  function renderPower() {
    const c = CURRENT_MA, b = board;
    const colourOn = (b.colour.reg[0] & 3) === 3;
    const rows = [
      ['Feather: microcontroller', c.boardDeepSleep + (b.asleep ? 0 : c.mcuActive), b.asleep ? 'deep sleep' : 'running'],
      ['Radio receiver', b.radioOn ? c.radio : 0, b.radioOn ? 'listening for other bricks' : 'off: only on with a combat tag'],
      ['Sensor connector', (b.level.QT_PWR ? c.sensorRail : 0) + (colourOn ? c.colourActive : 0) + (b.level.LAMP_EN ? c.lamp : 0), b.level.LAMP_EN ? 'lamp on' : 'accelerometer always on'],
      ['NFC reader', b.nfc.powered ? c.readerIdle : c.readerDown, b.nfc.powered ? 'field adds 75 mA for about 12 ms per poll' : 'held in reset'],
      ['Pixels', b.rail ? b.pixels.count * c.pixelIdle + b.pixels.sum() * c.pixelFull : 0, b.rail ? 'depends on brightness' : 'switched off'],
      ['Amplifier and microphone', b.asleep ? 0 : c.micActive + (b.rail ? c.ampIdle + (b.t < b.i2sEnd ? b.ampLevel * c.ampFullScale * 0.35 : 0) : 0), b.asleep ? 'off' : 'clocks running'],
    ];
    const hours = avgMa > 0 ? b.battery.capacityMah * b.battery.soc / 100 / avgMa : 0;
    $('power').innerHTML = `
      <table><tr><th>Part</th><th>Now, mA</th><th></th></tr>
      ${rows.map(([n, ma, note]) => `<tr><td>${n}</td><td class="num">${ma.toFixed(ma < 1 ? 3 : 1)}</td><td class="hint">${note}</td></tr>`).join('')}
      <tr><th>Average over the last few seconds</th><th class="num">${avgMa.toFixed(avgMa < 1 ? 3 : 1)}</th><th></th></tr></table>
      <p>At this rate a ${b.battery.capacityMah} mAh cell at ${b.battery.soc.toFixed(0)}% lasts about <strong>${hours > 48 ? (hours / 24).toFixed(0) + ' days' : hours >= 1 ? hours.toFixed(1) + ' hours' : (hours * 60).toFixed(0) + ' minutes'}</strong>.</p>
      <p class="hint">These are datasheet-typical figures used to size the battery. They are estimates, not measurements of a built board.</p>`;
  }

  let lastSlow = 0;
  function renderSlow(force) {
    const now = performance.now();
    if (!force && now - lastSlow < 200) return;
    lastSlow = now;
    if (tab === 'console' && (consoleDirty || force)) {
      const stick = consoleEl.scrollTop + consoleEl.clientHeight >= consoleEl.scrollHeight - 30;
      consoleEl.textContent = consoleLines.join('\n');
      if (stick || force) consoleEl.scrollTop = consoleEl.scrollHeight;
      consoleDirty = false;
    } else if (tab === 'decode') {
      const el = $('decode');
      const stick = el.scrollTop + el.clientHeight >= el.scrollHeight - 30;
      el.textContent = decoded.filter(d => filters[d.bus]).slice(-250).map(d => `[${(d.t / 1e6).toFixed(6).padStart(11)}] ${d.text}`).join('\n');
      if (stick || force) el.scrollTop = el.scrollHeight;
    } else if (tab === 'power') {
      renderPower();
    } else if (tab === 'memory' && force) {
      renderMemory();
    }

    const s = board.status();
    const kind = s.tagPresent && s.tagIndex !== 255 ? KINDS[s.tagKind] : '';
    const rows = [
      ['State', STATES[s.state] + (s.damaged ? ' · damaged' : '')],
      ['Tag', s.tagPresent ? `${s.tagName}${kind ? ` (${kind})` : ''}` : 'none'],
      ['Tag ID', s.tagPresent && s.tagLen ? `len 0x${hex(s.tagLen)} · crc 0x${hex(s.tagCrc, 8)} · ${s.tagIndex === 255 ? 'not in catalogue' : s.tagExact ? 'exact match' : 'length match'}` : '—'],
      ['Last event', s.lastEvent === 255 ? '—' : EVENTS[s.lastEvent].replace('_', ' ')],
      ['Acceleration', board.asleep ? '—' : s.accel.map(v => (v / 1000).toFixed(2)).join('  ') + ' g'],
      ['Colour seen', COLOUR_NAMES[s.colour]],
      ['Microphone', board.asleep ? '—' : `level ${s.micLevel} · background ${s.micFloor}`],
      ['Hits taken', s.tagPresent ? String(s.hits) : '—'],
      ['Battery', `${board.battery.soc.toFixed(0)}% · ${board.battery.volts.toFixed(2)} V${board.battery.usb ? ' · charging' : ''}`],
      ['Draw (estimate)', `${avgMa.toFixed(avgMa < 1 ? 3 : 1)} mA`],
      ['Radio', `sent ${radioSent} · received ${radioReceived}`],
    ];
    $('status').innerHTML = rows.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join('');
    $('peer-info').textContent = `sent ${radioSent} · received ${radioReceived}`;
    if (!socDragging) { $('soc').value = board.battery.soc; }
    $('soc-out').textContent = `${board.battery.soc.toFixed(0)}%`;
  }

  // ---- main loop ----
  board.boot();
  renderMemory();
  let last = performance.now();
  function frame(now) {
    const dt = Math.min(50, now - last);
    last = now;
    if (running) {
      try { board.run(board.t + dt * 1000); }
      catch (err) { setRunning(false); consoleLines.push(`EMULATOR ERROR: ${err.message}`); consoleDirty = true; console.error(err); }
      avgMa += (board.battery.loadMa - avgMa) * Math.min(1, dt / 3000);
    }
    speaker.flush();
    const audible = board.t < board.loudUntil;
    if (running && !board.asleep) { hot.I2S_BCLK = hot.I2S_LRCLK = true; }
    if (audible && running) { hot.I2S_DOUT = hot.SPK = true; }
    for (const net of Object.keys(hot)) { diagram.touch(net, now); delete hot[net]; }
    diagram.update(board, now, { audible: audible && running, micText: `level ${board.status().micLevel}` });
    brick.update(board, placed, +tiltEl.value, flipped);
    analyzer.draw();
    renderSlow(false);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  window.opb = { board, cat, analyzer };   // for poking at from the browser console
}

load().then(start).catch(err => {
  console.error(err);
  document.querySelector('main').innerHTML = `<section class="panel"><h2>Could not start</h2><p>${err.message}</p>
    <p>This page loads its firmware and data files over HTTP. If you opened index.html straight from disk, run <code>python3 -m http.server</code> in the <code>site</code> folder and open <code>http://localhost:8000</code>.</p></section>`;
});
