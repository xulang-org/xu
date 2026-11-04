#!/usr/bin/env python3
"""ESP32 esp_image (app binary) pack/unpack for the Xu Xtensa target.

An ESP32 app image is:

    esp_image_header_t   24 bytes
    segment[0]  hdr       8 bytes (load_addr, data_len)
                data      data_len bytes
    segment[1]  hdr ...
    ...
    sha256[32]            only when header.hash_appended == 1

Reaching the toolchain on the mirror is the real oracle: this script is
validated by byte-identical round-trip against the firmware already living
in the app0 partition.

Usage:
    esp32_image.py pack   <elf> <app.bin>       # build bootable image from Xu ELF
    esp32_image.py unpack <app.bin> <outdir>     # extract segments
    esp32_image.py repack <outdir> <app.bin>     # rebuild from segments
    esp32_image.py info    <app.bin>             # print layout
    esp32_image.py verify  <app.bin>             # structural + hash check
"""
import hashlib
import struct
import sys
from pathlib import Path

ESP_MAGIC = 0xE9
HEADER_LEN = 24
SEG_HDR_LEN = 8


def app_descriptor():
    """Reproducible app identity bound to this checkout's product version."""
    version = (Path(__file__).resolve().parents[1] / "VERSION").read_text().strip().encode("ascii")
    if not version or len(version) > 31:
        sys.exit("error: VERSION must fit the ESP32 application descriptor")
    desc = bytearray(256)
    struct.pack_into("<I", desc, 0, 0xABCD5432)
    desc[16:16 + len(version)] = version
    desc[48:56] = b"xu_esp32"
    return bytes(desc)

# chip_id values (soc_caps.h)
CHIPS = {0: "ESP32", 1: "ESP32-S2", 5: "ESP32-C3", 9: "ESP32-S3",
         6: "ESP32-C2", 10: "ESP32-C6", 17: "ESP32-H2", 2: "ESP32-S3P"}

# Load-address classification. Per the ESP32 memory map (soc.h):
#   DROM  0x3F400000-0x3F800000   read-only data mapped from flash
#   DRAM  0x3FFAE000-0x40000000   copied into RAM at boot
#   IRAM  0x40080000-0x400AA000   copied into RAM, executable
#   IROM  0x400D0000-0x40400000   code mapped from flash, executable
# Anything outside these is reported as UNKNOWN rather than guessed.


def classify(addr):
    if addr == 0x00000000:
        return "PADDING"
    if 0x3F400000 <= addr < 0x3F800000:
        return "DROM"
    if 0x3FFAE000 <= addr < 0x40000000:
        return "DRAM"
    if 0x40080000 <= addr < 0x400AA000:
        return "IRAM"
    if 0x400D0000 <= addr < 0x40400000:
        return "IROM"
    if 0x3FF00000 <= addr < 0x3FFB0000:
        return "DPORT"
    return "UNKNOWN"


def checked_load_size(address, size, radio=False):
    """Validate before allocating zero-fill for an untrusted ELF segment."""
    region = classify(address)
    limits = {"DROM": 0x3F800000, "DRAM": 0x40000000,
              "IRAM": 0x400AA000, "IROM": 0x40400000}
    padded = (size + 3) & ~3
    if region not in limits or size <= 0 or padded > limits[region] - address:
        sys.exit(f"error: load segment outside ESP32 memory at 0x{address:08X}")
    if radio and region == "DRAM" and (address != 0x3FFC0000 or address + padded > 0x3FFD2000):
        sys.exit("error: radio profile requires Xu data/heap within 0x3FFC0000..0x3FFD2000")
    if radio and region == "IRAM" and address + padded > 0x400A0000:
        sys.exit("error: radio profile requires IRAM code below the ROM DRAM alias at 0x400A0000")


