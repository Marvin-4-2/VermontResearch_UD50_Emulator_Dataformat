# Vermont Research UD50 – backup data formats

This document describes the two backup formats of the Vermont Research UD50 solid-state disk emulator.
The UD50 emulates a 50 MB disk drive for a SEMS computer (France, 1979). The emulator keeps the disk in RAM and
saves/restores it to an internal SCSI backup medium (SyQuest, MO, …). Two emulator generations exist, and they write
**different backup formats**:

* **old format** – e.g. `DUPLIC_4_3_K1_FHD_SYQUEST.img`, `Duplic_4_3_K1_MO_FHD.img`, `K1_MHD_SYQUEST.img`
* **new format** – e.g. `S2_FHD_070208.img`, `S2_MHD_irgendwas.img`, the first 64 MiB of `K2_MHD.hda`

Everything below was reverse-engineered from these images. No emulator documentation was available. Every claim
is backed by the CRC check and by byte-exact rebuild tests. The key result: **both formats carry exactly the
same host bit stream**. Only the packaging around it differs, so data can be converted losslessly.

FHD = fixed-head disk, MHD = moving-head disk. Both use the same backup layout and geometry.

---

## 1. Disk geometry

The SEMS documentation gives **20 heads × 400 cylinders × 24 sectors** and **131 16-bit words per sector**
(2 header words + 128 data words + 1 CRC word).

The backups contain **406 cylinders per head** (0–405). Cylinders 400–405 are presumably spare or maintenance
cylinders; in DUPLIC they contain only filler.

| | value |
|---|---|
| heads | 20 |
| cylinders per head (stored) | 406 |
| sectors per track | 24 |
| data per sector | 128 words = 256 bytes |
| sectors in a backup | 20 × 406 × 24 = **194 880** |
| payload size | 194 880 × 256 = **49 889 280 bytes** |

Sector index used throughout: `index = (head * 406 + cyl) * 24 + sector`.

## 2. The host record (identical in both formats)

The host writes each sector as a serial bit stream. In **time order** it consists of:

| bits | content |
|---|---|
| 4 | sync nibble, time order `0 0 0 1` (value 8 read LSB-first) |
| 16 | header word 1 (`w0`), LSB first |
| 16 | header word 2 (`w1`), LSB first |
| 128 × 16 | data words, each LSB first |
| 16 | CRC, LSB first |

That is 4 + 2096 bits = 131 words plus the sync nibble.

**Header word 1 (`w0`):** bits 0–4 = sector (0–23), bit 5 = head bit 0, bits 6–14 = cylinder (0–405),
bit 15 = head bit 4.
**Header word 2 (`w1`):** bits 0–2 = head bits 1–3. Bits 4–15 almost always equal the upper 12 bits of the first data
word; their meaning is unknown.

```
head = (w0 >> 5 & 1) | (w1 & 7) << 1 | (w0 >> 15) << 4
cyl  = (w0 >> 6) & 0x1FF
sec  =  w0 & 0x1F
```

**CRC:** CRC-16/ARC (IBM): polynomial 0x8005 (reflected 0xA001), init 0, no final XOR. It is computed over the
**260 bytes** after the sync nibble (4 header bytes + 256 data bytes), each byte taken from 8 consecutive stream bits,
LSB first. The stored CRC follows little-endian.

**Data / character encoding:** the SEMS is a 16-bit machine with big-endian words. The tools write each data word
**high byte first** into `*_payload.bin`; that is the only byte reordering. Text is **7-bit ASCII with even parity in
bit 7** (see `SEMS_ASCII_TABLE.jpeg`, e.g. `A` = 41, `C` = C3, `S` = 53, space = A0). Unused sectors in DUPLIC contain
the filler word `0xE38E`.

## 3. Old backup format

### Overall layout

| range | content |
|---|---|
| 0x0000000 – 0x36FFFFF | 20 sections of **0x2C0000 bytes**, one per head |
| 0x3700000 – … | test pattern (each 16-bit word holds its own word address), other leftovers |

