"""Embed the current-user execution policy in directly emitted SDK installers.

The resource is added before offline payload injection. Existing GUI resources
and manifests are preserved; this is not a general PE resource editor.
"""
from pathlib import Path
import struct
import xml.etree.ElementTree as ET

MANIFEST = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges>
    <requestedExecutionLevel level="asInvoker" uiAccess="false"/>
  </requestedPrivileges></security></trustInfo>
</assembly>
'''


def embed_invoker_manifest(path: Path) -> None:
    raw = bytearray(path.read_bytes())

    def u16(at):
        if at < 0 or at + 2 > len(raw):
            raise ValueError("truncated PE header")
        return struct.unpack_from("<H", raw, at)[0]

    def u32(at):
        if at < 0 or at + 4 > len(raw):
            raise ValueError("truncated PE header or resource")
        return struct.unpack_from("<I", raw, at)[0]

    def align(value, boundary):
        return (value + boundary - 1) & -boundary

    pe = u32(60)
    if raw[:2] != b"MZ" or raw[pe:pe+4] != b"PE\0\0" or u16(pe+4) not in (0x8664, 0xAA64):
        raise ValueError("expected a Windows x64 or ARM64 PE executable")
    optional = pe + 24
    optional_size, count = u16(pe+20), u16(pe+6)
    if u16(optional) != 0x20B or optional_size < 240 or not 1 <= count < 96 or u32(optional+108) < 16:
        raise ValueError("unsupported PE optional header or section table")
    section_alignment, file_alignment = u32(optional+32), u32(optional+36)
    if not (512 <= file_alignment <= 65536 and section_alignment >= file_alignment
            and file_alignment & (file_alignment-1) == 0 and section_alignment & (section_alignment-1) == 0):
        raise ValueError("unsupported PE alignment")
    table = optional + optional_size
    if table + count*40 > min(len(raw), u32(optional+60)):
        raise ValueError("truncated PE section table")
    sections = []
    for i in range(count):
        at = table + i * 40
        size, rva, disk_size, disk = (u32(at+n) for n in (8, 12, 16, 20))
        if disk_size and (disk < u32(optional+60) or disk + disk_size > len(raw)):
            raise ValueError("invalid PE section range")
        sections.append((size, rva, disk_size, disk))

    resource_rva, resource_size = u32(optional+128), u32(optional+132)
    if resource_rva:
        # The GUI toolchain already supplies a manifest alongside its icons.
        # Follow only the numeric RT_MANIFEST / application-id-1 resource.
        def offset(rva, length):
            for _, address, size, disk in sections:
                if address <= rva and rva + length <= address + size:
                    return disk + rva - address
            raise ValueError("PE resource points outside section data")

        base = offset(resource_rva, resource_size)

        def entry(directory, wanted):
            at = base + directory
            named, ids = u16(at+12), u16(at+14)
            if directory + 16 + (named+ids)*8 > resource_size:
                raise ValueError("invalid PE resource directory")
            for i in range(named, named+ids):
                item = at + 16 + i*8
                if wanted is None or u32(item) == wanted:
                    return u32(item+4)
            raise ValueError("existing PE resources lack an application manifest")

        node = 0
        for wanted in (24, 1):
            child = entry(node, wanted)
            if not child & 0x80000000:
                raise ValueError("invalid PE manifest resource tree")
            node = child & 0x7fffffff
        leaf = entry(node, None)
        if leaf & 0x80000000 or leaf + 16 > resource_size:
            raise ValueError("invalid PE manifest data entry")
        address, size = u32(base+leaf), u32(base+leaf+4)
        at = offset(address, size)
        root = ET.fromstring(raw[at:at+size])
        level = root.find('.//{urn:schemas-microsoft-com:asm.v3}requestedExecutionLevel')
        if level is None or level.get("level") != "asInvoker" or level.get("uiAccess") != "false":
            raise ValueError("SDK installer must declare asInvoker without UI access")
        return
    if resource_size or u32(optional+144) or u32(optional+148):
        raise ValueError("refusing to modify an inconsistent resource table or signed executable")
    header = table + count*40
    first_disk = min(disk for _, _, size, disk in sections if size)
    if header + 40 > min(first_disk, u32(optional+60)) or any(raw[header:header+40]):
        raise ValueError("PE has no spare section header for the installer manifest")
    disk_end = max(disk+size for _, _, size, disk in sections)
    if any(raw[disk_end:]):
        raise ValueError("embed the manifest before adding an offline payload")

    rva = align(max(address+max(size, disk_size) for size, address, disk_size, _ in sections), section_alignment)
    disk = align(len(raw), file_alignment)
    resource = bytearray(88)
    for directory, identifier, target in ((0, 24, 24), (24, 1, 48), (48, 0, 72)):
        struct.pack_into("<HH", resource, directory+12, 0, 1)
        struct.pack_into("<II", resource, directory+16, identifier,
                         target | (0x80000000 if directory != 48 else 0))
    struct.pack_into("<IIII", resource, 72, rva+88, len(MANIFEST), 65001, 0)
    resource += MANIFEST
    disk_size = align(len(resource), file_alignment)
    image_size = align(rva+len(resource), section_alignment)
    if max(image_size, disk+disk_size, u32(optional+8)+disk_size) > 0xffffffff:
        raise ValueError("PE installer manifest exceeds 32-bit image limits")
    raw.extend(bytes(disk+disk_size-len(raw)))
    raw[disk:disk+len(resource)] = resource
    struct.pack_into("<8sIIIIIIHHI", raw, header, b".rsrc\0\0\0", len(resource), rva,
                     disk_size, disk, 0, 0, 0, 0, 0x40000040)
    struct.pack_into("<H", raw, pe+6, count+1)
    for at, value in ((optional+8, u32(optional+8)+disk_size), (optional+56, image_size),
                      (optional+64, 0), (optional+128, rva), (optional+132, len(resource))):
        struct.pack_into("<I", raw, at, value)
    path.write_bytes(raw)