def check_load_layout(segments, entry):
    previous_end = 0
    flash_pages = set()
    executable_entry = False
    for address, data in sorted((a, d) for a, d in segments if a != 0):
        end = address + ((len(data) + 3) & ~3)
        if address < previous_end:
            sys.exit(f"error: overlapping load segments at 0x{address:08X}")
        previous_end = end
        region = classify(address)
        if region in {"IRAM", "IROM"} and address <= entry < end:
            executable_entry = True
        if region in {"DROM", "IROM"}:
            pages = set(range(address >> 16, ((end - 1) >> 16) + 1))
            if pages & flash_pages:
                sys.exit("error: flash-mapped load segments share a virtual MMU page")
            flash_pages.update(pages)
    if not executable_entry:
        sys.exit("error: primary entry is outside executable load segments")


class Header:
    __slots__ = ("magic", "segcount", "spi_mode", "spi_size_freq", "entry",
                 "wp_pin", "spi_pin_drv", "chip_id", "min_rev", "min_rev_full",
                 "max_rev_full", "reserved", "hash_appended")

    def __init__(self, raw):
        (self.magic, self.segcount, self.spi_mode,
         self.spi_size_freq) = struct.unpack("<BBBB", raw[0:4])
        self.entry, self.wp_pin = struct.unpack("<IB", raw[4:9])
        self.spi_pin_drv = raw[9:12]
        (self.chip_id, self.min_rev, self.min_rev_full,
         self.max_rev_full) = struct.unpack("<BBBB", raw[12:16])
        # Bytes 16..22 are reserved and must survive a round trip verbatim;
        # some firmwares leave them 0xFF rather than zeroed.
        self.reserved = raw[16:23]
        self.hash_appended = raw[23]

    def pack(self):
        out = bytearray(HEADER_LEN)
        out[0:4] = struct.pack("<BBBB", self.magic, self.segcount,
                               self.spi_mode, self.spi_size_freq)
        out[4:9] = struct.pack("<IB", self.entry, self.wp_pin)
        out[9:12] = bytes(self.spi_pin_drv)
        out[12:16] = struct.pack("<BBBB", self.chip_id, self.min_rev,
                                 self.min_rev_full, self.max_rev_full)
        out[16:23] = bytes(self.reserved)
        out[23] = self.hash_appended
        return bytes(out)


def parse(path, allow_partial=False):
    with open(path, "rb") as source:
        raw = source.read()
    if len(raw) < HEADER_LEN:
        sys.exit("error: file shorter than esp_image header")
    h = Header(raw)
    if h.magic != ESP_MAGIC:
        sys.exit(f"error: bad magic 0x{h.magic:02X} (want 0x{ESP_MAGIC:02X})")

    off = HEADER_LEN
    segs = []
    truncated_at = None
    for i in range(h.segcount):
        if off + SEG_HDR_LEN > len(raw):
            truncated_at = i
            break
        load, dlen = struct.unpack("<II", raw[off:off + SEG_HDR_LEN])
        off += SEG_HDR_LEN
        if off + dlen > len(raw):
            if not allow_partial:
                sys.exit(f"error: truncated segment {i} data "
                         f"(want {dlen}, have {len(raw) - off})")
            segs.append((load, raw[off:], dlen))
            truncated_at = i
            break
        segs.append((load, raw[off:off + dlen], dlen))
        off += dlen

    # In standard esp_image format:
    # 1. Segment data ends at `off`.
    # 2. Padding to (16 - 1) bytes, followed by 1-byte XOR checksum at (offset % 16 == 15).
    # 3. 32-byte SHA256 digest appended at the very end when hash_appended == 1.
    digest = b""
    trailing = b""
    if truncated_at is None:
        r = off % 16
        pad_chk = (15 - r) + 1  # padding + checksum byte
        off += pad_chk
        digest = raw[off:off + 32] if h.hash_appended else b""
        off += 32 if h.hash_appended else 0
        trailing = raw[off:]

    return h, segs, digest, trailing, raw, truncated_at


