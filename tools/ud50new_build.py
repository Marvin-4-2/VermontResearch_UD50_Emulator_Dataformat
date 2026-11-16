"""Build a K2-format backup image (K2 emulator, 64 MiB) of a UD50 drive from host records.

Layout (derived from K2_MHD.hda, S2_FHD_070208.img, S2_MHD_irgendwas.img; see
docs/FORMAT.md, "New format"):
  0x000000-0x0009FF  file header + table, identical in all known images (copied from REF)
  slot i (sector index i = (head*406 + cyl)*24 + sector, 194 880 slots):
      E_i = 0xA10 + 324*i + 960*head      end of the '[K2]' run in front of the record
      '[K2]' * reps before E_i (reps = 3 normally; at a head start the whole gap since the
      previous record is '[K2]'; first record: 4), zeros otherwise
      from E_i on: the record as a bit stream of 16-bit little-endian words, bit 15 first;
      `nib` zero bits, then the host record: sync nibble (0,0,0,1) + 2096 bits
      (2 header words, 128 data words, CRC-16/ARC; LSB-first in time) - identical to the
      host bit stream of the old format; zeros up to the next '[K2]' run
  after the last record: '[K2]' up to the end of the 64 MiB, copied from REF

Records come from a CSV + image:
  old format: ud50_extract_crc.py output (*_blocks.csv) + old image  -> --old
  new format: ud50new_extract.py output (*_records.csv) + new image -> --new (rebuild test)
Missing sectors are generated only if --fill-missing is given (header words from the
geometry, data = --fill-word, default 0xE38E, CRC computed).
Old-format records with status HDRBIT / CRCBIT keep their stored bits unchanged, unless
--fix-hdrbit is given (HDRBIT: header word 1 is set to the geometry value; refused if the
CRC does not become valid). Data bits are never changed.

Usage:
  python ud50new_build.py REF_NEW_IMAGE OUT.img --old OLD_IMAGE BLOCKS_CSV [--nib 245] [--fill-missing]
  python ud50new_build.py REF_NEW_IMAGE OUT.img --new NEW_IMAGE RECORDS_CSV [--keep-timing]
"""
import argparse
import numpy as np

SIZE = 0x4000000
HDR = 0xA00
SLOT = 324
HEADGAP = 960
CYLS, SECS, HEADS = 406, 24, 20
N = CYLS * SECS * HEADS
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


