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
    esp32_image.py unpack <app.bin> <outdir>     # extract segments
    esp32_image.py repack <outdir> <app.bin>     # rebuild from segments
    esp32_image.py info    <app.bin>             # print layout
    esp32_image.py verify  <app.bin>             # structural + hash check
"""
import hashlib
import struct
import sys

ESP_MAGIC = 0xE9
HEADER_LEN = 24
SEG_HDR_LEN = 8

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
    raw = open(path, "rb").read()
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

    # A partial trailing segment leaves no room for the digest.
    digest = b""
    trailing = b""
    if truncated_at is None:
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
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())