def build(h, segs, digest=b""):
    h.segcount = len(segs)
    h.hash_appended = 1 if digest else 0
    out = bytearray(h.pack())
    for load, data in segs:
        out += struct.pack("<II", load, len(data))
        out += data
    if digest:
        out += digest
    return bytes(out)


def image_sha256(raw, digest_len=32):
    return hashlib.sha256(raw[:len(raw) - digest_len]).digest()


def cmd_info(path):
    h, segs, digest, trailing, raw, trunc = parse(path, allow_partial=True)
    print(f"file          : {path}")
    print(f"size          : {len(raw)} bytes"
          + (f"  (PARTIAL: segment {trunc} of {h.segcount} cut off)"
             if trunc is not None else ""))
    print(f"magic         : 0x{h.magic:02X}")
    print(f"chip          : {CHIPS.get(h.chip_id, 'unknown')} "
          f"(id={h.chip_id})")
    print(f"min_rev       : {h.min_rev} (min_full={h.min_rev_full}, "
          f"max_full={h.max_rev_full})")
    print(f"entry_addr    : 0x{h.entry:08X}  [{classify(h.entry)}]")
    print(f"spi_mode      : 0x{h.spi_mode:02X}")
    print(f"spi_size_freq : 0x{h.spi_size_freq:02X} "
          f"(size={h.spi_size_freq >> 4}, freq={h.spi_size_freq & 0x0F})")
    print(f"wp_pin        : {h.wp_pin}"
          + ("  (disabled)" if h.wp_pin == 0xEE else ""))
    print(f"spi_pin_drv   : {list(h.spi_pin_drv)}")
    print(f"hash_appended : {h.hash_appended}")
    print(f"segments      : {len(segs)} declared {h.segcount}")
    for i, (load, data, dlen) in enumerate(segs):
        cut = "" if len(data) == dlen else f"  [have {len(data)} of {dlen}]"
        print(f"  [{i}] {classify(load):<8} load=0x{load:08X} "
              f"size={dlen:>9} (0x{dlen:X}){cut}")
    if trailing:
        print(f"trailing      : {len(trailing)} bytes (unexpected)")
    print(f"accounted     : {len(raw) - len(trailing)} bytes")


def cmd_verify(path):
    h, segs, digest, trailing, raw, trunc = parse(path)
    ok = True
    checksum = 0xEF
    segment_end = HEADER_LEN
    for _, data, size in segs:
        segment_end += SEG_HDR_LEN + size
        for byte in data:
            checksum ^= byte
    checksum_offset = segment_end + (15 - segment_end % 16)
    if checksum_offset >= len(raw):
        print("FAIL missing segment XOR checksum")
        ok = False
    elif raw[checksum_offset] != checksum:
        print(f"FAIL segment XOR checksum: stored 0x{raw[checksum_offset]:02X}, "
              f"calculated 0x{checksum:02X}")
        ok = False
    else:
        print("PASS segment XOR checksum")
    if trailing:
        print(f"FAIL trailing data: {len(trailing)} bytes")
        ok = False
    if h.hash_appended:
        if not digest or len(digest) != 32:
            print("FAIL hash_appended set but no 32-byte digest")
            ok = False
        else:
            calc = image_sha256(raw)
            if calc == digest:
                print("PASS sha256 trailer matches image body")
            else:
                print(f"FAIL sha256 mismatch\n  stored {digest.hex()}\n"
                      f"  calc   {calc.hex()}")
                ok = False
    else:
        print("PASS no hash trailer (hash_appended=0)")
    unknown = [i for i, (load, _, _) in enumerate(segs)
               if classify(load) == "UNKNOWN"]
    if unknown:
        print(f"WARN segments outside known ESP32 memory map: {unknown}")
    else:
        print("PASS all segments fall in a known ESP32 region")
    print("RESULT:", "OK" if ok else "BROKEN")
    return 0 if ok else 1