Each section holds 406 tracks. The remainder up to the next 0x2C0000 boundary is self-address fill.

### Track and block

A track is 24 blocks of **288 bytes** (144 LE words) plus **1 extra word**, 3457 words (6914 bytes) in total.
The extra word sits in front of sector 0 and repeats its self address. Sector 0 of cylinder 0 of head *h* (h ≥ 1)
begins **14 bytes before** the section boundary of head *h*.

Block layout (byte offsets from block start):

| bytes | content |
|---|---|
| +0 … +5 | tail of the previous record (last data word, CRC, a few trailing bits) |
| +6 … +11 | 0 |
| +12 … +13 | **self address**: `(offset / 2) & 0xFFFF` (rarely 0) |
| +14 … +29 | 0 |
| +30 … | **host record** as an **LSB-first bit stream**, shifted by `s` bits (0–15, varies per block) |

The bit shift `s` is found per block by requiring the sync nibble 8 **and** a valid CRC at offset +30 bytes + `s` bits.
The data then start at bit `(block + 30) * 8 + s + 36`.

## 4. New backup format

The new format is a 64 MiB file.

| range | content |
|---|---|
| 0x000 – 0x9FF | file header + table, **identical in all known images** |
| 0xA00 – ~0x3C3C700 | the 194 880 records, ordered head / cylinder / sector |
| up to 0x3FFF600 | gap pattern `[K2]` |
| rest up to 64 MiB | constant tail (copied from a reference image) |

**Record i:**
`E_i = 0xA10 + 324 * i + 960 * head` is the end of the gap pattern in front of the record.

* In front of `E_i` stands the gap/sync pattern **`[K2]`** (`5b 4b 32 5d`), normally 3 times (4 times before record 0).
  At a head change the whole extra gap of 960 bytes is filled with `[K2]`. The number of repetitions varies (2–6),
  and the run may reach a few bytes past `E_i`. This is probably write timing and carries no data.
* From `E_i` on, the record is stored as a **bit stream of 16-bit little-endian words, each word read from bit 15
  down to bit 0** (time order). It begins with zero bits, then at bit ≈ 231–273 (mostly 242–246) comes the sync
  nibble followed by **exactly the host record of section 2**. Zeros follow until the next `[K2]` run.

So the host bit stream is **identical** in old and new format. The tools rebuild all three new reference images
**byte for byte** from their extracted records, so the layout above is complete.

`K2_MHD.hda` is a dump of a larger backup medium. Only its first 64 MiB were written by the emulator; the rest is
older data on the medium (95.8 % zeros, test patterns such as `UUUU…`, `KKKK…` and ASCII sequences). It contains
neither `[K2]` nor any old-format blocks.

## 5. Extraction and conversion

### Old format → payload (`tools/ud50_extract_crc.py`)

1. Every 16-bit word equal to its own address is a candidate self address. Candidate block starts lie 12 bytes
   (normal) or 14 bytes (sector 0) before it.
2. For each candidate, the shift `s` (0–15) is chosen where the sync nibble is 8 **and** CRC-16/ARC is valid.
3. The sector is placed by its header words (head/cylinder/sector), **not** by its position in the image.
4. A second pass looks for blocks without a self address 288/290 bytes next to an already found neighbour.
5. Status per sector in `*_blocks.csv`:

| status | meaning |
|---|---|
| `ok` | CRC valid |
| `HDRBIT` | one flipped bit in header word 1; CRC valid after correcting it (data confirmed) |
| `CRCBIT` | the stored CRC differs from the computed one in exactly one bit |
| `BADCRC` | expected header found, CRC wrong (data unverified) |
| `STRAY` | valid record found outside its head's section |
| `MISSING` | not in the image; filled with `**MISSING SECTOR**` |

Payload bits are never changed. Parity stays as stored.

### New format → payload (`tools/ud50new_extract.py`)

