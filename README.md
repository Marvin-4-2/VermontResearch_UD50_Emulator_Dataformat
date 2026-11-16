# Vermont Research UD50 Emulator – backup data format

This repository contains the reverse-engineered backup formats of the **Vermont Research UD50**, a solid-state
disk emulator that stands in for a 50 MB disk drive on a **SEMS** computer (France, 1979). It also contains Python
tools that extract, verify and convert backup images.

The UD50 keeps the emulated disk in RAM and saves/restores it to an internal SCSI backup medium. The two emulator
generations write **different backup formats**. The goal of this project is to bring software that exists only as an
old-format backup (*DUPLIC*, a test program) onto new-generation emulators.

**Status:** both formats are fully decoded. Every sector is verified by its CRC. The three new-format reference images
can be rebuilt byte for byte. A converted DUPLIC image exists, but it has **not yet been tested on real hardware**
(see [Open issues](#open-issues)).

## Key findings

* Geometry: 20 heads × 406 cylinders (400 documented) × 24 sectors, 128 data words per sector.
* Both formats contain **the same host bit stream**: sync nibble, 2 header words, 128 data words, CRC-16/ARC.
  Only the packaging differs.
  * **Old format:** 288-byte blocks with a self address, the host stream stored LSB-first with a varying bit shift.
  * **New format:** fixed 324-byte slots separated by the gap pattern `[K2]`, the host stream stored as 16-bit
    little-endian words read MSB-first.
* Text on the SEMS is 7-bit ASCII with **even parity in bit 7**, and words are big-endian.

The full description is in **[docs/FORMAT.md](docs/FORMAT.md)**.

## Tools

The tools need Python 3 and numpy (`pip install -r requirements.txt`).

| script | purpose |
|---|---|
| `tools/ud50_extract_crc.py IMAGE [OUT] [END] [CYLS] [HEADS]` | old format → `*_payload.bin` + `*_blocks.csv`; CRC-verified, sectors placed by header words (recommended) |
| `tools/ud50_extract.py IMAGE [OUT] [END]` | first, order-based old-format extractor (kept for reference; misses sector 0 of heads 1–19) |
| `tools/ud50new_extract.py IMAGE [OUT] [CYLS] [HEADS]` | new format → `*_payload.bin` + `*_records.csv` |
| `tools/ud50new_build.py REF OUT.img --old IMG CSV [...]` | builds a new-format image from old-format records; `--new IMG CSV --keep-timing` rebuilds an image exactly |
| `tools/ud50_strings.py PAYLOAD.bin [MIN_LEN] [OUT.txt]` | lists 7-bit/even-parity text strings with sector positions (sanity check) |

For old-format images use `END = 0x3700000`.

Example: converting DUPLIC to the new format:

```
python tools/ud50_extract_crc.py DUPLIC_4_3_K1_FHD_SYQUEST.img out 0x3700000
python tools/ud50_extract_crc.py Duplic_4_3_K1_MO_FHD.img      out 0x3700000
python tools/ud50new_build.py S2_FHD_070208.img DUPLIC_4_3_K1_FHD_new.img \
    --old  DUPLIC_4_3_K1_FHD_SYQUEST.img out/DUPLIC_4_3_K1_FHD_SYQUEST_blocks.csv \
    --old2 Duplic_4_3_K1_MO_FHD.img      out/Duplic_4_3_K1_MO_FHD_blocks.csv \
    --fix-hdrbit --fill-missing --fill-word 0000
python tools/ud50new_extract.py DUPLIC_4_3_K1_FHD_new.img out    # round-trip check
```

## Results

`results/` holds gzip-compressed per-sector tables and string lists. The disk images and payload binaries are
**not** included.

* `results/old_format/` – `*_blocks.csv.gz` (offset, bit shift, header words, CRC, status per sector) for
  the DUPLIC SYQUEST, DUPLIC MO and K1 images, plus string lists.
* `results/new_format/` – `*_records.csv.gz` and string lists for K2, S2_FHD and S2_MHD.
* `results/conversion/` – record table of the converted DUPLIC image.

The DUPLIC string list was made with the first extractor, so its 20 sector-0 entries are placeholders.

| image | format | sectors with valid CRC (of 194 880) |
|---|---|---|
| DUPLIC_4_3_K1_FHD_SYQUEST.img | old | 194 877 (+1 header-bit flip, +1 CRC-bit flip, 1 missing) |
| Duplic_4_3_K1_MO_FHD.img | old | 194 877 (+1 header-bit flip, +1 backup artifact, 1 missing) |
| K1_MHD_SYQUEST.img | old | 193 176 (1 702 missing in the backup) |
| K2_MHD.hda (first 64 MiB) | new | 194 880 |
| S2_FHD_070208.img | new | 194 880 |
| S2_MHD_irgendwas.img | new | 194 880 |
| converted DUPLIC | new | 194 880 (round trip bit-identical except the generated sector 0) |

## Open issues

* **Hardware test of the converted image.** At power-on, the new emulator restores its RAM from the SCSI backup
  medium. With a **BlueSCSI** as the backup device it loops forever: it sends TEST UNIT READY, BlueSCSI answers GOOD,
  and the emulator sends TEST UNIT READY again.
  * SyQuest and Quantum ELS drives work. A Fujitsu MO drive fails the same way; it worked with the old emulators.
  * Already tried without effect: `EnableSCSI2=0`, `SelectionDelay`, `EnableParity`, `EnableUnitAttention=1`, all
    termination settings.
  * Main suspect: bus timing or handshake. The fast targets fail, the slow SCSI-1-era drives work. This is unverified.
  * Next steps: a BlueSCSI debug log, then a logic-analyzer comparison of a working and a failing drive.
* The meaning of the upper 12 bits of header word 2 and the content of the 0xA00-byte file header of the new
  format are not understood; both are copied verbatim.
* Head 0/cyl 0/sec 0 of DUPLIC is missing in both old backups. It is generated with zero data.

## Files

```
docs/FORMAT.md            format description
docs/SEMS_ASCII_TABLE.jpeg  SEMS ASCII code table (even parity), from the system documentation
tools/                    Python tools
results/                  per-sector tables and string lists (gzip)
```
