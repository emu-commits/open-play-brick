// Headless end-to-end test: boots the real firmware (WebAssembly build)
// against the chip models and plays through every feature.
//   node test/run.mjs
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { Board, STATES } from '../site/js/board.js';
import { buildCatalog, tagMemory } from '../site/js/catalog.js';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const json = f => JSON.parse(readFileSync(join(root, 'site/data', f), 'utf8'));
const netlist = json('netlist.json');
const cat = buildCatalog(json('tags.json'), json('sounds.json'));
const wasm = readFileSync(join(root, 'site/firmware.wasm'));

let failed = 0, passed = 0;
function check(name, ok, detail = '') {
  if (ok) { passed++; console.log(`  ok    ${name}`); }
  else { failed++; console.log(`  FAIL  ${name} ${detail}`); }
}

function makeBoard() {
  const board = new Board({ netlist, catalog: cat.blob, wasm });
  board.logs = [];
  board.audio = 0;
  board.radio = [];
  board.on('log', line => board.logs.push(line));
  board.on('audio', s => { board.audio += s.length; });
  board.on('radio', d => board.radio.push(d));
  board.boot();
  return board;
}
const since = (board, mark) => board.logs.slice(mark).join('\n');
const tagByName = name => { const t = cat.tags.find(t => t.name === name); return { name, uid: t.sim.uid, mem: t.sim.mem }; };
const hexs = a => Array.from(a, b => b.toString(16).padStart(2, '0')).join(' ');

console.log(`catalogue: ${cat.blob.length} bytes, ${cat.tags.length} tags, ${cat.patchNames.length} patches`);

// ---------------------------------------------------------------- boot
console.log('boot');
let b = makeBoard();
b.runFor(1200);
let log = b.logs.join('\n');
check('reader answers with its version', /PN5180 product 4\.0 firmware 4\.0 eeprom 153\.0/.test(log), log);
check('accelerometer found', /LIS3DH found/.test(log));
check('colour sensor found', /TCS3472x found, id 0x44/.test(log));
check('fuel gauge found', /MAX17048 found, version 0x0012/.test(log));
check('catalogue loaded', new RegExp(`Catalogue: ${cat.tags.length} tags`).test(log));
check('no errors logged', !/ERROR/.test(log), log);
check('state is Idle', STATES[b.status().state] === 'Idle', STATES[b.status().state]);
check('boot sound reached the amplifier', b.audio > 2000, String(b.audio));
check('pixel supply and amplifier are enabled', b.rail && b.level.PERIPH_EN === 1);
check('sensor connector is powered', b.level.QT_PWR === 1);
check('reader is out of reset', b.level.NFC_RST === 1 && b.nfc.powered);
check('I2S clocks run while awake (microphone is fed)', b.trace.some(r => r.bus === 'i2sin'));
const firstSpi = b.trace.find(r => r.bus === 'spi');
check('first SPI frame is READ_EEPROM 0x10 x6', hexs(firstSpi.tx) === '07 10 06', hexs(firstSpi.tx));
const inv = b.trace.find(r => r.bus === 'spi' && r.tx[0] === 0x09);
check('inventory request on the wire is 26 01 00', inv && hexs(inv.tx) === '09 00 26 01 00', inv && hexs(inv.tx));
check('field is pulsed, not left on', b.edges.RF_FIELD.length >= 4 && !b.rfOn);

// ---------------------------------------------------------------- tag
console.log('tag');
let mark = b.logs.length;
b.placeTag(tagByName('X-Wing'));
b.runFor(700);
log = since(b, mark);
let s = b.status();
check('tag detected and block 0 logged', /Block 0: 00 6B 01 0C/.test(log), log);
check('payload length and CRC logged', /Payload length 107 bytes \(blocks 0-26\), CRC-32 0x/.test(log), log);
check('identified as X-Wing by CRC', /=> X-Wing \(item\), exact CRC match/.test(log), log);
check('status reports the tag', s.tagPresent && s.tagName === 'X-Wing' && s.tagLen === 0x6B, JSON.stringify(s));
check('state is Tag active or Gesture response', s.state === 2 || s.state === 3);
check('pixels are lit', b.pixels.sum() > 0.2, String(b.pixels.sum()));
check('lamp beside the colour sensor is on', b.level.LAMP_EN === 1);
const rf = b.trace.filter(r => r.bus === 'rf' && r.resp);
check('tag answered Read Multiple Blocks', rf.some(r => r.req[1] === 0x23));