Each `[K2]` run is followed by the record. The tool reads it as 16-bit LE words MSB-first, finds the nibble where
the CRC is valid, and places the sector by its header words.

### Building a new-format image (`tools/ud50new_build.py`)

The tool copies the header from a reference new-format image. It then writes every record into its slot: `[K2]` ×3,
zeros, the **unchanged host bit stream** (nibble + 2096 bits) at bit 245 (`--nib`), and zeros. Options:

* `--old2` – a second old-format copy; it replaces records that are not `ok` in the first.
* `--fix-hdrbit` – corrects the single flipped header bit of `HDRBIT` records, but only if the CRC then becomes valid.
* `--fill-missing --fill-word XXXX` – generates missing sectors with correct header words and CRC.
* `--new IMG CSV --keep-timing` – rebuilds a new-format image exactly (verification).

## 6. Results on the available images

| image | format | valid CRC | special | missing |
|---|---|---|---|---|
| DUPLIC_4_3_K1_FHD_SYQUEST.img | old | 194 877 | 1 HDRBIT, 1 CRCBIT | 1 |
| Duplic_4_3_K1_MO_FHD.img | old | 194 877 | 1 HDRBIT, 1 BADCRC | 1 |
| K1_MHD_SYQUEST.img | old | 193 176 | 1 STRAY, 1 BADCRC | 1 702 |
| K2_MHD.hda (first 64 MiB) | new | 194 880 | – | 0 |
| S2_FHD_070208.img | new | 194 880 | – | 0 |
| S2_MHD_irgendwas.img | new | 194 880 | – | 0 |

* **DUPLIC SYQUEST vs. MO:** the payloads are bit-identical. Each copy has exactly one backup flaw, and the other copy
  covers it:
  * SYQUEST has one flipped CRC bit (head 1/cyl 81/sec 3); MO is correct there.
  * MO loses 5 bits exactly at its 32 MiB boundary (head 11/cyl 265/sec 9); SYQUEST is correct there.
  * Both share one flipped header bit (head 19/cyl 179/sec 5, `ade5` instead of `ace5`; filler data).
  * Both lack head 0/cyl 0/sec 0.
* **K1:** the first track of head 0 is overwritten at the start of the file. Heads 18 and 19 end at cylinder 370 in this
  backup.
* **New-format images:** all three rebuild byte-identically with `ud50new_build.py --new … --keep-timing`.

## 7. DUPLIC conversion

```
python tools/ud50new_build.py S2_FHD_070208.img DUPLIC_4_3_K1_FHD_new.img \
    --old  DUPLIC_4_3_K1_FHD_SYQUEST.img DUPLIC_4_3_K1_FHD_SYQUEST_blocks.csv \
    --old2 Duplic_4_3_K1_MO_FHD.img      Duplic_4_3_K1_MO_FHD_blocks.csv \
    --fix-hdrbit --fill-missing --fill-word 0000
```

* The host bit stream of every sector is copied unchanged. Head 1/cyl 81/sec 3 comes from the MO copy.
* Head 19/cyl 179/sec 5: the flipped header bit was corrected (`--fix-hdrbit`). The CRC is then valid, and the data are
  unchanged.
* Head 0/cyl 0/sec 0 is missing in both old images. It was generated with zero data, correct header words and CRC.
  K1, K2 and S2_MHD also hold only zeros in this sector.
* **Round trip:** extracting the generated image again gives 194 880 of 194 880 sectors with a valid CRC.
  194 879 of them are bit-identical with the payload extracted from the old image; the only difference is the
  generated sector 0.

## 8. History: a misread of the new format

At first I read the new format byte by byte, MSB first, instead of as 16-bit LE words. Text then looked *almost*
right, but bits 5–7 seemed corrupted (`SYSTEME` → `S9STEME`, space → `@`), and the CRC failed. With the correct
16-bit word order every record has a valid CRC. If you see such near-miss text in a similar format, check the
word order first.