def cmd_unpack(path, outdir):
    import os
    h, segs, digest, trailing, raw, trunc = parse(path, allow_partial=True)
    os.makedirs(outdir, exist_ok=True)
    meta = {
        "entry": h.entry, "chip_id": h.chip_id, "spi_mode": h.spi_mode,
        "spi_size_freq": h.spi_size_freq, "wp_pin": h.wp_pin,
        "spi_pin_drv": list(h.spi_pin_drv), "min_rev": h.min_rev,
        "min_rev_full": h.min_rev_full, "max_rev_full": h.max_rev_full,
        "reserved": h.reserved.hex(),
    }
    with open(os.path.join(outdir, "meta.txt"), "w") as f:
        for k, v in meta.items():
            f.write(f"{k} = {v}\n")
    for i, (load, data, dlen) in enumerate(segs):
        cut = "_PARTIAL" if len(data) != dlen else ""
        with open(os.path.join(outdir, f"seg{i:02d}_{classify(load)}"
                                       f"_{load:08X}{cut}.bin"), "wb") as f:
            f.write(data)
    if digest:
        with open(os.path.join(outdir, "image.sha256"), "wb") as f:
            f.write(digest)
    print(f"unpacked {len(segs)} segments -> {outdir}/"
          + (f"  (segment {trunc} is PARTIAL)" if trunc is not None else ""))
    return 0


def cmd_repack(outdir, path):
    import os
    meta = {}
    with open(os.path.join(outdir, "meta.txt")) as f:
        for line in f:
            if "=" in line:
                k, v = line.split("=", 1)
                meta[k.strip()] = v.strip()

    h = Header(b"\x00" * HEADER_LEN)
    h.magic = ESP_MAGIC
    h.entry = int(meta["entry"])
    h.chip_id = int(meta["chip_id"])
    h.spi_mode = int(meta["spi_mode"])
    h.spi_size_freq = int(meta["spi_size_freq"])
    h.wp_pin = int(meta["wp_pin"])
    h.spi_pin_drv = bytes(int(x) for x in
                          meta["spi_pin_drv"].strip("[]").split(","))
    h.min_rev = int(meta["min_rev"])
    h.min_rev_full = int(meta["min_rev_full"])
    h.max_rev_full = int(meta["max_rev_full"])
    h.reserved = bytes.fromhex(meta["reserved"])

    segs = []
    for name in sorted(os.listdir(outdir)):
        if not name.startswith("seg") or not name.endswith(".bin"):
            continue
        stem = name[:-len(".bin")]
        if stem.endswith("_PARTIAL"):
            stem = stem[:-len("_PARTIAL")]
        load = int(stem.split("_")[-1], 16)
        with open(os.path.join(outdir, name), "rb") as f:
            segs.append((load, f.read()))

    spath = os.path.join(outdir, "image.sha256")
    digest = b""
    if os.path.exists(spath):
        with open(spath, "rb") as f:
            digest = f.read()[:32]

    blob = build(h, segs, digest)
    with open(path, "wb") as f:
        f.write(blob)
    print(f"repacked {len(segs)} segments -> {path} ({len(blob)} bytes)")
    return 0


