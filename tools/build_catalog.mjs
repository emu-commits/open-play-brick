// Packs site/data/tags.json and sounds.json into build/catalog.bin, the image
// for the brick's "catalog" flash partition. The emulator does the same
// packing in the browser every time it loads.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { buildCatalog } from '../site/js/catalog.js';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const json = f => JSON.parse(readFileSync(join(root, 'site/data', f), 'utf8'));
const tags = json('tags.json');

// A real brick must not carry made-up IDs: drop tags that were never scanned.
const unscanned = tags.tags.filter(t => t.len == null).map(t => t.name);
tags.tags = tags.tags.filter(t => t.len != null);

const { blob } = buildCatalog(tags, json('sounds.json'));
mkdirSync(join(root, 'build'), { recursive: true });
writeFileSync(join(root, 'build/catalog.bin'), blob);
console.log(`build/catalog.bin: ${blob.length} bytes, ${tags.tags.length} tags`);
if (unscanned.length) console.log(`left out (no scanned length yet): ${unscanned.join(', ')}`);
