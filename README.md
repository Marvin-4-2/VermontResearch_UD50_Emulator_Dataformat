# Vermont Research UD50 emulators – backup data formats

**UD50** is a 50 MB disk drive of a **SEMS** computer (France, 1979). Vermont Research built solid-state
emulators that replace this drive. An emulator keeps the drive contents in RAM and saves/restores them to an
internal SCSI backup medium. There are two emulator versions, and they write **different backup formats**:

* an **older emulator** (model name unknown) – the "old format"
* the newer **K2** emulator – the "K2 format" (its backup images even contain the gap marker `[K2]`)

This project compares and reverse-engineers both backup formats. It provides tools that extract the real UD50
drive contents from either format and convert one format into the other. The immediate goal is to bring software
that exists only as an old-format backup (*DUPLIC*, a test program) onto K2 emulators.

**Status:** both formats are fully decoded. Every sector is verified by its CRC.
* Conversion **old → K2** works, and the three K2 reference images can be rebuilt byte for byte.
* A converted DUPLIC image exists, but it has **not yet been tested on real hardware**.
* A genuine K2 backup with DUPLIC on it (`HD00_imaged.hda`) has since turned up, and the K2 emulator reads it back.
  Its DUPLIC data are bit-identical with the old backup.
* Conversion **K2 → old** is not implemented yet (see [Open issues](#open-issues)).

## Key findings

* Geometry: 20 heads × 406 cylinders (400 documented) × 24 sectors, 128 data words per sector.
* Both formats contain **the same host bit stream**: sync nibble, 2 header words, 128 data words, CRC-16/ARC.
  Only the packaging differs.
  * **Old format (older emulator):** 288-byte blocks with a self address, the host stream stored LSB-first with a
    varying bit shift.
  * **K2 format (K2 emulator):** fixed 324-byte slots separated by the gap pattern `[K2]`, the host stream stored as
    16-bit little-endian words read MSB-first.
* The K2 backup is a **1:1 copy of the emulator RAM** behind a 0xA00-byte header, as a RAM dump from the
  maintenance interface shows. The `[K2]` gap marker is not required; some K2 backups have zero gaps.
* Text on the SEMS (a **SOLAR 16**) is 7-bit ASCII with **even parity in bit 7**, and words are big-endian.
* What is stored *on* the disks (SEMS disk layout, file system, operating system) is documented in the separate,
  currently private project **SEMS_SOLAR_16_65_Revival**, which aims at getting a real SOLAR 16-65 running again.

The full description is in **[docs/FORMAT.md](docs/FORMAT.md)**.

## Tools

The tools need Python 3 and numpy (`pip install -r requirements.txt`).

| script | purpose |
|---|---|
| `tools/ud50_extract_crc.py IMAGE [OUT] [END] [CYLS] [HEADS]` | old format → `*_payload.bin` + `*_blocks.csv`; CRC-verified, sectors placed by header words (recommended) |
| `tools/ud50_extract.py IMAGE [OUT] [END]` | first, order-based old-format extractor (kept for reference; misses sector 0 of heads 1–19) |
| `tools/ud50new_extract.py IMAGE [OUT] [CYLS] [HEADS]` | K2 format → `*_payload.bin` + `*_records.csv` |
| `tools/ud50k2_slot_extract.py IMAGE OUT_PREFIX` | K2 format by slot position, for images without `[K2]` gaps |
| `tools/ud50new_build.py REF OUT.img --old IMG CSV [...]` | builds a K2-format image from old-format records; `--new IMG CSV --keep-timing` rebuilds a K2 image exactly || `tools/ud50_strings.py PAYLOAD.bin [MIN_LEN] [OUT.txt]` | lists 7-bit/even-parity text strings with sector positions (sanity check) |

For old-format images use `END = 0x3700000`.

The `ud50new_*` tools handle the K2 format; the names are kept for compatibility.

Example: converting DUPLIC to the K2 format:

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
* `results/new_format/` – K2 format: `*_records.csv.gz` and string lists for K2_MHD, S2_FHD, S2_MHD and HD00.
* `results/conversion/` – record table of the converted DUPLIC image (K2 format).
The DUPLIC string list was made with the first extractor, so its 20 sector-0 entries are placeholders.

| image | format | sectors with valid CRC (of 194 880) |
|---|---|---|
| DUPLIC_4_3_K1_FHD_SYQUEST.img | old | 194 877 (+1 header-bit flip, +1 CRC-bit flip, 1 missing) |
| Duplic_4_3_K1_MO_FHD.img | old | 194 877 (+1 header-bit flip, +1 backup artifact, 1 missing) |
| K1_MHD_SYQUEST.img | old | 193 176 (1 702 missing in the backup) |
| K2_MHD.hda (first 64 MiB) | K2 | 194 880 |
| S2_FHD_070208.img | K2 | 194 880 |
| S2_MHD_irgendwas.img | K2 | 194 880 |
| HD00_imaged.hda (first 64 MiB) | K2, zero gaps | 194 880 (DUPLIC, read back by the K2 emulator) |
| converted DUPLIC | K2 | 194 880 (round trip bit-identical except the generated sector 0) |

## Open issues

* **Conversion K2 → old format** is not implemented yet. The host records can already be extracted from K2 images;
  what is missing is a builder that writes the old block layout (self addresses, bit shifts, section fill).
* **Hardware test of the converted image.** At power-on, the K2 emulator restores its RAM from the SCSI backup
  medium. With a **BlueSCSI** as the backup device it loops forever: it sends TEST UNIT READY, BlueSCSI answers GOOD,
  and the emulator sends TEST UNIT READY again.
  * SyQuest and Quantum ELS drives work. A Fujitsu MO drive fails the same way; it worked with the older emulator.
  * Already tried without effect: `EnableSCSI2=0`, `SelectionDelay`, `EnableParity`, `EnableUnitAttention=1`, all
    termination settings.
  * Main suspect: bus timing or handshake. The fast targets fail, the slow SCSI-1-era drives work. This is unverified.
  * Next steps: a BlueSCSI debug log, then a logic-analyzer comparison of a working and a failing drive.
* The meaning of the upper 12 bits of header word 2 and the content of the 0xA00-byte file header of the K2
  format are not understood; both are copied verbatim.
* Head 0/cyl 0/sec 0 of DUPLIC is missing in both old backups. It is generated with zero data; in HD00 it holds only
  a fill pattern, so it is not part of the program.
* Loading an image through the maintenance interface (it can write RAM) could bypass the SCSI problem; not tried yet.

## Files

```
docs/FORMAT.md            format description
docs/SEMS_ASCII_TABLE.jpeg  SEMS ASCII code table (even parity), from the system documentationtools/                    Python tools
results/                  per-sector tables and string lists (gzip)
```

## License

The tools and documentation are released under the [MIT License](LICENSE). The scanned SEMS documentation pages
and the software contents in the result files belong to their respective owners.
