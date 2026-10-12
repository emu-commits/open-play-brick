// Generates firmware/core/pins.h from site/data/netlist.json.
// Run with --check to fail if the committed header is out of date.
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const netlist = JSON.parse(readFileSync(join(root, 'site/data/netlist.json'), 'utf8'));
const out = join(root, 'firmware/core/pins.h');

const i2c = Object.fromEntries(netlist.parts.filter(p => p.i2c).map(p => [p.name, p.i2c]));
let h = `/* GENERATED from site/data/netlist.json by tools/gen_pins.mjs. Do not edit. */
#ifndef OPB_PINS_H
#define OPB_PINS_H

`;
for (const [net, gpio] of Object.entries(netlist.gpio)) h += `#define PIN_${net.padEnd(12)} ${gpio}\n`;
h += '\n';
for (const [name, addr] of Object.entries(i2c)) h += `#define I2C_ADDR_${name.padEnd(9)} ${addr}\n`;
h += '\n#endif\n';

if (process.argv.includes('--check')) {
  if (readFileSync(out, 'utf8') !== h) {
    console.error('pins.h is out of date: run node tools/gen_pins.mjs');
    process.exit(1);
  }
  console.log('pins.h matches netlist.json');
} else {
  writeFileSync(out, h);
  console.log('wrote', out);
}
