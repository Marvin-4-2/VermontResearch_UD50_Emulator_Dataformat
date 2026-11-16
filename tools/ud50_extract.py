"""Extract the 256-byte payload of every 288-byte block of a UD50 backup image.

Block layout (byte offsets from block start, see docs/FORMAT.md):
  +12      16-bit LE self address: (offset/2) & 0xFFFF
  +30      low nibble 8 = sync nibble; the host record starts right after it
  +30..33  ID; bits 4..8 = sector 0..23
  +34 + 4 bits: 256 data bytes, then a 16-bit check value
The record may be stored with a bit offset of 0..15 (LE bit stream); it is
detected per block from the ID and undone. Data words are written to the
payload big-endian (high byte first), the way the 16-bit SEMS host sees them;
text is 7-bit ASCII with even parity in bit 7.

Usage: python ud50_extract.py IMAGE [OUT_DIR] [END_OFFSET]
Writes <name>_payload.bin (blocks in image order) and <name>_blocks.csv.
"""
import os
import sys

import numpy as np

DATA_OFF = 34
DATA_NIBBLE = 4  # data start in bits after DATA_OFF (record follows the sync nibble)
DATA_LEN = 256
MISSING_FILL = b'**MISSING SECTOR**'.ljust(16 * 2, b'*') * (DATA_LEN // 32)


def find_blocks(w):
    idx = np.arange(len(w), dtype=np.uint32)
    selfa = w == (idx & 0xFFFF)
    n = len(w)
    b = np.arange(n - 160)
    # small self addresses (just past a 64K-word wrap) are only accepted there
    big = (w[b + 6] > 0x40) | (((b + 6) & 0xFFFF) < 0x40)
    ok = selfa[b + 6] & ~selfa[b + 5] & ~selfa[b + 7] & big
    for k in (4, 5, 7, 8, 9, 10, 11, 12, 13):
        ok &= w[b + k] == 0
    # last block of a track: the extra track word repeats the self address
    # (w6, w7), so the rest of the block starts one word later
    lng = selfa[b + 6] & selfa[b + 7] & ~selfa[b + 5] & big
    for k in (4, 5, 9, 10, 11, 12, 13, 14):
        lng &= w[b + k] == 0
    return np.sort(np.concatenate([np.nonzero(ok)[0], np.nonzero(lng)[0] + 1]))


def bits(raw, byteoff, s, nbits):
    nbytes = (nbits + s + 7) // 8 + 1
    v = int.from_bytes(raw[byteoff:byteoff + nbytes], 'little')
    return (v >> s) & ((1 << nbits) - 1)


def detect_shift(raw, o, expect_sector):
    hits = []
    for s in range(16):
        v = bits(raw, o + 30, s, 16)
        sec = (v >> 4) & 0x1F
        if (v & 0xF) == 8 and sec <= 23:
            hits.append((s, v, sec))
    if not hits:
        return None
    # smallest shift wins; the expected sector only decides between shifts 0 and 1
    for h in hits:
        if h[0] <= 1 and h[2] == expect_sector:
            return h
    return hits[0]


def main():
    path = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(path))
    end = int(sys.argv[3], 0) if len(sys.argv) > 3 else None
    raw = open(path, 'rb').read()
    if end:
        raw = raw[:end]
    w = np.frombuffer(raw[:len(raw) // 2 * 2], dtype='<u2')
    blocks = find_blocks(w)
    # a block whose self address was not written (word is 0) is found as a
    # 2-block gap between two good neighbours; take it from the middle
    gaps = np.nonzero(np.isin(np.diff(blocks), (288, 289)))[0]
    blocks = np.sort(np.concatenate([blocks, blocks[gaps] + 144]))
    name = os.path.splitext(os.path.basename(path))[0]
    os.makedirs(out_dir, exist_ok=True)
    payload = bytearray()
    bad = 0
    missing = 0
    shifts = {}
    expect = 0
    with open(os.path.join(out_dir, name + '_blocks.csv'), 'w') as log:
        log.write('sector_index;image_offset;shift;id;sector;check;nibble;status\n')
        for b in blocks.tolist():
            o = b * 2
            h = detect_shift(raw, o, expect)
            if h is None:  # false candidate (e.g. zero area at a 64K-word wrap)
                bad += 1
                continue
            s, idv, sec = h
            # sectors absent from the image (first sector of every 0x2C0000
            # chunk, a few damaged blocks) get a placeholder so that the
            # payload stays track aligned
            while sec != expect:
                log.write(f'{len(payload) // DATA_LEN};;;;{expect};;;MISSING\n')
                payload += MISSING_FILL
                missing += 1
                expect = (expect + 1) % 24
            le = bits(raw, o + DATA_OFF, s + DATA_NIBBLE, DATA_LEN * 8).to_bytes(DATA_LEN, 'little')
            data = bytes(np.frombuffer(le, dtype='<u2').astype('>u2').tobytes())
            chk = bits(raw, o + DATA_OFF + DATA_LEN, s + DATA_NIBBLE, 16)
            nib = bits(raw, o + DATA_OFF + DATA_LEN + 2, s + DATA_NIBBLE, 8)
            shifts[s] = shifts.get(s, 0) + 1
            id32 = bits(raw, o + 30, s, 32)
            log.write(f'{len(payload) // DATA_LEN};0x{o:08x};{s};0x{id32:08x};{sec};0x{chk:04x};{nib};ok\n')
            payload += data
            expect = (sec + 1) % 24
    with open(os.path.join(out_dir, name + '_payload.bin'), 'wb') as f:
        f.write(payload)
    print(f'{name}: {len(blocks) - bad} blocks, {missing} placeholders, {bad} false candidates dropped')
    print(f'payload {len(payload)} bytes = {len(payload) // DATA_LEN / 24:.2f} tracks of 24 sectors')
    print('bit shifts:', dict(sorted(shifts.items())))


if __name__ == '__main__':
    main()
