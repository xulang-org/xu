#!/usr/bin/env python3
"""Build and inspect Xu native-module artifacts.

``xunative compile`` compiles C sources for one target, wraps the XU export
metadata in a valid target object section, and creates a hybrid Unix archive;
``xunative archive`` does the same packaging step for precompiled native
objects. ``xunative pack`` bundles one archive per target into a portable
``.xulib`` file. The Xu compiler reads the metadata while the platform linker
sees only valid native objects.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

MAGIC = b"XULIB\x01\x00"
XUOBJ_MAGIC = b"XUOBJ\x01\x00\x00"
FORMAT_VERSION = 1
TARGETS = {
    "macos-arm64": (1, 1),
    "macos-x64": (1, 2),
    "linux-arm64": (2, 1),
    "linux-x64": (2, 2),
    "linux-loongarch64": (2, 5),
    "linux-riscv64": (2, 6),
    "windows-arm64": (3, 1),
    "windows-x64": (3, 2),
}
CLANG_TARGETS = {
    "macos-arm64": "arm64-apple-macos11",
    "macos-x64": "x86_64-apple-macos11",
    "linux-arm64": "aarch64-linux-gnu",
    "linux-x64": "x86_64-linux-gnu",
    "linux-loongarch64": "loongarch64-linux-gnu",
    "linux-riscv64": "riscv64-linux-gnu",
    "windows-arm64": "aarch64-pc-windows-msvc",
    "windows-x64": "x86_64-pc-windows-msvc",
}
TYPE_CODES = {
    "void": 0,
    "int": 1,
    "bool": 2,
    "f64": 4,
    "i32": 8,
    "u32": 9,
    "u8": 10,
}


def xu_string(value: str) -> bytes:
    raw = value.encode("utf-8")
    if len(raw) > 0xFFFF:
        raise SystemExit(f"string is too long for XUOBJ: {value[:40]!r}")
    return struct.pack("<H", len(raw)) + raw


def target_code(target: str) -> tuple[int, int]:
    try:
        return TARGETS[target]
    except KeyError:
        names = ", ".join(sorted(TARGETS))
        raise SystemExit(f"unsupported target {target!r}; choose one of: {names}")


def type_code(name: str) -> int:
    try:
        return TYPE_CODES[name.lower()]
    except KeyError:
        names = ", ".join(sorted(TYPE_CODES))
        raise SystemExit(f"unsupported XU ABI type {name!r}; choose one of: {names}")


def is_xu_ident(value: str) -> bool:
    if not value or not (value[0].isascii() and (value[0].isalpha() or value[0] == "_")):
        return False
    return all(char.isascii() and (char.isalnum() or char == "_") for char in value[1:])


def valid_module_path(value: str) -> bool:
    # Same portable lexical contract as internal/modulepath. Domain dots are
    # data; slash is the only separator. Native metadata names packages, so
    # a subpackage need not end in its enclosing module's major suffix.
    elements = value.split("/")
    for element in elements:
        if not element or element.startswith(".") or element.endswith("."):
            return False
        if not all(c.isascii() and (c.isalnum() or c in "-._~") for c in element):
            return False
        base = element.split(".", 1)[0].lower()
        if base in {"con", "prn", "aux", "nul"} or base in {f"{p}{n}" for p in ("com", "lpt") for n in range(1, 10)}:
            return False
        if "~" in base and base.rsplit("~", 1)[1].isdigit():
            return False
    authority = elements[0]
    if "." in authority:
        if any(not label or label.startswith("-") or label.endswith("-") for label in authority.split(".")):
            return False
        if any(not ("a" <= c <= "z" or "0" <= c <= "9" or c in ".-") for c in authority):
            return False
    return True


def export_label(module: str, name: str) -> str:
    def symbol_part(value: str) -> str:
        return "".join(
            char if char.isascii() and (char.isalnum() or char == "_") else "_"
            for char in value
        )

    if "." in module.split("/", 1)[0]:
        return "_xu_path." + module.encode("ascii").hex() + "_" + symbol_part(name)
    return "_xu_" + symbol_part(module) + "_" + symbol_part(name)


def encode_xuobj(manifest: dict, target: str) -> bytes:
    os_code, arch_code = target_code(target)
    if manifest.get("abi") != "xu-c-1":
        raise SystemExit("manifest requires 'abi': 'xu-c-1'")
    module = manifest.get("module")
    if not isinstance(module, str) or not module:
        raise SystemExit("manifest requires a non-empty string 'module'")
    if not valid_module_path(module):
        raise SystemExit(f"manifest has invalid Xu module id: {module!r}")
    exports = manifest.get("exports", [])
    if not isinstance(exports, list):
        raise SystemExit("manifest 'exports' must be a list")

    out = bytearray(b"XUOBJ\x01\x00\x00")
    out += bytes((os_code, arch_code)) + struct.pack("<H", 0)
    out += xu_string(module)
    out += struct.pack("<I", len(exports))
    for item in exports:
        if not isinstance(item, dict):
            raise SystemExit("each manifest export must be an object")
        name = item.get("name")
        if not isinstance(name, str) or not is_xu_ident(name):
            raise SystemExit("each manifest export needs a valid Xu identifier 'name'")
        params = item.get("params", [])
        if not isinstance(params, list) or len(params) > 255:
            raise SystemExit(f"export {name!r} has invalid params")
        if any(not isinstance(param, str) or param.lower() == "void" for param in params):
            raise SystemExit(f"export {name!r} has an invalid parameter type")
        ret = item.get("ret", item.get("returns", "void"))
        if not isinstance(ret, str):
            raise SystemExit(f"export {name!r} has invalid return type")
        label = item.get("label", export_label(module, name))
        if not isinstance(label, str) or not label:
            raise SystemExit(f"export {name!r} has invalid label")
        out += xu_string(name)
        out += xu_string(label)
        out += bytes((type_code(ret), len(params)))
        out += bytes(type_code(p) for p in params)

    # Metadata payload. It is wrapped in a valid native object below so the
    # platform linker can validate the archive without understanding XUOBJ.
    out += struct.pack("<I", 0)  # labels
    out += struct.pack("<I", 0)  # relocations
    out += struct.pack("<I", 0)  # code
    out += struct.pack("<I", 0)  # data
    return bytes(out)


def metadata_c_source(metadata: bytes, target: str) -> str:
    section = "__DATA,__xumeta" if target.startswith("macos-") else ".xumeta"
    rows = []
    for offset in range(0, len(metadata), 12):
        rows.append("    " + ", ".join(f"0x{byte:02x}" for byte in metadata[offset : offset + 12]))
    encoded = ",\n".join(rows)
    return (
        "/* Generated XUNATIVE metadata wrapper. */\n"
        f'__attribute__((used, aligned(1), section("{section}")))\n'
        "static const unsigned char xu_native_metadata_v1[] = {\n"
        f"{encoded}\n"
        "};\n"
    )


def compile_metadata_object(metadata: bytes, target: str, output: Path, cc: str) -> None:
    source = output.with_suffix(".c")
    source.write_text(metadata_c_source(metadata, target), encoding="utf-8")
    triple = CLANG_TARGETS[target]
    cmd = [cc, f"--target={triple}", "-c", "-x", "c", str(source), "-o", str(output)]
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        raise SystemExit(f"C compiler not found: {cc}")
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"metadata object compilation failed with exit status {exc.returncode}")


def compile_c_sources(
    sources: list[Path], target: str, root: Path, cc: str, cflags: list[str]
) -> list[Path]:
    if not sources:
        raise SystemExit("compile requires at least one C source")
    triple = CLANG_TARGETS[target]
    include_dir = Path(__file__).resolve().parent.parent / "include"
    outputs: list[Path] = []
    for index, source in enumerate(sources):
        if not source.is_file():
            raise SystemExit(f"C source does not exist: {source}")
        output = root / f"native_{index}.o"
        cmd = [
            cc,
            f"--target={triple}",
            "-I",
            str(include_dir),
            *cflags,
            "-c",
            str(source.resolve()),
            "-o",
            str(output),
        ]
        try:
            subprocess.run(cmd, check=True)
        except FileNotFoundError:
            raise SystemExit(f"C compiler not found: {cc}")
        except subprocess.CalledProcessError as exc:
            raise SystemExit(
                f"C source compilation failed for {source} with exit status {exc.returncode}"
            )
        outputs.append(output)
    return outputs


def resolve_c_compiler(requested: str, target: str) -> str:
    if requested != "auto":
        return requested
    llvm_clang = [
        "/opt/homebrew/opt/llvm/bin/clang",
        "/usr/local/opt/llvm/bin/clang",
    ]
    candidates = (
        [*llvm_clang, "clang"]
        if target in ("linux-loongarch64", "linux-riscv64")
        else ["clang", *llvm_clang]
    )
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found
    raise SystemExit("C compiler not found: install clang or pass --cc PATH")


def resolve_archive_tool(requested: str, _target: str) -> str:
    if requested != "auto":
        return requested
    candidates = [
        "llvm-ar",
        "/opt/homebrew/opt/llvm/bin/llvm-ar",
        "/usr/local/opt/llvm/bin/llvm-ar",
        "ar",
    ]
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found
    raise SystemExit("archive tool not found: install llvm-ar or pass --ar PATH")


def ar_archive(output: Path, metadata: Path, native: list[Path], ar: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    cmd = [ar, "rcs", str(output), str(metadata), *(str(p) for p in native)]
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        raise SystemExit(f"archive tool not found: {ar}")
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"archive failed with exit status {exc.returncode}")


def native_members(paths: list[Path], ar: str, root: Path) -> list[Path]:
    members: list[Path] = []
    for index, path in enumerate(paths):
        if not path.is_file():
            raise SystemExit(f"native input does not exist: {path}")
        if path.suffix != ".a":
            members.append(path.resolve())
            continue
        dest = root / f"archive_{index}"
        dest.mkdir()
        try:
            subprocess.run([ar, "-x", str(path.resolve())], cwd=dest, check=True)
        except FileNotFoundError:
            raise SystemExit(f"archive tool not found: {ar}")
        except subprocess.CalledProcessError as exc:
            raise SystemExit(f"cannot extract {path}: ar exited {exc.returncode}")
        members.extend(
            sorted(
                p
                for p in dest.iterdir()
                if p.is_file() and p.name not in ("__.SYMDEF", "__.SYMDEF SORTED", "/", "//")
            )
        )
    return members


def read_manifest(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"cannot read manifest {path}: {exc}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON manifest {path}: {exc}")
    if not isinstance(value, dict):
        raise SystemExit("native manifest root must be a JSON object")
    return value


def archive_member_payloads(raw: bytes) -> list[tuple[str, bytes]]:
    if not raw.startswith(b"!<arch>\n"):
        return []
    members: list[tuple[str, bytes]] = []
    pos = 8
    while pos + 60 <= len(raw):
        header = raw[pos : pos + 60]
        try:
            size = int(header[48:58].decode("ascii").strip())
        except (UnicodeDecodeError, ValueError):
            raise SystemExit("slice has an invalid ar member size")
        pos += 60
        if size > len(raw) - pos:
            raise SystemExit("slice has a truncated ar member")
        body = raw[pos : pos + size]
        raw_name = header[:16].decode("ascii", errors="ignore").strip()
        if raw_name.startswith("#1/"):
            try:
                name_len = int(raw_name[3:].strip())
            except ValueError:
                raise SystemExit("slice has an invalid BSD ar member name")
            if name_len > len(body):
                raise SystemExit("slice has a truncated BSD ar member name")
            name = body[:name_len].rstrip(b"\x00/").decode("utf-8", errors="ignore")
            payload = body[name_len:]
        else:
            name = raw_name.rstrip("/")
            payload = body
        members.append((name, payload))
        pos += size + (size & 1)
    return members


def slice_target_codes(raw: bytes) -> tuple[int, int]:
    payloads = [payload for name, payload in archive_member_payloads(raw) if name == "xu.o"]
    if not payloads:
        payloads = [raw]
    for payload in payloads:
        pos = payload.rfind(XUOBJ_MAGIC)
        if pos >= 0 and pos + 10 <= len(payload):
            return payload[pos + 8], payload[pos + 9]
    raise SystemExit("slice has no embedded XUOBJ target metadata")


def cmd_archive(args: argparse.Namespace) -> None:
    manifest = read_manifest(args.manifest)
    target_code(args.target)
    cc = resolve_c_compiler(args.cc, args.target)
    ar = resolve_archive_tool(args.ar, args.target)
    with tempfile.TemporaryDirectory(prefix="xunative-") as temp:
        root = Path(temp)
        encoded = encode_xuobj(manifest, args.target)
        metadata = root / "xu.o"
        compile_metadata_object(encoded, args.target, metadata, cc)
        members = native_members(args.native, ar, root)
        ar_archive(args.output, metadata, members, ar)
    print(f"archive: {args.output} target={args.target}")


def cmd_compile(args: argparse.Namespace) -> None:
    manifest = read_manifest(args.manifest)
    target_code(args.target)
    cc = resolve_c_compiler(args.cc, args.target)
    ar = resolve_archive_tool(args.ar, args.target)
    with tempfile.TemporaryDirectory(prefix="xunative-") as temp:
        root = Path(temp)
        encoded = encode_xuobj(manifest, args.target)
        metadata = root / "xu.o"
        compile_metadata_object(encoded, args.target, metadata, cc)
        compiled = compile_c_sources(args.source, args.target, root, cc, args.cflag)
        members = [*compiled, *native_members(args.native, ar, root)]
        ar_archive(args.output, metadata, members, ar)
    print(f"compile: {args.output} target={args.target} sources={len(args.source)}")


def parse_slice(value: str) -> tuple[str, Path]:
    target, sep, path = value.partition("=")
    if not sep or not target or not path:
        raise SystemExit(f"slice must be TARGET=PATH, got {value!r}")
    target_code(target)
    return target, Path(path)


def cmd_pack(args: argparse.Namespace) -> None:
    manifest = read_manifest(args.manifest)
    if not isinstance(manifest.get("module"), str) or not manifest["module"]:
        raise SystemExit("manifest requires a non-empty string 'module'")
    if not valid_module_path(manifest["module"]):
        raise SystemExit(f"manifest has invalid Xu module id: {manifest['module']!r}")
    if manifest.get("abi") != "xu-c-1":
        raise SystemExit("manifest requires 'abi': 'xu-c-1'")
    slices: dict[str, Path] = {}
    for raw in args.slice:
        target, path = parse_slice(raw)
        if target in slices:
            raise SystemExit(f"duplicate target slice: {target}")
        if not path.is_file():
            raise SystemExit(f"slice does not exist: {path}")
        slices[target] = path
    if not slices:
        raise SystemExit("pack requires at least one --slice TARGET=PATH")

    entries = []
    payload = bytearray()
    for target in sorted(slices):
        raw = slices[target].read_bytes()
        actual_target = slice_target_codes(raw)
        if actual_target != TARGETS[target]:
            raise SystemExit(
                f"slice {slices[target]} target metadata {actual_target} does not match {target}"
            )
        digest = hashlib.sha256(raw).digest()
        offset = len(payload)
        payload += raw
        entries.append(
            {
                "target": target,
                "kind": "archive" if slices[target].suffix == ".a" else "object",
                "offset": offset,
                "size": len(raw),
                "sha256": digest.hex(),
            }
        )
    stored_manifest = dict(manifest)
    stored_manifest["format"] = "xulib-1"
    stored_manifest["slices"] = [
        {key: value for key, value in item.items() if key not in ("offset",)}
        for item in entries
    ]
    manifest_bytes = json.dumps(
        stored_manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if len(manifest_bytes) > 0xFFFFFFFF:
        raise SystemExit("manifest is too large")

    out = bytearray(MAGIC)
    out += struct.pack("<HHI", FORMAT_VERSION, 0, len(manifest_bytes))
    out += manifest_bytes
    out += struct.pack("<I", len(entries))
    table_size = 0
    for item in entries:
        target_raw = item["target"].encode("utf-8")
        kind_raw = item["kind"].encode("ascii")
        if len(target_raw) > 0xFFFF or len(kind_raw) > 0xFF:
            raise SystemExit("slice metadata is too large")
        table_size += 2 + len(target_raw) + 1 + len(kind_raw) + 8 + 8 + 32
    payload_start = len(out) + table_size
    for item in entries:
        target_raw = item["target"].encode("utf-8")
        kind_raw = item["kind"].encode("ascii")
        out += struct.pack("<H", len(target_raw)) + target_raw
        out += bytes((len(kind_raw),)) + kind_raw
        out += struct.pack("<QQ", payload_start + item["offset"], item["size"])
        out += bytes.fromhex(item["sha256"])
    out += payload
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(out)
    print(f"xulib: {args.output} slices={len(entries)}")


def read_xulib(path: Path) -> tuple[dict, list[dict], bytes]:
    raw = path.read_bytes()
    if len(raw) < len(MAGIC) + 8 or raw[: len(MAGIC)] != MAGIC:
        raise SystemExit(f"not a XULIB v1 file: {path}")
    pos = len(MAGIC)
    version, _flags, manifest_len = struct.unpack_from("<HHI", raw, pos)
    pos += 8
    if version != FORMAT_VERSION:
        raise SystemExit(f"unsupported XULIB version: {version}")
    end = pos + manifest_len
    if end > len(raw):
        raise SystemExit("truncated XULIB manifest")
    try:
        manifest = json.loads(raw[pos:end].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid XULIB manifest: {exc}")
    pos = end
    if pos + 4 > len(raw):
        raise SystemExit("truncated XULIB slice count")
    count = struct.unpack_from("<I", raw, pos)[0]
    pos += 4
    entries = []
    for _ in range(count):
        if pos + 2 > len(raw):
            raise SystemExit("truncated XULIB target name")
        n = struct.unpack_from("<H", raw, pos)[0]
        pos += 2
        if pos + n + 1 > len(raw):
            raise SystemExit("truncated XULIB slice metadata")
        target = raw[pos : pos + n].decode("utf-8")
        pos += n
        kind_len = raw[pos]
        pos += 1
        if pos + kind_len + 48 > len(raw):
            raise SystemExit("truncated XULIB slice metadata")
        kind = raw[pos : pos + kind_len].decode("ascii")
        pos += kind_len
        offset, size = struct.unpack_from("<QQ", raw, pos)
        pos += 16
        digest = raw[pos : pos + 32]
        pos += 32
        if offset + size > len(raw):
            raise SystemExit(f"XULIB slice {target!r} is out of bounds")
        actual = hashlib.sha256(raw[offset : offset + size]).digest()
        if actual != digest:
            raise SystemExit(f"XULIB slice {target!r} failed SHA-256 verification")
        entries.append(
            {"target": target, "kind": kind, "offset": offset, "size": size, "sha256": digest.hex()}
        )
    return manifest, entries, raw


def cmd_inspect(args: argparse.Namespace) -> None:
    manifest, entries, _raw = read_xulib(args.input)
    print(json.dumps({"manifest": manifest, "slices": entries}, ensure_ascii=False, indent=2))


def cmd_extract(args: argparse.Namespace) -> None:
    _manifest, entries, raw = read_xulib(args.input)
    matches = [item for item in entries if item["target"] == args.target]
    if not matches:
        available = ", ".join(item["target"] for item in entries)
        raise SystemExit(f"target {args.target!r} is not packaged; available: {available}")
    item = matches[0]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(raw[item["offset"] : item["offset"] + item["size"]])
    print(f"extract: {args.output} target={args.target}")


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="xunative")
    sub = ap.add_subparsers(dest="command", required=True)

    archive = sub.add_parser("archive", help="make a hybrid XU metadata/native archive")
    archive.add_argument("--manifest", type=Path, required=True)
    archive.add_argument("--target", required=True)
    archive.add_argument("-o", "--output", type=Path, required=True)
    archive.add_argument("--ar", default="auto")
    archive.add_argument("--cc", default="auto")
    archive.add_argument("--native", type=Path, action="append", default=[])
    archive.set_defaults(func=cmd_archive)

    compile_cmd = sub.add_parser("compile", help="compile C sources into a native Xu archive")
    compile_cmd.add_argument("--manifest", type=Path, required=True)
    compile_cmd.add_argument("--target", required=True)
    compile_cmd.add_argument("-o", "--output", type=Path, required=True)
    compile_cmd.add_argument("--cc", default="auto")
    compile_cmd.add_argument("--ar", default="auto")
    compile_cmd.add_argument("--cflag", action="append", default=[])
    compile_cmd.add_argument("--native", type=Path, action="append", default=[])
    compile_cmd.add_argument("source", type=Path, nargs="+")
    compile_cmd.set_defaults(func=cmd_compile)

    pack = sub.add_parser("pack", help="pack target archives into one .xulib")
    pack.add_argument("--manifest", type=Path, required=True)
    pack.add_argument("--slice", action="append", default=[])
    pack.add_argument("-o", "--output", type=Path, required=True)
    pack.set_defaults(func=cmd_pack)

    inspect = sub.add_parser("inspect", help="inspect and verify a .xulib")
    inspect.add_argument("input", type=Path)
    inspect.set_defaults(func=cmd_inspect)

    extract = sub.add_parser("extract", help="extract one target slice")
    extract.add_argument("input", type=Path)
    extract.add_argument("--target", required=True)
    extract.add_argument("-o", "--output", type=Path, required=True)
    extract.set_defaults(func=cmd_extract)
    return ap


def main() -> None:
    args = parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
