"""linux-arm32: hosted Thumb-2 ELF32 (ARM EABI), not Cortex-M."""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XU = ROOT / "bin" / "xu"
HELLO = ROOT / "tests" / "embedded" / "hello.xu"


def _build(target: str, dest: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(XU), "build", str(HELLO), "--target", target, "-o", str(dest)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_linux_arm32_aliases_parse_and_emit_elf32() -> None:
    if not XU.is_file():
        raise AssertionError("missing product bin/xu")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "hello.xin"
        r = _build("linux-arm32", out)
        if r.returncode != 0 and "unknown --target" in (r.stderr + r.stdout):
            import pytest
            pytest.skip("product bin/xu predates linux-arm32; run make xu")
        assert r.returncode == 0, r.stdout + r.stderr
        data = out.read_bytes()
        assert data[:4] == b"\x7fELF"
        assert data[4] == 1  # ELFCLASS32
        e_type, e_machine = struct.unpack_from("<HH", data, 16)
        e_entry = struct.unpack_from("<I", data, 24)[0]
        e_flags = struct.unpack_from("<I", data, 36)[0]
        assert e_type == 2
        assert e_machine == 40
        assert e_entry & 1 == 1
        assert e_flags & 0xFF000000 == 0x05000000
        alt = Path(td) / "hello_arm.xin"
        r2 = _build("linux-arm", alt)
        assert r2.returncode == 0, r2.stdout + r2.stderr
        qemu = shutil.which("qemu-arm") or shutil.which("qemu-arm-static")
        if qemu:
            env = os.environ.copy()
            env.pop("QEMU_LD_PREFIX", None)
            run = subprocess.run(
                [qemu, str(out)],
                capture_output=True,
                text=True,
                timeout=5,
                env=env,
                check=False,
            )
            assert "hello" in (run.stdout + run.stderr), run.stdout + run.stderr


def test_linux_arm32_array_index_rw() -> None:
    compiler = Path("/tmp/xu_g1.xin") if Path("/tmp/xu_g1.xin").is_file() else XU
    fixture = ROOT / "tests" / "fixtures" / "array_index_rw" / "main.xu"
    if not fixture.is_file():
        return
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "array_rw.xin"
        r = subprocess.run(
            [str(compiler), "build", str(fixture), "--target", "linux-arm32", "-o", str(out)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        data = out.read_bytes()
        assert data[:4] == b"\x7fELF"
        assert data[4] == 1  # ELFCLASS32
