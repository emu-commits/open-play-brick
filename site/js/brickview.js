// A picture of the brick itself: 2 x 4 studs, five plates tall, translucent,
// with the eight array pixels shining through, the tag sitting on top and
// whatever colour is being held up to the sensor window.

const NS = 'http://www.w3.org/2000/svg';
const el = (name, attrs = {}, text) => {
  const e = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text != null) e.textContent = text;
  return e;
};

export class BrickView {
  constructor(host) {
    const svg = el('svg', { viewBox: '0 0 400 250', role: 'img', 'aria-label': 'The brick' });
    svg.innerHTML = `
      <defs>
        <filter id="glow" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="9"/></filter>
        <filter id="soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.5"/></filter>
      </defs>`;
    this.body = el('g', { class: 'brick-body' });
    svg.append(this.body);

    // Oblique view: front face 200 x 100 (31.8 x 16 mm), depth drawn at 45 x -32.
    const fx = 70, fy = 112, fw = 200, fh = 100, dx = 45, dy = -32;
    this.glows = el('g', { filter: 'url(#glow)' });
    this.leds = [];
    for (let i = 0; i < 8; i++) {
      const back = i >= 4, k = i % 4;
      const cx = fx + 25 + k * 50 + (back ? dx * 0.8 : 0), cy = back ? fy + dy * 0.8 + 30 : fy + 55;
      const c = el('circle', { cx, cy, r: back ? 20 : 24, fill: 'none' });
      this.glows.append(c);
      this.leds.push(c);
    }
    this.lamp = el('circle', { cx: fx + fw + dx / 2, cy: fy + 58 + dy / 2, r: 9, fill: 'none', filter: 'url(#soft)' });

    const faces = el('g', { class: 'faces' });
    faces.append(
      el('path', { d: `M${fx} ${fy}h${fw}v${fh}h${-fw}z`, class: 'face front' }),
      el('path', { d: `M${fx} ${fy}l${dx} ${dy}h${fw}l${-dx} ${-dy}z`, class: 'face top' }),
      el('path', { d: `M${fx + fw} ${fy}l${dx} ${dy}v${fh}l${-dx} ${-dy}z`, class: 'face side' }),
    );
    for (let p = 1; p < 5; p++) faces.append(el('path', { d: `M${fx} ${fy + p * 20}h${fw}`, class: 'seam' }));
    const studs = el('g', { class: 'studs' });
    for (const row of [0, 1]) for (let k = 0; k < 4; k++) {
      const cx = fx + 25 + k * 50 + (row ? 31 : 12), cy = fy + (row ? -23 : -9);
      studs.append(el('path', { d: `M${cx - 17} ${cy}v-6a17 5.5 0 0 1 34 0v6a17 5.5 0 0 1 -34 0z`, class: 'stud' }), el('ellipse', { cx, cy: cy - 6, rx: 17, ry: 5.5, class: 'stud-top' }));
    }
    const win = el('rect', { x: fx + fw + 12, y: fy + 34 + dy / 2 + 10, width: 20, height: 24, rx: 3, class: 'window', transform: `skewY(${Math.atan2(dy, dx) * 180 / Math.PI})`, 'transform-origin': `${fx + fw + 22}px ${fy + 60}px` });
    this.body.append(this.glows, faces, studs, this.lamp, win);

    this.tag = el('g', { class: 'brick-tag', visibility: 'hidden' });
    this.tag.append(
      el('path', { d: `M${fx + 62} ${fy - 30}l28 -20h80l-28 20z`, class: 'tile-top' }),
      el('path', { d: `M${fx + 62} ${fy - 30}h80v7h-80z`, class: 'tile-front' }),
      el('path', { d: `M${fx + 142} ${fy - 30}l28 -20v7l-28 20z`, class: 'tile-side' }),
    );
    this.tagLabel = el('text', { x: fx + 116, y: fy - 62, 'text-anchor': 'middle', class: 'tile-label' });
    this.tag.append(this.tagLabel);
    this.body.append(this.tag);

    this.swatch = el('g', { visibility: 'hidden' });
    this.swatchRect = el('path', { d: `M${fx + fw + dx + 18} ${fy + dy + 14}l16 -11v84l-16 11z`, class: 'swatch-card' });
    this.swatch.append(this.swatchRect, el('text', { x: fx + fw + dx + 26, y: fy + fh + dy + 30, 'text-anchor': 'middle', class: 'tile-label' }, 'surface'));
    svg.append(this.swatch);
    this.zzz = el('text', { x: 40, y: 60, class: 'zzz', visibility: 'hidden' }, 'asleep');
    svg.append(this.zzz);

    host.append(svg);
    this.svg = svg;
  }

  setSwatch(css) {
    this.swatch.setAttribute('visibility', css ? 'visible' : 'hidden');
    if (css) this.swatchRect.style.fill = css;
  }

  animate(gesture) {
    this.body.classList.remove('shake', 'swing', 'throw', 'impact');
    void this.body.getBoundingClientRect();
    this.body.classList.add(gesture);
  }

  update(board, placed, tiltDeg, flipped) {
    const px = board.pixels.rgb;
    const boost = v => Math.min(255, Math.round(Math.sqrt(v / 255) * 255));
    for (let i = 0; i < 8; i++) {
      const [r, g, b] = px.subarray(i * 3, i * 3 + 3);
      const on = r + g + b > 0;
      this.leds[i].setAttribute('fill', on ? `rgb(${boost(r)},${boost(g)},${boost(b)})` : 'none');
      this.leds[i].setAttribute('opacity', on ? Math.min(1, 0.35 + Math.sqrt(Math.max(r, g, b) / 255)) : 0);
    }
    this.lamp.setAttribute('fill', px[24] + px[25] + px[26] ? '#fffbe8' : 'none');
    this.body.style.transform = `rotate(${tiltDeg}deg) scaleY(${flipped ? -1 : 1})`;
    this.tag.setAttribute('visibility', placed ? 'visible' : 'hidden');
    if (placed) this.tagLabel.textContent = placed.name.length > 26 ? placed.name.slice(0, 25) + '…' : placed.name;
    this.tagLabel.style.transform = flipped ? 'scaleY(-1)' : '';
    this.zzz.setAttribute('visibility', board.asleep ? 'visible' : 'hidden');
    this.svg.classList.toggle('asleep', board.asleep);
  }
}
