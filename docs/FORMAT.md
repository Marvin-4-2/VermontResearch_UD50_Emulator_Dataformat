# Vermont Research UD50 emulators – backup data formats

**UD50** is a 50 MB disk drive of a SEMS computer (France, 1979). Vermont Research built solid-state emulators
that replace this drive. An emulator keeps the drive contents in RAM and saves/restores them to an internal SCSI
backup medium (SyQuest, MO, …). This document describes the backup formats of the two emulator versions:

* **old format** – written by the **older emulator** (model name unknown), e.g. `DUPLIC_4_3_K1_FHD_SYQUEST.img`,
  `Duplic_4_3_K1_MO_FHD.img`, `K1_MHD_SYQUEST.img`
* **K2 format** – written by the newer **K2** emulator, e.g. `S2_FHD_070208.img`, `S2_MHD_irgendwas.img`, the first
  64 MiB of `K2_MHD.hda` and of `HD00_imaged.hda`. Its gap marker is the ASCII string `[K2]`. Sections and tools below that say "new format"
  mean the K2 format.

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

## 3. Old backup format (older emulator)

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

## 4. New backup format (K2 emulator)

The K2 format is a 64 MiB file.

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

**`[K2]` is not required.** In `HD00_imaged.hda`, a K2 backup with DUPLIC on it that the K2 emulator reads back,
all gaps and the area after the last record are zeros. Nevertheless all 194 880 records sit exactly at `E_i` and have
a valid CRC; there the nibble is at bit 239–242. `tools/ud50k2_slot_extract.py` extracts such images by slot position.

**The backup is a RAM image.** The maintenance interface of the K2 emulator can dump its RAM
(`AAAAAAAA = WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW`, the address counts 32-bit words). Written as little-endian
32-bit words, the dump is byte-identical to `HD00_imaged.hda` from offset 0xA00 (checked for 70 400 bytes). So the K2
backup is a **1:1 copy of the emulator RAM preceded by the 0xA00-byte file header**: RAM word address `A` ↔ file
offset `0xA00 + 4·A`. The emulator holds the tracks in RAM as bit streams with gaps, and the `[K2]` gaps seen in
other images are presumably the RAM's initial fill. The maintenance interface can also write RAM, which would be
a way to load an image without a SCSI backup device (not tried yet).

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
| HD00_imaged.hda (first 64 MiB) | new, zero gaps | 194 880 | – | 0 |

* **DUPLIC SYQUEST vs. MO:** the payloads are bit-identical. Each copy has exactly one backup flaw, and the other copy
  covers it:
  * SYQUEST has one flipped CRC bit (head 1/cyl 81/sec 3); MO is correct there.
  * MO loses 5 bits exactly at its 32 MiB boundary (head 11/cyl 265/sec 9); SYQUEST is correct there.
  * Both share one flipped header bit (head 19/cyl 179/sec 5, `ade5` instead of `ace5`; filler data).
  * Both lack head 0/cyl 0/sec 0.
* **K1:** the first track of head 0 is overwritten at the start of the file. Heads 18 and 19 end at cylinder 370 in this
  backup.
* **New-format images:** all three rebuild byte-identically with `ud50new_build.py --new … --keep-timing`.
* **HD00 (K2, DUPLIC):** 4 620 of the 4 623 data sectors of the old DUPLIC backup are bit-identical here. The other
  three (head 0/cyl 0, physical sectors 1, 6, 15) differ in 1–3 bytes, probably state data. Every other sector holds a
  fill pattern instead of `E38E`: below cylinder 200 each word is `cyl·0x40 + logical sector` (the sector's own logical
  address, see section 8), above it other test patterns. Head 0/cyl 0/sec 0, missing in both old backups, holds only
  this pattern here, so it is not part of the program.
  * Real content (sectors that are not constant) amounts to 4 234 sectors, 3 963 of them distinct (≈ 1 MB), all on
    heads 0–1, cylinders 0–172. Besides DUPLIC this includes a test library: a command file (`FICHIER DE COMMANDE
    POUR LANCEMENT DE TESTS`), several test kernels (`NOYAU DE TEST MEMOIRE`, `… INSTRUCTIONS`,
    `… VERSION SOLAR 16-85`, …), bootstrap and monitor. The computer is a SEMS **SOLAR 16**.

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
  K1, K2 and S2_MHD also hold only zeros in this sector, and in HD00 it holds only a fill pattern.
* **Round trip:** extracting the generated image again gives 194 880 of 194 880 sectors with a valid CRC.
  194 879 of them are bit-identical with the payload extracted from the old image; the only difference is the
  generated sector 0.

### K2 format → old format

