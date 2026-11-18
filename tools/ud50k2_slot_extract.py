"""Extract a K2-format backup image by slot position (works without '[K2]' gap markers).

Some K2 backups (e.g. HD00_imaged.hda) have zeros in the gaps instead of '[K2]'.
ud50new_extract.py finds records by the '[K2]' runs; this tool uses the fixed slot
positions instead (see docs/FORMAT.md, "New backup format"):

    E_i = 0xA10 + 324 * i + 960 * head,   i = (head * 406 + cyl) * 24 + sector

Around E_i the record is searched in the stream of 16-bit little-endian words read bit 15
first: sync nibble 0,0,0,1 followed by 2096 bits with a valid CRC-16/ARC. Data words are
written big-endian (high byte first) to <OUT>_payload.bin; data bits are not changed.

Usage: python ud50k2_slot_extract.py IMAGE OUT_PREFIX
Writes OUT_PREFIX_payload.bin and OUT_PREFIX_records.csv
(index;head;cyl;sec;nibble_bit;status;w0;w1 - nibble_bit is relative to E_i).
"""
import sys
from collections import Counter
import numpy as np

CYLS, SECS, HEADS = 406, 24, 20
N = CYLS * SECS * HEADS
TAB = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = (_c >> 1) ^ 0xA001 if _c & 1 else _c >> 1
    TAB.append(_c)


def crc16_arc(data):
    c = 0
    for b in data:
        c = (c >> 8) ^ TAB[(c ^ b) & 0xFF]
    return c


def main():
    path, out = sys.argv[1], sys.argv[2]
    d = open(path, 'rb').read(0x4000000)
    pos, bad, badhdr = Counter(), 0, 0
    payload, rows = bytearray(), []
    for i in range(N):
        head, r = divmod(i, CYLS * SECS)
        cyl, sec = divmod(r, SECS)
        E = 0xA10 + 324 * i + 960 * head
        seg = d[E - 32:E + 340]
        a = np.frombuffer(seg, dtype=np.uint8).reshape(-1, 2)[:, ::-1].reshape(-1)
        bits = np.unpackbits(a, bitorder='big')
        cand = np.nonzero((bits[:-3] == 0) & (bits[1:-2] == 0) & (bits[2:-1] == 0) & (bits[3:] == 1))[0]
        hit = None
        for p in cand.tolist():
            if p + 2100 > len(bits):
                break
            rr = bits[p + 4:p + 2100]
            m = np.packbits(rr[:2080], bitorder='little').tobytes()
            c = int.from_bytes(np.packbits(rr[2080:], bitorder='little').tobytes(), 'little')
            if crc16_arc(m) == c:
                hit = (p - 256, m)          # relative to E (the segment starts 32 bytes before E)
                break
        if hit is None:
            bad += 1
            payload += b'**MISSING SECTOR**'.ljust(32, b'*') * 8
            rows.append(f'{i};{head};{cyl};{sec};;MISSING;;')
            continue
        p, m = hit
        w0 = int.from_bytes(m[:2], 'little')
        w1 = int.from_bytes(m[2:4], 'little')
        h2 = ((w0 >> 5) & 1) | ((w1 & 7) << 1) | ((w0 >> 15) << 4)
        status = 'ok' if (w0 & 31, (w0 >> 6) & 511, h2) == (sec, cyl, head) else 'HEADER_MISMATCH'
        badhdr += status != 'ok'
        pos[p] += 1
        payload += np.frombuffer(m[4:], dtype='<u2').astype('>u2').tobytes()
        rows.append(f'{i};{head};{cyl};{sec};{p};{status};{w0:04x};{w1:04x}')
    open(out + '_payload.bin', 'wb').write(payload)
    open(out + '_records.csv', 'w').write('index;head;cyl;sec;nibble_bit;status;w0;w1\n' + '\n'.join(rows) + '\n')
    print(f'valid CRC: {N - bad} of {N}, missing {bad}, header != slot: {badhdr}')
    print('nibble bit relative to E (top):', pos.most_common(8))


if __name__ == '__main__':
    main()