def slot_end(i):
    return HDR + 16 + SLOT * i + HEADGAP * (i // (CYLS * SECS))


def old_records(img, csv):
    """host record bits (nibble + 2096) per sector index from an old-format image"""
    raw = open(img, 'rb').read()
    recs = {}
    for line in list(open(csv))[1:]:
        r = line.strip().split(';')
        if not r[0] or r[9] == 'MISSING':
            continue
        i, o, s = int(r[0]), int(r[4], 16), int(r[5])
        b = np.unpackbits(np.frombuffer(raw[o + 30:o + 30 + 300], dtype=np.uint8), bitorder='little')
        recs[i] = (b[s:s + 2100].copy(), None, None, r[9])
    return recs


def new_records(img, csv):
    d = open(img, 'rb').read()
    recs = {}
    for line in list(open(csv))[1:]:
        r = line.strip().split(';')
        if r[9] != 'ok':
            continue
        i, e, p = int(r[0]), int(r[4], 16), int(r[5])
        e0 = e & ~1
        a = np.frombuffer(d[e0:e0 + 340], dtype=np.uint8).reshape(-1, 2)[:, ::-1].reshape(-1)
        bits = np.unpackbits(a, bitorder='big')
        # [K2] run (start, end) relative to the slot, for the exact rebuild test;
        # the run may reach a few bytes past the slot start E
        n = 0
        while d[e - 4 * (n + 1):e - 4 * n] == K2:
            n += 1
        E = slot_end(i)
        recs[i] = (bits[p:p + 2100].copy(), (e0 - E) * 8 + p, (e - 4 * n - E, e - E), 'ok')
    return recs


def filler_record(i, fill=0xE38E):
    head, r = divmod(i, CYLS * SECS)
    cyl, sec = divmod(r, SECS)
    w0 = sec | (head & 1) << 5 | cyl << 6 | (head >> 4) << 15
    # header word 2: bits 0-2 head bits 1-3, bits 4-15 = upper 12 bits of the first data word
    w1 = ((head >> 1) & 7) | (fill & 0xFFF0)
    msg = w0.to_bytes(2, 'little') + w1.to_bytes(2, 'little') + fill.to_bytes(2, 'little') * 128
    c = crc16_arc(msg)
    stream = msg + c.to_bytes(2, 'little')
    bits = np.unpackbits(np.frombuffer(stream, dtype=np.uint8), bitorder='little')
    return np.concatenate([np.array([0, 0, 0, 1], dtype=np.uint8), bits])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('ref')
    ap.add_argument('out')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--old', nargs=2, metavar=('IMAGE', 'CSV'))
    g.add_argument('--new', nargs=2, metavar=('IMAGE', 'CSV'))
    ap.add_argument('--old2', nargs=2, metavar=('IMAGE', 'CSV'),
                    help='second old-format copy: replaces records that are not ok in --old')
    ap.add_argument('--fix-hdrbit', action='store_true',
                    help='correct the single flipped bit in header word 1 of HDRBIT records '
                         '(only if the CRC then becomes valid; data bits are not touched)')
    ap.add_argument('--nib', type=int, default=245, help='zero bits between [K2] end and nibble')
    ap.add_argument('--keep-timing', action='store_true', help='(--new) reuse nibble position and [K2] count')
    ap.add_argument('--fill-missing', action='store_true')
    ap.add_argument('--fill-word', type=lambda x: int(x, 16), default=0xE38E,
                    help='data word for generated sectors (hex, default E38E; 0000 = zeros)')
    a = ap.parse_args()

    ref = open(a.ref, 'rb').read()[:SIZE]
    recs = old_records(*a.old) if a.old else new_records(*a.new)
    if a.old2:
        alt = old_records(*a.old2)
        for i, r in list(recs.items()):
            if r[3] != 'ok' and i in alt and alt[i][3] == 'ok':
                print(f'sector {i}: status {r[3]} in --old, taken from --old2 (ok)')
                recs[i] = alt[i]
        for i, r in alt.items():
            if i not in recs and r[3] == 'ok':
                print(f'sector {i}: missing in --old, taken from --old2')
                recs[i] = r
    if a.fix_hdrbit:
        for i, r in list(recs.items()):
            if r[3] != 'HDRBIT':
                continue
            head, rr = divmod(i, CYLS * SECS)
            cyl, sec = divmod(rr, SECS)
            exp0 = sec | (head & 1) << 5 | cyl << 6 | (head >> 4) << 15
            bits = r[0].copy()
            old0 = int(np.packbits(bits[4:20], bitorder='little').view('<u2')[0])
            bits[4:20] = np.unpackbits(np.frombuffer(exp0.to_bytes(2, 'little'), dtype=np.uint8),
                                       bitorder='little')
            m = np.packbits(bits[4:4 + 2080], bitorder='little').tobytes()
            c = int.from_bytes(np.packbits(bits[2084:2100], bitorder='little').tobytes(), 'little')
            if crc16_arc(m) != c:
                raise SystemExit(f'sector {i}: header correction does not give a valid CRC')
            print(f'sector {i}: header word 1 {old0:04x} -> {exp0:04x}, CRC now valid (data unchanged)')
            recs[i] = (bits, r[1], r[2], 'HDRFIXED')
    from collections import Counter
    print('source record status:', dict(Counter(r[3] for r in recs.values())))
    out = bytearray(SIZE)
    out[:HDR] = ref[:HDR]
    last_end = slot_end(N - 1)
    # tail: copy from the reference (the '[K2]' fill after the last record)
    out[last_end + 300:] = ref[last_end + 300:]   # record ends before +300 (nib <= 300)
    nfill = 0
    prev_end = HDR
    for i in range(N):
        E = slot_end(i)
        if i in recs:
            bits, p, reps, st = recs[i]
        elif a.fill_missing:
            bits, p, reps, st = filler_record(i, a.fill_word), None, None, 'FILL'
            nfill += 1
        else:
            raise SystemExit(f'sector {i} missing; use --fill-missing')
        if a.keep_timing and p is not None:
            k0, k1 = reps                     # exact [K2] run and nibble position of the source
            out[E + k0:E + k1] = K2 * ((k1 - k0) // 4)
        else:
            p = a.nib
            if i == 0:
                n = 4
            elif i % (CYLS * SECS) == 0:
                n = (E - prev_end) // 4       # head start: the whole gap is '[K2]'
            else:
                n = 3
            out[E - 4 * n:E] = K2 * n
        # record bits: zeros from E up to the nibble, written as whole 16-bit words; bytes that
        # are entirely zero are not written, so a [K2] run reaching past E stays intact
        nbits = p + len(bits)
        nbits += (-nbits) % 16
        stream = np.zeros(nbits, dtype=np.uint8)
        stream[p:p + len(bits)] = bits
        words = np.packbits(stream, bitorder='big').reshape(-1, 2)[:, ::-1].reshape(-1).tobytes()
        first = (p // 16) * 2                 # first word that holds record bits
        out[E + first:E + len(words)] = words[first:]
        prev_end = E + len(words)
    open(a.out, 'wb').write(out)
    print(f'wrote {a.out}: {len(recs)} records from source, {nfill} generated (filler)')


if __name__ == '__main__':
    main()
