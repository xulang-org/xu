#!/usr/bin/env python3
"""Host checks for the IDF CYD control envelope (absolute mouse)."""
from __future__ import annotations

import ctypes
import subprocess
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "examples/esp32/idf_cyd/main"


def compile_parser() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="xu-idf-cyd-"))
    obj = tmp / "control_parse.so"
    subprocess.check_call(
        [
            "cc",
            "-shared",
            "-fPIC",
            "-O2",
            "-I",
            str(SRC),
            str(SRC / "control_parse.c"),
            "-o",
            str(obj),
        ]
    )
    return obj


class Command(ctypes.Structure):
    _fields_ = [
        ("valid", ctypes.c_bool),
        ("id", ctypes.c_char * 65),
        ("op", ctypes.c_int),
        ("report", ctypes.c_uint8 * 8),
        ("report_len", ctypes.c_size_t),
    ]


def load(lib_path: Path):
    lib = ctypes.CDLL(str(lib_path))
    lib.xu_control_parse.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
    lib.xu_control_parse.restype = Command
    return lib


def main() -> int:
    lib = load(compile_parser())

    def parse(s: str) -> Command:
        b = s.encode("ascii")
        return lib.xu_control_parse(b, len(b))

    abs_center = parse('{"id":"tap-1","op":"hid.mouse","report":[1,255,63,255,63]}')
    assert abs_center.valid, "absolute mouse must parse"
    assert abs_center.op == 7
    assert abs_center.report_len == 5
    x = abs_center.report[1] | (abs_center.report[2] << 8)
    y = abs_center.report[3] | (abs_center.report[4] << 8)
    assert x == 16383 and y == 16383

    assert not parse('{"id":"old","op":"hid.mouse","report":[0,1,0,0]}').valid
    assert not parse('{"id":"over","op":"hid.mouse","report":[0,0,128,0,0]}').valid
    assert parse('{"id":"status-1","op":"status"}').valid
    assert parse('{"id":"key-1","op":"hid.keyboard","report":[0,0,115,0,0,0,0,0]}').valid

    # Report map in hid_abs.c must advertise absolute axes, not relative.
    hid = (SRC / "hid_abs.c").read_text()
    assert "0x81, 0x06" not in hid.replace(" ", ""), "hid_abs report map must not use relative Input"
    assert "0x26, 0xFF, 0x7F" in hid.replace("\n", ""), "logical max 32767 required"
    assert "s_last_x" in hid and "s_last_y" in hid

    readme = (ROOT / "examples/esp32/idf_cyd/README.md").read_text()
    assert "1.5" in readme or "1572864" in readme or "1.5 MiB" in readme
    assert "IDF_VERSION" in readme

    print("idf_cyd control contract checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