def cmd_pack_multi(elf_paths, bin_path, radio=False):
    """Pack one or more ELF32 Xtensa executables into a single ESP32 image.

    The primary ELF supplies the entry point. Additional ELFs (for example a
    Xu-generated IRAM callback module) contribute their PT_LOAD segments as extra
    image segments.

    Flash-mapped segments (DROM/IROM) obey the ESP32 flash cache rule: the
    data of a segment must sit at a flash offset congruent to the load address
    modulo 64 KB, and no two flash-mapped segments may share a 64 KB flash
    page. Gaps are filled with PADDING segments (load address 0), exactly like
    the single-ELF path does.
    """
    flash_segs = []   # (vaddr, data) for DROM/IROM
    ram_segs = []     # (vaddr, data) for DRAM/IRAM
    entry = None
    first = True

    for path in elf_paths:
        with open(path, "rb") as source:
            raw = source.read()
        if len(raw) < 52 or raw[0:4] != b"\x7fELF":
            sys.exit(f"error: {path} is not a valid ELF file")
        if raw[4:6] != b"\x01\x01" or struct.unpack_from("<H", raw, 18)[0] != 94:
            sys.exit(f"error: {path}: expected a little-endian ELF32 Xtensa file")
        e_entry, phoff, phnum = struct.unpack("<IIH", raw[24:28] + raw[28:32] + raw[44:46])
        if struct.unpack_from("<H", raw, 42)[0] != 32 or phoff + phnum * 32 > len(raw):
            sys.exit(f"error: {path}: truncated or unsupported ELF program headers")
        if first:
            entry = e_entry
            first = False
        for i in range(phnum):
            poff = phoff + i * 32
            ptype, offset, vaddr, paddr, filesz, memsz = struct.unpack("<IIIIII", raw[poff:poff + 24])
            if ptype != 1:
                continue
            if filesz == 0 and memsz == 0:
                continue
            if offset + filesz > len(raw) or filesz > memsz:
                sys.exit(f"error: {path}: truncated or malformed ELF load segment")
            checked_load_size(vaddr, memsz, radio)
            data = raw[offset:offset + filesz] + bytes(memsz - filesz)
            if 0x3F400000 <= vaddr < 0x3F800000:
                flash_segs.append((vaddr, data))
            elif 0x400D0000 <= vaddr < 0x40400000:
                flash_segs.append((vaddr, data))
            elif 0x3FFAE000 <= vaddr < 0x40000000:
                if radio and (vaddr != 0x3FFC0000 or vaddr + memsz > 0x3FFD2000):
                    sys.exit("error: radio profile requires Xu data/heap within 0x3FFC0000..0x3FFD2000")
                ram_segs.append((vaddr, data))
            elif 0x40080000 <= vaddr < 0x400AA000:
                if radio and vaddr + memsz > 0x400A0000:
                    sys.exit("error: radio profile requires IRAM code below the ROM DRAM alias at 0x400A0000")
                ram_segs.append((vaddr, data))
            else:
                sys.exit(f"error: {path}: unsupported ELF load address 0x{vaddr:08X}")

    if entry is None:
        sys.exit("error: no ELF given")

    def pad4(b):
        r = len(b) % 4
        return b + (b"\x00" * (4 - r) if r != 0 else b"")

    # 1. DROM: esp_app_desc at 0x3F400020 (required by the ESP-IDF bootloader).
    drom = (0x3F400020, pad4(app_descriptor()))
    check_load_layout([drom, *ram_segs, *flash_segs], entry)

    # The synthetic DROM descriptor occupies flash page 0; every later
    # flash-mapped segment must land in a page of its own.
    flash_segs.sort(key=lambda s: s[0])
    ram_segs.sort(key=lambda s: s[0])

    segs = []
    body = bytearray()
    pos = HEADER_LEN
    segcount = 0

    def emit(vaddr, data):
        nonlocal pos, segcount
        segs.append((vaddr, data))
        body.extend(struct.pack("<II", vaddr, len(data)))
        body.extend(data)
        pos += SEG_HDR_LEN + len(data)
        segcount += 1

    def emit_padding(length):
        emit(0, bytes(length))

    emit(drom[0], drom[1])
    last_page = (pos - 1) // 0x10000

    for vaddr, data in ram_segs:
        emit(vaddr, pad4(data))

    for vaddr, data in flash_segs:
        # The ESP32 bootloader maps the 64 KB flash page that holds a
        # segment's data onto the 64 KB page that holds its load address,
        # so the data must sit at the same offset inside the page as the
        # load address. The segment header sits SEG_HDR_LEN bytes earlier.
        data_off = vaddr & 0xFFFF
        page = last_page + 1
        data_pos = page * 0x10000 + data_off
        while data_pos < pos + 2 * SEG_HDR_LEN:
            page += 1
            data_pos = page * 0x10000 + data_off
        head_pos = data_pos - SEG_HDR_LEN
        gap = head_pos - SEG_HDR_LEN - pos
        if gap > 0:
            emit_padding(gap)
        emit(vaddr, pad4(data))
        last_page = (pos - 1) // 0x10000

    if segcount > 16:
        sys.exit(f"error: {segcount} image segments exceeds ESP_IMAGE_MAX_SEGMENTS = 16")

    h = Header(b"\x00" * HEADER_LEN)
    h.magic = ESP_MAGIC
    h.entry = entry
    h.chip_id = 0
    h.spi_mode = 0x02
    h.spi_size_freq = 0x20
    h.wp_pin = 0xEE
    h.spi_pin_drv = b"\x00\x00\x00"
    h.min_rev = 0
    h.min_rev_full = 0
    h.max_rev_full = 0
    h.reserved = b"\x00" * 7
    h.hash_appended = 1

    h.segcount = segcount
    out = bytearray(h.pack())
    out += body
    r = len(out) % 16
    out += b"\x00" * (15 - r)
    chk = 0xEF
    for _, data in segs:
        for b in data:
            chk ^= b
    out += bytes([chk])
    digest = hashlib.sha256(out).digest()
    image = bytes(out) + digest
    if radio and len(image) > 0x300000:
        sys.exit("error: radio image exceeds the 3MiB application partition")

    with open(bin_path, "wb") as f:
        f.write(image)
    print(f"packed {h.segcount} segments from {len(elf_paths)} ELF(s) -> {bin_path} "
          f"({len(image)} bytes, entry=0x{entry:08X})")
    return 0


