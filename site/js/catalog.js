// Packs tags.json + sounds.json into the binary catalogue the firmware reads
// (layout documented in firmware/core/catalog.h), and builds simulated tag
// memory images. Runs in the browser and in Node.

export const EVENTS = ['place', 'remove', 'shake', 'swing', 'tilt_l', 'tilt_r', 'roll', 'impact',
  'throw', 'red', 'green', 'blue', 'hit', 'damaged', 'destroyed', 'ambient', 'clap'];
export const ANIMS = ['off', 'solid', 'breathe', 'flash', 'chase', 'sparkle', 'rainbow', 'alternate', 'halves', 'fade'];
export const WAVES = ['sine', 'square', 'saw', 'triangle', 'noise', 'silence'];
export const KINDS = ['unknown', 'identity', 'item'];
const SYSTEM = ['boot', 'low_battery', 'unknown_tag', 'sleep'];
const NAME_MAX = 20;
export const TAG_BLOCKS = 66;

export function crc32(bytes) {
  let crc = 0xFFFFFFFF;
  for (const b of bytes) {
    crc ^= b;
    for (let k = 0; k < 8; k++) crc = (crc >>> 1) ^ (0xEDB88320 & -(crc & 1));
  }
  return (~crc) >>> 0;
}

const num = v => (typeof v === 'string' ? parseInt(v, 16) : v);
const hex = (v, w = 2) => '0x' + v.toString(16).toUpperCase().padStart(w, '0');

function hashName(s) {
  let h = 2166136261;
  for (const c of s) h = Math.imul(h ^ c.codePointAt(0), 16777619);
  return h >>> 0;
}

function xorshift(seed) {
  let x = seed || 1;
  return () => { x ^= x << 13; x >>>= 0; x ^= x >>> 17; x ^= x << 5; x >>>= 0; return x; };
}

// A simulated tag: the real 5-byte cleartext header, then filler bytes. The
// filler stands in for the encrypted payload, which this project never
// copies or decodes. The UID uses the real manufacturer prefix E0 16 5C 01.
export function tagMemory(name, len) {
  const mem = new Uint8Array(TAG_BLOCKS * 4);
  const rnd = xorshift(hashName(name) ^ (len * 0x9E3779B1));
  mem.set([0x00, len, 0x01, 0x0C, 0x01]);
  for (let i = 5; i < len; i++) mem[i] = rnd() & 0xFF;
  const u = xorshift(hashName(name + '/uid'));
  const uid = Uint8Array.from([0xE0, 0x16, 0x5C, 0x01, u() & 0xFF, u() & 0xFF, u() & 0xFF, u() & 0xFF]);
  return { name, len, mem, uid, crc: crc32(mem.subarray(0, len)) };
}

// Normalise tags.json: numeric lengths, placeholder flag, simulated memory.
export function resolveTags(tagsJson) {
  const seen = new Map();
  return tagsJson.tags.map(t => {
    const placeholder = t.len == null;
    const len = num(placeholder ? t.placeholder_len : t.len);
    if (!Number.isInteger(len) || len < 5 || len > 255) throw new Error(`Tag "${t.name}": len must be 0x05..0xFF`);
    if (t.name.length > NAME_MAX) throw new Error(`Tag "${t.name}": name is longer than ${NAME_MAX} characters`);
    const crcReal = t.crc32 ? num(t.crc32) : 0;
    const key = len + '/' + crcReal;
    if (seen.has(key)) throw new Error(`Tags "${seen.get(key)}" and "${t.name}" share length ${hex(len)} with no CRC to tell them apart`);
    seen.set(key, t.name);
    return { ...t, len, placeholder, crcReal, sim: tagMemory(t.name, len) };
  });
}

