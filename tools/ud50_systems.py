"""Extract the systems (BOS/RTS/...) listed in the system sectors of a SEMS disk payload.

Disk layout (SEMS documentation 12.11, see docs/FORMAT.md, "SEMS disk file system"):
  logical sector n = physical sector n+1 (mod 24) on a track
  disk address     = cyl * 480 + head * 24 + logical sector   (480 sectors per cylinder)
  logical sector 2: word 0 RAPD start, word 1 max system+1,
                    words 2+4k..5+4k: memory address, launch address, disk address, length (words)
  logical sector 3: words 8 validation, 9-12 label, 16+3k..18+3k file name of system k,
                    64+2k / 65+2k start / end disk address of system k   (k = 0..7)
The payload (*_payload.bin) is ordered head / cyl / physical sector, 256 bytes per sector,
words big-endian. System data are written unchanged (big-endian words, as in the payload).

Usage: python ud50_systems.py PAYLOAD.bin OUT_DIR
Writes OUT_DIR/<k>_<NAME>.bin (exactly `length` words) and OUT_DIR/systems.txt.
"""
import os
import sys
import numpy as np

CYLS, HEADS, SECS = 406, 20, 24


def phys_index(adr):
    cyl, r = divmod(adr, HEADS * SECS)
    head, lsec = divmod(r, SECS)
    return (head * CYLS + cyl) * SECS + (lsec + 1) % SECS


def txt(ws):
    return ''.join(chr(b & 0x7F) if 32 <= (b & 0x7F) < 127 else '.' for w in ws for b in (w >> 8, w & 0xFF))


def main():
    pay = np.fromfile(sys.argv[1], dtype=np.uint8).reshape(-1, 256)
    out = sys.argv[2]
    os.makedirs(out, exist_ok=True)
    words = lambda adr: [int(x) for x in pay[phys_index(adr)].view('>u2')]
    s2, s3 = words(2), words(3)
    lines = [f'source: {sys.argv[1]}',
             f'label {txt(s3[9:13])!r}  validation {s3[8]:04x}  structure {s3[13]:04x}  '
             f'RAPD start {s2[0]:04x}  max system+1 {s2[1]}', '']
    lines.append('k  name    mem   launch  disk adr  start  end    sectors  length(words)  file')
    for k in range(8):
        mem, launch, dadr, length = s2[2 + 4 * k:6 + 4 * k]
        name = txt(s3[16 + 3 * k:19 + 3 * k]).strip('.').strip()
        start, end = s3[64 + 2 * k], s3[65 + 2 * k]
        if not length or not name:
            lines.append(f'{k}  (empty)')
            continue
        nsec = -(-length // 128)
        if dadr != start or end - start + 1 < nsec:
            note = '  WARNING: sector 2/3 disagree'
        else:
            note = ''
        data = b''.join(pay[phys_index(start + j)].tobytes() for j in range(nsec))[:2 * length]
        fn = f'{k}_{name}.bin'
        open(os.path.join(out, fn), 'wb').write(data)
        lines.append(f'{k}  {name:6s}  {mem:04x}  {launch:04x}    {dadr:04x}      {start:04x}   {end:04x}   '
                     f'{nsec:5d}    {length:6d}         {fn}{note}')
    open(os.path.join(out, 'systems.txt'), 'w').write('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
