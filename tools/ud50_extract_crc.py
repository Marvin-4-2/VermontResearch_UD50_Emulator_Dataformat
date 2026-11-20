"""CRC-verified extraction of old-format backup images (older emulator) of a UD50 drive.

Unlike ud50_extract.py this does not rely on the order of the blocks in the image:
every block is located by its self address, the bit offset s (0..15) is chosen so
that the sync nibble is 8 AND the CRC-16/ARC over header+data matches, and the
sector is placed by its header words (see docs/FORMAT.md, "Geometry"):

    w0: bits 0-4 sector, bit 5 head bit 0, bits 6-14 cylinder, bit 15 head bit 4
    w1: bits 0-2 head bits 1-3
    index = (head * CYLS + cyl) * 24 + sector

Payload words are written big-endian (high byte first) exactly as in ud50_extract.py;
data bits are never changed. Sectors not found with a valid CRC are filled with
'**MISSING SECTOR**'. CSV status per sector:
  ok      CRC valid
  HDRBIT  one bit of header word 1 flipped in the backup; CRC valid after correcting it
          (the data are confirmed; the stored header is reported unchanged in the CSV)
  CRCBIT  stored CRC differs from the computed one in exactly 1 bit (data almost surely fine)
  BADCRC  expected header found, CRC wrong (data unverified)
  STRAY   CRC valid, but the record lies outside the image section of its head
          (stray copy; used only because no record was found at its proper place)
  MISSING not in the image

Usage: python ud50_extract_crc.py IMAGE [OUT_DIR] [END_OFFSET] [CYLS] [HEADS]
"""
import os
import sys
import numpy as np

SECS = 24
CHUNK = 0x2C0000                     # image bytes per head (406 tracks + self-address fill)
MISSING_FILL = b'**MISSING SECTOR**'.ljust(32, b'*') * 8

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