export function buildCatalog(tagsJson, soundsJson) {
  const tags = resolveTags(tagsJson);
  const patchNames = Object.keys(soundsJson.patches);
  const profileNames = Object.keys(soundsJson.profiles);
  if (profileNames[0] !== 'generic') throw new Error('The first profile in sounds.json must be "generic"');
  if (tags.length > 255 || patchNames.length > 254 || profileNames.length > 255) throw new Error('Catalogue too large');

  const patchIndex = name => {
    if (name == null) return 0xFF;
    const i = patchNames.indexOf(name);
    if (i < 0) throw new Error(`Unknown patch "${name}"`);
    return i;
  };
  const animIndex = name => {
    const i = ANIMS.indexOf(name);
    if (i < 0) throw new Error(`Unknown animation "${name}"`);
    return i;
  };

  // Profiles, with `extends` resolved.
  const resolved = {};
  const resolveProfile = name => {
    if (resolved[name]) return resolved[name];
    const p = soundsJson.profiles[name];
    if (!p) throw new Error(`Unknown profile "${name}"`);
    const base = p.extends ? { ...resolveProfile(p.extends) } : {};
    for (const ev of EVENTS) if (p[ev]) base[ev] = p[ev];
    for (const k of Object.keys(p)) if (k !== 'extends' && !EVENTS.includes(k)) throw new Error(`Profile "${name}": unknown event "${k}"`);
    return (resolved[name] = base);
  };

  const segs = [];
  const patches = patchNames.map(name => {
    const p = soundsJson.patches[name];
    if (!p.segs?.length || p.segs.length > 255) throw new Error(`Patch "${name}" needs 1 to 255 segments`);
    const first = segs.length;
    for (const s of p.segs) {
      const wave = WAVES.indexOf(s.wave);
      if (wave < 0) throw new Error(`Patch "${name}": unknown wave "${s.wave}"`);
      segs.push([wave, s.vol ?? 0, s.f0 ?? 0, s.f1 ?? s.f0 ?? 0, s.ms, s.atk ?? 0, Math.min(255, Math.round((s.rel ?? 0) / 4)), s.vib ?? 0, s.depth ?? 0]);
    }
    return [first, p.segs.length, p.loop ? 1 : 0];
  });

  const size = 16 + tags.length * 36 + profileNames.length * EVENTS.length * 2 + patches.length * 4 + segs.length * 12;
  if (size > 8192) throw new Error(`Catalogue is ${size} bytes, the firmware allows 8192`);
  const blob = new Uint8Array(size);
  const dv = new DataView(blob.buffer);
  blob.set([0x4F, 0x50, 0x42, 0x43, 2, tags.length, profileNames.length, patches.length]);
  dv.setUint16(8, segs.length, true);
  SYSTEM.forEach((k, i) => { blob[10 + i] = patchIndex(soundsJson.system?.[k]); });

  let o = 16;
  for (const t of tags) {
    const profile = profileNames.indexOf(t.profile);
    if (profile < 0) throw new Error(`Tag "${t.name}": unknown profile "${t.profile}"`);
    const kind = KINDS.indexOf(t.kind);
    if (kind < 0) throw new Error(`Tag "${t.name}": kind must be identity or item`);
    const rgb = parseInt(t.colour.slice(1), 16);
    blob.set([t.len, kind, profile, t.combat ? 1 : 0, rgb >> 16, (rgb >> 8) & 0xFF, rgb & 0xFF, 0], o);
    dv.setUint32(o + 8, t.crcReal, true);
    dv.setUint32(o + 12, t.sim.crc, true);
    blob.set(new TextEncoder().encode(t.name).subarray(0, NAME_MAX), o + 16);
    o += 36;
  }
  for (const name of profileNames) {
    const p = resolveProfile(name);
    EVENTS.forEach((ev, i) => {
      const [patch, anim] = p[ev] ?? [null, 'off'];
      blob[o + i] = patchIndex(patch);
      blob[o + EVENTS.length + i] = animIndex(anim);
    });
    o += EVENTS.length * 2;
  }
  for (const [first, n, flags] of patches) { dv.setUint16(o, first, true); blob[o + 2] = n; blob[o + 3] = flags; o += 4; }
  for (const s of segs) {
    blob[o] = s[0]; blob[o + 1] = s[1];
    dv.setUint16(o + 2, s[2], true); dv.setUint16(o + 4, s[3], true); dv.setUint16(o + 6, s[4], true);
    blob[o + 8] = s[5]; blob[o + 9] = s[6]; blob[o + 10] = s[7]; blob[o + 11] = s[8];
    o += 12;
  }
  return { blob, tags, patchNames, profileNames };
}