// ---------------------------------------------------------------- gestures
console.log('gestures');
for (const [gesture, expect] of [['shake', 'Shake'], ['swing', 'Swing'], ['impact', 'Impact'], ['throw', 'Throw']]) {
  b.runFor(1500);
  mark = b.logs.length;
  b.motion.gesture(gesture, b.t);
  b.runFor(1500);
  log = since(b, mark);
  const events = log.split('\n').filter(l => / while X-Wing active/.test(l)).map(l => l.split(' while')[0]);
  const allowed = gesture === 'throw' ? ['Throw', 'Impact'] : [expect];
  check(`${gesture} is recognised from raw acceleration`, events.includes(expect) && events.every(e => allowed.includes(e)), JSON.stringify(events));
}
for (const [tilt, flip, expect] of [[0.9, 0, 'Tilt right'], [0, 0, null], [-0.9, 0, 'Tilt left'], [0, 0, null], [0, Math.PI, 'Roll'], [0, 0, 'Roll']]) {
  mark = b.logs.length;
  b.motion.setOrientation(tilt, flip, b.t);
  b.runFor(1600);
  const events = since(b, mark).split('\n').filter(l => / while X-Wing active/.test(l)).map(l => l.split(' while')[0]);
  check(`orientation ${tilt.toFixed(1)}/${flip.toFixed(1)} gives ${expect ?? 'nothing'}`, expect ? events.length === 1 && events[0] === expect : events.length === 0, JSON.stringify(events));
}
mark = b.logs.length;
b.runFor(20000);
check('20 s at rest gives no false gestures', !/ while X-Wing active/.test(since(b, mark)), since(b, mark));

// ---------------------------------------------------------------- microphone
console.log('microphone');
check('its own sounds never counted as a clap', !/Clap/.test(b.logs.join('\n')), b.logs.filter(l => /Clap/.test(l)).join('; '));
b.runFor(1500);
mark = b.logs.length;
b.mic.clap(b.t);
b.runFor(800);
check('a clap is heard', /Clap while X-Wing active/.test(since(b, mark)), since(b, mark));
mark = b.logs.length;
b.motion.gesture('swing', b.t);
b.runFor(1000);                     // the swing has been recognised and its sound is playing
b.mic.clap(b.t);
b.runFor(1500);
check('a clap during its own sound effect is ignored', !/Clap/.test(since(b, mark)), since(b, mark));
check('background level settles low', b.status().micFloor < 400, String(b.status().micFloor));

// ---------------------------------------------------------------- colour
console.log('colour');
const swatches = { red: [0.8, 0.12, 0.1], green: [0.15, 0.7, 0.2], blue: [0.1, 0.25, 0.8] };
for (const [name, swatch] of Object.entries(swatches)) {
  mark = b.logs.length;
  b.scene.swatch = swatch;
  b.runFor(900);
  log = since(b, mark);
  check(`${name} surface is classified`, new RegExp(`Colour sensor: ${name}`).test(log), log);
  b.scene.swatch = null;
  b.runFor(900);
}
check('red made a combat tag send a FIRE packet', b.radio.length === 1 && hexs(b.radio[0].subarray(0, 5)) === '4f 50 42 01 01', String(b.radio.length));

// ---------------------------------------------------------------- brick to brick
console.log('radio');
const fire = [0x4F, 0x50, 0x42, 1, 1, 0x3B, 0, 0];
mark = b.logs.length;
for (let i = 0; i < 3; i++) { b.radioReceive(fire); b.runFor(400); }
check('three hits leave it undamaged', !b.status().damaged && b.status().hits === 3);
b.radioReceive(fire); b.runFor(400);
check('fourth hit damages', b.status().damaged && /now damaged/.test(since(b, mark)));
b.radioReceive(fire); b.runFor(400);
b.radioReceive(fire); b.runFor(400);
check('two more hits destroy and reset', !b.status().damaged && b.status().hits === 0 && /destroyed/.test(since(b, mark)));

