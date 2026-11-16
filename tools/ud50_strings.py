"""List text strings of a UD50 payload file (sanity check only, payload is not modified).

Text on the SEMS system is 7-bit ASCII with even parity in bit 7; only bytes with
correct even parity count as characters.

Usage: python ud50_strings.py PAYLOAD.bin [MIN_LEN] [OUT.txt]
"""
import os
import sys

SECTOR = 256
SECTORS_PER_TRACK = 24


def is_char(b):
    c = b & 0x7F
    return 0x20 <= c < 0x7F and bin(b).count('1') % 2 == 0


def main():
    path = sys.argv[1]
    min_len = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    out = sys.argv[3] if len(sys.argv) > 3 else os.path.splitext(path)[0].replace('_payload', '') + '_strings.txt'
    data = open(path, 'rb').read()
    n = 0
    with open(out, 'w', encoding='utf-8') as f:
        f.write(f'# strings from {os.path.basename(path)}: 7-bit ASCII, even parity, min length {min_len}\n')
        f.write('# offset   sector  track/sec  text\n')
        start = None
        for i in range(len(data) + 1):
            if i < len(data) and is_char(data[i]):
                if start is None:
                    start = i
                continue
            if start is not None and i - start >= min_len:
                text = bytes(b & 0x7F for b in data[start:i]).decode('ascii')
                sec = start // SECTOR
                f.write(f'0x{start:08x} {sec:7d}  {sec // SECTORS_PER_TRACK:5d}/{sec % SECTORS_PER_TRACK:<3d} {text}\n')
                n += 1
            start = None
    print(f'{n} strings -> {out}')


if __name__ == '__main__':
    main()
