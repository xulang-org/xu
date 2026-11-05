#!/usr/bin/env python3
"""Host checks for the IDF CYD control envelope (absolute mouse).

Command parsing and MQTT run in Xu (examples/esp32/idf_cyd/xu/app.xu, using
#embedded/bluetooth/control and #embedded/mqtt). This checks the shared Xu
parser on the host, that app.xu still builds as an Xtensa relocatable object
with its C entry points, and the C HID report map.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CYD = ROOT / "examples/esp32/idf_cyd"
XU = ROOT / "bin/xu"

PROBE = """@main
#embedded/bluetooth/control

fn show(bytes string) {
    command := control.parse(&bytes)
    $line := "0"
    if command.valid { line = "1" }
    line = line + " " + str(command.op) + " " + str(command.report.len)
    for i in 0:command.report.len { line = line + " " + str(command.report[i]) }
    println(line)
}

fn main() {
%s
}
"""

CASES = [
    '{"id":"tap-1","op":"hid.mouse","report":[1,255,63,255,63]}',
    '{"id":"over","op":"hid.mouse","report":[0,0,128,0,0]}',
    '{"id":"status-1","op":"status"}',
    '{"id":"key-1","op":"hid.keyboard","report":[0,0,115,0,0,0,0,0]}',
]


def parse_cases() -> list[list[int]]:
    calls = "\n".join("    show(%s)" % ('"' + c.replace('"', '\\"') + '"') for c in CASES)
    with tempfile.TemporaryDirectory(prefix="xu-idf-cyd-") as tmp:
        src = Path(tmp) / "probe.xu"
        exe = Path(tmp) / "probe"
        src.write_text(PROBE % calls)
        subprocess.check_call([str(XU), "build", str(src), "-o", str(exe)], cwd=ROOT)
        out = subprocess.check_output([str(exe)], text=True)
    return [list(map(int, line.split())) for line in out.splitlines()]


def check_app_object() -> None:
    with tempfile.TemporaryDirectory(prefix="xu-idf-cyd-") as tmp:
        stage = Path(tmp) / "xu_src"
        stage.mkdir()
        for src in [*sorted((CYD / "xu").glob("*.xu")), CYD.parent / "status_demo/ui.xu"]:
            shutil.copy(src, stage / src.name)
        obj = Path(tmp) / "xu_app.o"
        subprocess.check_call(
            [str(XU), "build", "--target", "xtensa-esp32-none", "--emit-obj", "-o", str(obj),
             *map(str, sorted(stage.glob("*.xu")))],
            cwd=ROOT,
        )
        data = obj.read_bytes()
    assert data[:4] == b"\x7fELF" and data[4] == 1, "ELF32 object expected"
    assert int.from_bytes(data[18:20], "little") == 94, "EM_XTENSA expected"
    for sym in (b"xu_rt_init", b"_rom_cb_xu_main_xu_app_main", b"xu_host_hid_mouse", b"xu_host_lcd_span"):
        assert sym in data, f"{sym.decode()} missing from xu_app.o"


def main() -> int:
    tap, over, status, key = parse_cases()
    assert tap[:3] == [1, 7, 5], "absolute mouse must parse"
    x = tap[4] | (tap[5] << 8)
    y = tap[6] | (tap[7] << 8)
    assert x == 16383 and y == 16383
    assert over[0] == 0, "axis above 32767 must be rejected"
    assert status[0] == 1
    assert key[0] == 1

    app = (CYD / "xu/app.xu").read_text()
    assert "command.op == control.MOUSE && command.report.len != 5" in app, \
        "CYD app must reject relative 4-byte mouse reports"
    check_app_object()

    # Report map in hid_abs.c must advertise absolute axes, not relative.
    hid = (CYD / "main/hid_abs.c").read_text()
    assert "0x81, 0x06" not in hid.replace(" ", ""), "hid_abs report map must not use relative Input"
    assert "0x26, 0xFF, 0x7F" in hid.replace("\n", ""), "logical max 32767 required"
    assert "s_last_x" in hid and "s_last_y" in hid

    readme = (CYD / "README.md").read_text()
    assert "2097152" in readme and "partitions.csv" in readme
    assert "IDF_VERSION" in readme

    print("idf_cyd control contract checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