def cmd_pack(elf_path, bin_path, radio=False):
    """Convert an ELF32 executable for ESP32 into an esp_image binary."""
    with open(elf_path, "rb") as source:
        raw = source.read()
    if len(raw) < 52 or raw[0:4] != b"\x7fELF":
        sys.exit(f"error: {elf_path} is not a valid ELF file")
    if raw[4:6] != b"\x01\x01" or struct.unpack_from("<H", raw, 18)[0] != 94:
        sys.exit("error: expected a little-endian ELF32 Xtensa executable")

    entry, phoff, phnum = struct.unpack("<IIH", raw[24:28] + raw[28:32] + raw[44:46])
    if struct.unpack_from("<H", raw, 42)[0] != 32 or phoff + phnum * 32 > len(raw):
        sys.exit("error: truncated or unsupported ELF program headers")

    dram_data = b""
    dram_addr = None
    iram_data = b""
    irom_data = b""

    for i in range(phnum):
        poff = phoff + i * 32
        ptype, offset, vaddr, paddr, filesz, memsz = struct.unpack("<IIIIII", raw[poff:poff+24])
        if ptype == 1:  # PT_LOAD
            if filesz > memsz or offset + filesz > len(raw):
                sys.exit("error: truncated or malformed ELF load segment")
            if filesz == 0 and memsz == 0:
                continue
            checked_load_size(vaddr, memsz, radio)
            seg_data = raw[offset:offset+filesz]
            if 0x3FFAE000 <= vaddr < 0x40000000:
                if dram_addr is not None or vaddr + memsz > 0x40000000:
                    sys.exit("error: unsupported or overflowing DRAM load segments")
                dram_addr = vaddr
                dram_data = seg_data + bytes(memsz - filesz)
            elif vaddr == 0x400D0020:
                # IROM: flash-mapped code, executed in place by the bootloader.
                irom_data = seg_data + bytes(memsz - filesz)
            elif vaddr == 0x40084000:
                # Legacy layout: code copied into the 128 KB IRAM window.
                iram_data = seg_data + bytes(memsz - filesz)
            else:
                sys.exit(f"error: unsupported ELF load address 0x{vaddr:08X}")

    if dram_addr is None or not dram_data or not (irom_data or iram_data):
        sys.exit("error: ELF must contain populated DRAM and executable segments")
    if radio and (dram_addr != 0x3FFC0000 or dram_addr + len(dram_data) > 0x3FFD2000):
        sys.exit("error: radio profile requires Xu data/heap within 0x3FFC0000..0x3FFD2000")

    def pad4(b):
        r = len(b) % 4
        return b + (b"\x00" * (4 - r) if r != 0 else b"")

    dram_data = pad4(dram_data)
    iram_data = pad4(iram_data)
    irom_data = pad4(irom_data)

    # 1. DROM: esp_app_desc at 0x3F400020 (required by ESP-IDF 2nd-stage bootloader)
    drom_data = pad4(app_descriptor())

    # 2. IROM: flash-mapped code at 0x400D0020, executed in place.
    if not irom_data:
        # No IROM segment in the ELF: fall back to a dummy return stub so the
        # image still has the segment the ESP32 bootloader expects.
        irom_data = b"\x00\x00\xf0\x0d"

    # Header: 24 bytes
    h = Header(b"\x00" * HEADER_LEN)
    h.magic = ESP_MAGIC
    h.entry = entry
    h.chip_id = 0  # ESP32
    h.spi_mode = 0x02  # DIO
    h.spi_size_freq = 0x20  # 40MHz, 4MB
    h.wp_pin = 0xEE
    h.spi_pin_drv = b"\x00\x00\x00"
    h.min_rev = 0
    h.min_rev_full = 0
    h.max_rev_full = 0
    h.reserved = b"\x00" * 7
    h.hash_appended = 1

    # Flash cache MMU requires: (file_offset + flash_addr) % 64KB == vaddr % 64KB
    # For partition offset 0x10000 and target vaddr 0x400D0020:
    # (0x10000 + target_pos + 8) % 64KB == 0x20 -> target_pos % 64KB == 0x18
    cur_pos = HEADER_LEN + (SEG_HDR_LEN + len(drom_data)) + (SEG_HDR_LEN + len(dram_data))
    if iram_data:
        cur_pos += SEG_HDR_LEN + len(iram_data)
    target_pos = 0x10018
    while target_pos <= cur_pos + SEG_HDR_LEN:
        target_pos += 0x10000

    pad_len = target_pos - (cur_pos + SEG_HDR_LEN)
    pad_data = b"\x00" * pad_len

    segs = [
        (0x3F400020, drom_data),
        (dram_addr, dram_data),
    ]
    if iram_data:
        segs.append((0x40084000, iram_data))
    segs.append((0x00000000, pad_data))
    segs.append((0x400D0020, irom_data))
    check_load_layout(segs, entry)

    h.segcount = len(segs)
    body = bytearray(h.pack())
    chk = 0xEF
    for load, data in segs:
        body += struct.pack("<II", load, len(data))
        body += data
        for b in data:
            chk ^= b

    r = len(body) % 16
    pad_to_16 = 15 - r
    body += b"\x00" * pad_to_16
    body += bytes([chk])

    digest = hashlib.sha256(body).digest()
    image = bytes(body) + digest
    if radio and len(image) > 0x300000:
        sys.exit("error: radio image exceeds the 3MiB application partition")

    with open(bin_path, "wb") as f:
        f.write(image)
    print(f"packed {len(segs)} segments from {elf_path} -> {bin_path} ({len(image)} bytes, entry=0x{entry:08X})")
    return 0


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    if cmd == "info":
        cmd_info(sys.argv[2])
    elif cmd == "verify":
        return cmd_verify(sys.argv[2])
    elif cmd == "unpack":
        return cmd_unpack(sys.argv[2], sys.argv[3])
    elif cmd == "repack":
        return cmd_repack(sys.argv[2], sys.argv[3])
    elif cmd == "pack":
        return cmd_pack(sys.argv[2], sys.argv[3], radio="--radio" in sys.argv[4:])
    elif cmd == "pack-multi":
        # usage: pack-multi <out.bin> <elf> [<elf>...]
        args = sys.argv[3:]
        radio = "--radio" in args
        args = [a for a in args if not a.startswith("--")]
        return cmd_pack_multi(args, sys.argv[2], radio=radio)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