Not implemented yet. The host records can be extracted from K2 images with `ud50new_extract.py`. A builder for
the old block layout (self addresses, per-block bit shift, extra word before sector 0, section fill, test pattern
after 0x3700000) is still missing. Whether the older emulator accepts the shift 0 everywhere is unknown.

## 8. SEMS disk file system (sectors 0–4)

Source: SEMS documentation, chapter 12.11 "Utilisation des supports disques" (`Disk_geometry_1..3.jpeg`).

**Sector numbering.** The documentation counts **logical** sectors: logical sector n is **physical sector n+1**
(mod 24) on a track, so physical sector 0 is logical sector 23. Disk addresses count sectors **cylinder by
cylinder across all 20 heads**:

```
disk address = cyl * 480 + head * 24 + logical sector
```

Sector 4 confirms this: "taille secteur" = 128 words and "taille cylindre" = 480 sectors (20 heads × 24). Note that the
`*_payload.bin` files are ordered head by head. The cylinder-major order was checked at track boundaries: there, text
and code continue in the cylinder-major successor 306 times and in the head-major one only 115 times.

| logical sector | content |
|---|---|
| 0–2 | RAPD (bootstrap loader); sector 2 also holds the system table |
| 3 | system information |
| 4 | space table |

**Sector 2:** word 0 RAPD start address, word 1 max. system number + 1, then for systems 0–7 four words each
(words 2–33): memory address, start address, disk address, length in words. The RAPD program follows.

**Sector 3:**

| words | content |
|---|---|
| 0–7 | table of defective cylinders |
| 8 | validation code |
| 9–12 | label |
| 13 | structure code |
| 16+3k … 18+3k | file name of system k (k = 0–7) |
| 64+2k / 65+2k | start / end disk address of system k |

**Sector 4:**

| words | content |
|---|---|
| 0–3 | label |
| 4–6 | support code, sector size, cylinder size |
| 7 / 8 | NBESP (number of spaces, high byte) / NBFMS |
| 12+4k … 15+4k | space k (k = 0–27): indicator, LTAG, disk address, length |

**Values in S2_FHD** (S2_MHD and K2_MHD are the same apart from names):
* Defective-cylinder table `0190` = 400, so cylinders 400–405 are locked. This explains the 406 stored cylinders.
* Validation code `89AB`, label `SRBFCC1`, structure code 2.
* Support code 2, 128 words per sector, 480 sectors per cylinder, NBESP 6.
* Spaces 2–5 have address/length 5/40, 47/260, 307/23 and 330/70, while spaces 0 and 1 are zero. Since the last one
  ends exactly at 400, these values are apparently in cylinders; this is not confirmed.

**Systems** (`tools/ud50_systems.py PAYLOAD OUT`; tables in `results/systems/`):

| k | S2_FHD | S2_MHD / K2_MHD | memory | start | disk address | words |
|---|---|---|---|---|---|---|
| 0 | BOSDFH | BOSDMH | 0354 | 448A | 0x005–0x0FE | 31 916 |
| 1 | RTSDFH | RTSDMH | 0140 | 56B3 | 0x1F4–0x3F0 | 65 089 |
| 2 | RTSDFH | RTSDMH | 0140 | 4A19 | 0x3F1–0x5E4 | 19 687 |
| 6 | BDFHWI | BOSDMH | 1255 / 106F | 44B5 / 44AE | 0x640–0x71B / 0x71F | 28 059 / 28 545 |
| 7 | FORMAF | FORMAF | 1400 | 1620 | 0x12C–0x13F | 2 556 |

Sectors 2 and 3 agree on all disk addresses. The contents fit the names:
* BOS contains `** RECHNER S2 FHD **` and `BETRIEBSSYSTEME: BOSDFH V9.7 UND RTS…`.
* RTS is the real-time system.
* FORMAF is the formatter (`REPRISE SUR DEFAUT SECTEUR`, `PERIPH. BOOTSTRAPABLE (Y-N)`).

FORMAF is identical in all three images, and BOSDFH and BOSDMH agree in 95 % of their bytes.

**The DUPLIC disk does not use this structure.** In HD00, logical sectors 1 and 3 are unwritten (fill pattern), and
logical sector 4 already contains DUPLIC text (`FICHIER BOOTSTRAP + MONITEUR`). It is a stand-alone bootable test
disk, not a file-system volume, so it has no directory. Logical sector 2 has `0880` in word 0 and `00AC` (= 172) in
word 1; 172 matches the last used cylinder.

## 9. History: a misread of the new format

At first I read the new format byte by byte, MSB first, instead of as 16-bit LE words. Text then looked *almost*
right, but bits 5–7 seemed corrupted (`SYSTEME` → `S9STEME`, space → `@`), and the CRC failed. With the correct
16-bit word order every record has a valid CRC. If you see such near-miss text in a similar format, check the
word order first.