def main():
    img = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else '.'
    end = int(sys.argv[3], 0) if len(sys.argv) > 3 else 0x3700000
    cyls = int(sys.argv[4]) if len(sys.argv) > 4 else 406
    heads = int(sys.argv[5]) if len(sys.argv) > 5 else 20
    raw = open(img, 'rb').read()[:end + 4096]
    w = np.frombuffer(raw[:len(raw) // 2 * 2], dtype='<u2')
    idx = np.arange(len(w), dtype=np.int64)
    selfa = w == (idx & 0xFFFF)
    cand = np.nonzero(selfa)[0]
    cand = cand[(cand >= 6) & (cand * 2 < end + 16)]  # +16: sector 0 of head 0 may sit just before END
    starts = set()
    for c in cand.tolist():
        starts.add(c * 2 - 12)       # normal block: self address at +12
        starts.add(c * 2 - 14)       # sector 0: self address doubled at +12 and +14
    starts = sorted(s for s in starts if s >= 0)

    found = {}                       # index -> (offset, shift, data, crc ok)
    bad = []
    seen = set()
    for o in starts:
        seg = raw[o + 30:o + 30 + 270]
        if len(seg) < 270:
            continue
        v = int.from_bytes(seg, 'little')
        for s in range(16):
            if (v >> s) & 0xF != 8:
                continue
            rec = (v >> (s + 4)) & ((1 << 2096) - 1)
            b = rec.to_bytes(262, 'little')
            msg, chk = b[:260], int.from_bytes(b[260:262], 'little')
            if crc16_arc(msg) != chk:
                continue
            w0 = int.from_bytes(msg[0:2], 'little'); w1 = int.from_bytes(msg[2:4], 'little')
            sec = w0 & 31
            cyl = (w0 >> 6) & 0x1FF
            head = ((w0 >> 5) & 1) | ((w1 & 7) << 1) | ((w0 >> 15) << 4)
            key = (o + 30) * 8 + s + 4   # absolute bit position of the record
            if key in seen:
                break
            seen.add(key)
            if sec >= SECS or cyl >= cyls or head >= heads:
                bad.append((o, s, f'{w0:04x}', f'{w1:04x}', 'OUTOFRANGE'))
                break
            i = (head * cyls + cyl) * SECS + sec
            data = np.frombuffer(msg[4:], dtype='<u2').astype('>u2').tobytes()
            entry = (o, s, data, f'{w0:04x}', f'{w1:04x}', f'{chk:04x}')
            # a valid record belongs to the 0x2C0000 section of its head (sector 0 may
            # start up to 14 bytes before it); records elsewhere are stray copies
            home = head * CHUNK - 16 <= o < (head + 1) * CHUNK
            if i in found:
                old_home = head * CHUNK - 16 <= found[i][0] < (head + 1) * CHUNK
                if found[i][2] != data:
                    loser = found[i] if (home and not old_home) else entry
                    bad.append((loser[0], loser[1], loser[3], loser[4], 'DUPLICATE_DIFFERENT'))
                if home and not old_home:
                    found[i] = entry
            else:
                found[i] = entry
            break

    # pass 2: sectors not found yet. Their block is expected 288/290 bytes after the
    # previous sector or before the next one (self address missing or CRC wrong).
    # A record with the expected header but a wrong CRC is taken with status BADCRC.
    n = heads * cyls * SECS
    status = {i: 'ok' for i in found}
    for i in range(n):
        if i in found:
            continue
        head, r = divmod(i, cyls * SECS)
        cyl, sec = divmod(r, SECS)
        tries = []
        if i - 1 in found:
            tries += [found[i - 1][0] + d for d in (288, 290)]
        if i + 1 in found:
            tries += [found[i + 1][0] - d for d in (288, 290)]
        best = None
        for o in tries:
            seg = raw[o + 30:o + 30 + 270]
            if o < 0 or len(seg) < 270:
                continue
            v = int.from_bytes(seg, 'little')
            for s in range(16):
                if (v >> s) & 0xF != 8:
                    continue
                b = ((v >> (s + 4)) & ((1 << 2096) - 1)).to_bytes(262, 'little')
                msg, chk = b[:260], int.from_bytes(b[260:262], 'little')
                w0 = int.from_bytes(msg[0:2], 'little'); w1 = int.from_bytes(msg[2:4], 'little')
                hd = ((w0 >> 5) & 1) | ((w1 & 7) << 1) | ((w0 >> 15) << 4)
                exp0 = sec | (head & 1) << 5 | cyl << 6 | (head >> 4) << 15
                fixed = None
                if (w0 & 31, (w0 >> 6) & 0x1FF, hd) != (sec, cyl, head):
                    # one flipped bit in header word 1: accept if the CRC confirms the correction
                    if bin(w0 ^ exp0).count('1') != 1 or (w1 & 7) != (head >> 1) & 7:
                        continue
                    m2 = exp0.to_bytes(2, 'little') + msg[2:]
                    if crc16_arc(m2) != chk:
                        continue
                    fixed = 'HDRBIT'
                data = np.frombuffer(msg[4:], dtype='<u2').astype('>u2').tobytes()
                entry = (o, s, data, f'{w0:04x}', f'{w1:04x}', f'{chk:04x}')
                if fixed:
                    best = (entry, fixed)
                    break
                if crc16_arc(msg) == chk:
                    best = (entry, 'ok')
                    break
                if bin(crc16_arc(msg) ^ chk).count('1') == 1 and (best is None or best[1] == 'BADCRC'):
                    best = (entry, 'CRCBIT')  # one flipped bit in the stored CRC, data confirmed
                    continue
                if best is None:
                    best = (entry, 'BADCRC')
            if best and best[1] in ('ok', 'HDRBIT'):
                break
        if best:
            found[i], status[i] = best

    # pass 3: sectors still missing or BADCRC. Some records start a few bytes away from the
    # usual place (no self address in front, e.g. 5 bytes earlier), so passes 1/2 miss them.
    # Search bit by bit in a window around the expected place for a record whose header is
    # exactly the expected one AND whose CRC matches (status SHIFTED). Runs forwards and
    # backwards so that runs of such sectors are found one after the other.
    def scan(i, lo, hi):
        head, r = divmod(i, cyls * SECS)
        cyl, sec = divmod(r, SECS)
        exp0 = sec | (head & 1) << 5 | cyl << 6 | (head >> 4) << 15
        lo = max(lo, 0)
        seg = raw[lo:hi + 270]
        if len(seg) < 270:
            return None
        v = int.from_bytes(seg, 'little')
        for bit in range(0, (hi - lo) * 8):
            if (v >> bit) & 0xFFFF != exp0 or (v >> (bit + 16)) & 7 != (head >> 1) & 7:
                continue
            b = ((v >> bit) & ((1 << 2096) - 1)).to_bytes(262, 'little')
            msg, chk = b[:260], int.from_bytes(b[260:262], 'little')
            if crc16_arc(msg) != chk:
                continue
            ab = lo * 8 + bit - 4                  # bit position of the (assumed) sync nibble
            o, s = ab // 8 - 30, ab % 8
            data = np.frombuffer(msg[4:], dtype='<u2').astype('>u2').tobytes()
            w1 = int.from_bytes(msg[2:4], 'little')
            return (o, s, data, f'{exp0:04x}', f'{w1:04x}', f'{chk:04x}')
        return None

    for order in (range(n), range(n - 1, -1, -1)):
        for i in order:
            if i in found and status[i] != 'BADCRC':
                continue
            for j, sign in ((i - 1, 1), (i + 1, -1)):
                if j in found and status.get(j) != 'BADCRC':
                    c = found[j][0] + sign * 289
                    e = scan(i, c - 48, c + 48)
                    if e:
                        found[i], status[i] = e, 'SHIFTED'
                        break

    name =os.path.splitext(os.path.basename(img))[0]
    os.makedirs(out, exist_ok=True)
    missing = 0
    with open(os.path.join(out, name + '_payload.bin'), 'wb') as fp, \
            open(os.path.join(out, name + '_blocks.csv'), 'w') as fc:
        fc.write('sector_index;head;cyl;sector;image_offset;shift;w0;w1;crc;status\n')
        for i in range(n):
            head, r = divmod(i, cyls * SECS)
            cyl, sec = divmod(r, SECS)
            if i in found:
                o, s, data, w0, w1, chk = found[i]
                if status[i] == 'ok' and not (head * CHUNK - 16 <= o < (head + 1) * CHUNK):
                    status[i] = 'STRAY'  # CRC valid, but found outside its head's section
                fp.write(data)
                fc.write(f'{i};{head};{cyl};{sec};{o:#010x};{s};{w0};{w1};{chk};{status[i]}\n')
            else:
                fp.write(MISSING_FILL)
                fc.write(f'{i};{head};{cyl};{sec};;;;;;MISSING\n')
                missing += 1
        for o, s, w0, w1, st in bad:
            fc.write(f';;;;{o:#010x};{s};{w0};{w1};;{st}\n')
    from collections import Counter
    st = Counter(status[i] for i in found)
    print(f'{name}: status {dict(st)}, {missing} missing of {n}; '
          f'{len(bad)} other records ({", ".join(sorted(set(b[4] for b in bad))) or "none"})')


if __name__ == '__main__':
    main()
