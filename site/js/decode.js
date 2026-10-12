// Turns raw bus records into one readable line each, the way a protocol
// analyzer would.

const hex = (a) => Array.from(a, b => b.toString(16).toUpperCase().padStart(2, '0')).join(' ');
const hex2 = v => v.toString(16).toUpperCase().padStart(2, '0');

const PN_CMD = {
  0x00: 'WRITE_REGISTER', 0x01: 'WRITE_REGISTER_OR_MASK', 0x02: 'WRITE_REGISTER_AND_MASK', 0x04: 'READ_REGISTER',
  0x07: 'READ_EEPROM', 0x09: 'SEND_DATA', 0x0A: 'READ_DATA', 0x11: 'LOAD_RF_CONFIG', 0x16: 'RF_ON', 0x17: 'RF_OFF',
};
const PN_REG = { 0x00: 'SYSTEM_CONFIG', 0x01: 'IRQ_ENABLE', 0x02: 'IRQ_STATUS', 0x03: 'IRQ_CLEAR', 0x13: 'RX_STATUS', 0x1D: 'RF_STATUS' };
const PN_IRQ = { 0: 'RX', 1: 'TX', 2: 'IDLE', 8: 'TX_RFOFF', 9: 'TX_RFON', 14: 'RX_SOF_DET' };
const ISO_CMD = { 0x01: 'Inventory', 0x20: 'Read Single Block', 0x23: 'Read Multiple Blocks', 0x2B: 'Get System Information' };
const I2C_NAME = { 0x18: 'LIS3DH', 0x29: 'TCS34725', 0x36: 'MAX17048' };
const I2C_REG = {
  0x18: { 0x0F: 'WHO_AM_I', 0x20: 'CTRL_REG1', 0x21: 'CTRL_REG2', 0x22: 'CTRL_REG3', 0x23: 'CTRL_REG4', 0x24: 'CTRL_REG5', 0x26: 'REFERENCE', 0x28: 'OUT_X_L', 0x30: 'INT1_CFG', 0x31: 'INT1_SRC', 0x32: 'INT1_THS', 0x33: 'INT1_DURATION' },
  0x29: { 0x00: 'ENABLE', 0x01: 'ATIME', 0x0F: 'CONTROL', 0x12: 'ID', 0x14: 'CDATAL' },
  0x36: { 0x02: 'VCELL', 0x04: 'SOC', 0x08: 'VERSION', 0x16: 'CRATE' },
};

const u32 = (b, o) => (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0;
const reg = r => PN_REG[r] ?? `reg 0x${hex2(r)}`;

function irqBits(v) {
  const names = Object.entries(PN_IRQ).filter(([bit]) => v & (1 << bit)).map(([, n]) => n);
  return names.length ? ` (${names.join(' | ')})` : '';
}

export class Decoder {
  constructor() { this.lastCmd = null; }

  // Returns { bus, text } or null to skip the record.
  line(r) {
    switch (r.bus) {
      case 'spi': {
        if (r.read) {
          const c = this.lastCmd;
          if (c && c[0] === 0x04) { const v = u32(r.rx, 0); return { bus: 'spi', text: `  ← ${reg(c[1])} = 0x${v.toString(16).toUpperCase().padStart(8, '0')}${c[1] === 0x02 ? irqBits(v) : ''}` }; }
          return { bus: 'spi', text: `  ← ${hex(r.rx)}` };
        }
        const t = r.tx, name = PN_CMD[t[0]] ?? `cmd 0x${hex2(t[0])}`;
        this.lastCmd = t;
        let detail = hex(t.subarray(1));
        if (t[0] <= 0x02) detail = `${reg(t[1])} ${t[0] === 0 ? '=' : t[0] === 1 ? '|=' : '&='} 0x${u32(t, 2).toString(16).toUpperCase().padStart(8, '0')}`;
        else if (t[0] === 0x04) detail = reg(t[1]);
        else if (t[0] === 0x07) detail = `address 0x${hex2(t[1])}, ${t[2]} bytes`;
        else if (t[0] === 0x09) detail = `[${hex(t.subarray(2))}]`;
        else if (t[0] === 0x11) detail = `tx 0x${hex2(t[1])} rx 0x${hex2(t[2])}${t[1] === 0x0D ? ' (ISO 15693, 26 kbit/s)' : ''}`;
        else if (t[0] === 0x16 || t[0] === 0x17 || t[0] === 0x0A) detail = '';
        return { bus: 'spi', text: `SPI PN5180  ${name} ${detail}` };
      }
      case 'rf': {
        const name = ISO_CMD[r.req[1]] ?? `command 0x${hex2(r.req[1])}`;
        return { bus: 'rf', text: `RF 13.56 MHz  ${name} [${hex(r.req)}] → ${r.resp ? `[${hex(r.resp)}]` : 'no answer'}` };
      }
      case 'i2c': {
        const chip = I2C_NAME[r.addr] ?? '?';
        if (r.nack) return { bus: 'i2c', text: `I2C 0x${hex2(r.addr)} NACK` };
        const first = r.wr[0] ?? 0;
        const regNo = r.addr === 0x29 ? first & 0x1F : r.addr === 0x18 ? first & 0x7F : first;
        const name = I2C_REG[r.addr]?.[regNo] ?? `0x${hex2(regNo)}`;
        if (r.rd.length) return { bus: 'i2c', text: `I2C ${chip}  read ${name} → ${hex(r.rd)}` };
        return { bus: 'i2c', text: `I2C ${chip}  write ${name} = ${hex(r.wr.subarray(1))}` };
      }
      case 'led': {
        const px = [];
        for (let i = 0; i < r.grb.length; i += 3) px.push(hex2(r.grb[i + 1]) + hex2(r.grb[i]) + hex2(r.grb[i + 2]));
        return { bus: 'led', text: `Pixels  ${px.join(' ')}` };
      }
      case 'i2s':
        return { bus: 'i2s', text: `I2S  ${r.samples.length} samples, peak ${r.peak}` };
      case 'radio':
        return { bus: 'radio', text: `Radio ${r.dir === 'tx' ? 'sent' : 'received'}  [${hex(r.data)}]` };
      default:
        return null;
    }
  }
}

export const DECODE_BUSES = [
  ['spi', 'SPI', true], ['rf', 'RF', true], ['i2c', 'I2C', false], ['led', 'Pixels', false], ['i2s', 'I2S', false], ['radio', 'Radio', true],
];