// ---------------------------------------------------------------- removal
console.log('removal');
mark = b.logs.length;
b.removeTag();
b.runFor(2500);
check('tag removal is noticed', /Tag removed/.test(since(b, mark)) && !b.status().tagPresent);
check('lamp is off again', b.level.LAMP_EN === 0);

// ---------------------------------------------------------------- every catalogue tag
console.log('catalogue');
for (const t of cat.tags) {
  mark = b.logs.length;
  b.placeTag({ name: t.name, uid: t.sim.uid, mem: t.sim.mem });
  b.runFor(900);
  const st = b.status();
  check(`${t.name} (0x${t.len.toString(16)}) identified`, st.tagName === t.name && st.tagExact, st.tagName);
  b.removeTag();
  b.runFor(1300);
}
mark = b.logs.length;
const custom = tagMemory('mystery', 0x55);
b.placeTag({ name: 'mystery', uid: custom.uid, mem: custom.mem });
b.runFor(900);
check('unknown play tag is reported with its numbers', /not in the catalogue\. Add len 0x55, crc 0x[0-9A-F]{8}/.test(since(b, mark)), since(b, mark));
b.removeTag();
b.runFor(1300);
mark = b.logs.length;
const blank = new Uint8Array(264);
b.placeTag({ name: 'blank', uid: Uint8Array.from([0xE0, 4, 1, 2, 3, 4, 5, 6]), mem: blank });
b.runFor(900);
check('a non-play NFC tag is rejected politely', /Not a play tag header/.test(since(b, mark)));
b.removeTag();
b.runFor(1300);

// A tag whose length is known but whose CRC is not: length-only match.
const byLen = tagMemory('someone else', 0x3B);
mark = b.logs.length;
b.placeTag({ name: 'x', uid: byLen.uid, mem: byLen.mem });
b.runFor(900);
check('length-only match is labelled as such', /=> TIE Fighter \(item\), matched by length only/.test(since(b, mark)), since(b, mark));
b.removeTag();
b.runFor(1300);

// ---------------------------------------------------------------- sleep and wake
console.log('sleep');
mark = b.logs.length;
const boots = b.bootCount;
b.runFor(34000);
check('sleeps after 30 s with no tag and no movement', b.asleep && /Sleeping/.test(since(b, mark)), since(b, mark));
check('pixel supply is off in sleep', !b.rail && b.level.PERIPH_EN === 0);
check('reader is held in reset in sleep', b.level.NFC_RST === 0 && !b.nfc.powered);
check('sensor connector stays powered in sleep', b.level.QT_PWR === 1);
check('pixels are dark in sleep', b.pixels.sum() === 0);
check('sleep current estimate is under 1.5 mA', b.loadMa() < 1.5, String(b.loadMa()));
b.runFor(5000);
check('stays asleep while still', b.asleep);
b.motion.gesture('shake', b.t);
b.runFor(1500);
check('movement wakes it through IMU_INT1', !b.asleep && b.bootCount === boots + 1);
check('wake is a clean boot', /Waiting for a tag/.test(b.logs.slice(-12).join('\n')));

// ---------------------------------------------------------------- battery
console.log('battery');
mark = b.logs.length;
b.battery.soc = 8;
b.runFor(4500);
check('low battery is announced', /Battery low: [78]%/.test(since(b, mark)), since(b, mark));
check('state is Low battery', STATES[b.status().state] === 'Low battery', STATES[b.status().state]);
b.battery.usb = true;
b.runFor(4500);
check('USB power is seen as charging', b.status().charging && STATES[b.status().state] === 'Charging');
b.battery.usb = false;
b.battery.soc = 2;
b.runFor(4500);
check('empty battery forces sleep', b.asleep);

// ---------------------------------------------------------------- failure injection
console.log('faults');
b = new Board({ netlist, catalog: new Uint8Array(16), wasm });
b.logs = [];
b.on('log', l => b.logs.push(l));
b.boot();
b.runFor(1000);
check('a blank catalogue partition is reported, not fatal', /no valid catalogue/.test(b.logs.join('\n')));

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
