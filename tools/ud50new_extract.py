"""Extract the host records from a K2-format backup image (K2 emulator)
of a UD50 drive (S2_*.img, K2_MHD.hda).

New format (see docs/FORMAT.md, "New format"):
  * file header at 0, table from 0x200; records follow, each preceded by the
    gap/sync pattern '[K2]' (5b 4b 32 5d) repeated, padded with zeros
  * the record is a bit stream stored as 16-bit LITTLE-ENDIAN words, each word read
    from bit 15 down to bit 0 (time order)
  * in that stream: sync nibble (time order 0,0,0,1 = value 8 LSB-first), then the
    host record exactly as in the old format: 2 header words, 128 data words, CRC-16/ARC
    (all LSB-first in time, i.e. the host bit stream is identical to the old format)
The start bit of the nibble varies; it is found per record by requiring a valid CRC.
Payload words are written big-endian (high byte first) like ud50_extract.py, and the
sector is placed by its header words: index = (head*CYLS + cyl)*24 + sector.

Usage: python ud50new_extract.py IMAGE [OUT_DIR] [CYLS=406] [HEADS=20]
"""
import os
import re
import sys
from collections import Counter
import numpy as np

SECS = 24
MISSING_FILL = b'**MISSING SECTOR**'.ljust(32, b'*') * 8
K2 = b'[K2]'
TAB = []
for i in range(256):
    c = i
    for _ in range(8):
        c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
    TAB.append(c)


def crc16_arc(data):
    c = 0
    for b in data:
        c = (c >> 8) ^ TAB[(c ^ b) & 0xFF]
    return c


def stream_bits(seg):
    """bytes -> time-ordered bits: 16-bit LE words, bit 15 first"""
    a = np.frombuffer(seg[:len(seg) // 2 * 2], dtype=np.uint8).reshape(-1, 2)[:, ::-1].reshape(-1)
    return np.unpackbits(a, bitorder='big')


def main():
    img = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else '.'
    cyls = int(sys.argv[3]) if len(sys.argv) > 3 else 406
    heads = int(sys.argv[4]) if len(sys.argv) > 4 else 20
    d = open(img, 'rb').read()
    # records: after the last '[K2]' of a run; keep start word-aligned relative to file
    ends = [m.end() for m in re.finditer(re.escape(K2) + b'(?!' + re.escape(K2) + b')', d)]
    found, status, starts, bad = {}, {}, Counter(), Counter()
    for e in ends:
        e0 = e & ~1
        seg = d[e0:e0 + 360]
        if len(seg) < 300:
            continue
        bits = stream_bits(seg)
        best = None
        cand = np.nonzero((bits[:-3] == 0) & (bits[1:-2] == 0) & (bits[2:-1] == 0) & (bits[3:] == 1))[0]
        for p in cand.tolist():
            if p + 4 + 2096 > len(bits):
                break
            r = bits[p + 4:p + 4 + 2096]
            m = np.packbits(r[:2080], bitorder='little').tobytes()
            c = int.from_bytes(np.packbits(r[2080:], bitorder='little').tobytes(), 'little')
            if crc16_arc(m) == c:
                best = (p, m, c)
                break
        if best is None:
            bad['no valid CRC'] += 1
            continue
        p, m, c = best
        w0 = int.from_bytes(m[:2], 'little'); w1 = int.from_bytes(m[2:4], 'little')
        sec, cyl = w0 & 31, (w0 >> 6) & 0x1FF
        head = ((w0 >> 5) & 1) | ((w1 & 7) << 1) | ((w0 >> 15) << 4)
        if sec >= SECS or cyl >= cyls or head >= heads:
            bad['header out of range'] += 1
            continue
        i = (head * cyls + cyl) * SECS + sec
        data = np.frombuffer(m[4:], dtype='<u2').astype('>u2').tobytes()
        if i in found:
            bad['duplicate same' if found[i][3] == data else 'duplicate different'] += 1
            continue
        found[i] = (e, p, w0, data, w1, c)
        starts[p] += 1

    n = heads * cyls * SECS
    name = os.path.splitext(os.path.basename(img))[0]
    os.makedirs(out, exist_ok=True)
    missing = 0
    with open(os.path.join(out, name + '_payload.bin'), 'wb') as fp, \
            open(os.path.join(out, name + '_records.csv'), 'w') as fc:
        fc.write('sector_index;head;cyl;sector;k2_end_offset;nibble_bit;w0;w1;crc;status\n')
        for i in range(n):
            head, r = divmod(i, cyls * SECS)
            cyl, sec = divmod(r, SECS)
            if i in found:
                e, p, w0, data, w1, c = found[i]
                fp.write(data)
                fc.write(f'{i};{head};{cyl};{sec};{e:#010x};{p};{w0:04x};{w1:04x};{c:04x};ok\n')
            else:
                fp.write(MISSING_FILL)
                fc.write(f'{i};{head};{cyl};{sec};;;;;;MISSING\n')
                missing += 1
    print(f'{name}: {len(ends)} [K2] runs, {len(found)} sectors with valid CRC, {missing} missing of {n}; '
          f'other: {dict(bad)}')
    print('  nibble start bit after [K2] (top):', starts.most_common(8))


if __name__ == '__main__':
    main()
