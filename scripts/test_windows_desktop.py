#!/usr/bin/env python3
"""Exercise native Windows desktop shell, paths, and ARM64 loader discovery.

Run on Windows with Git Bash on PATH:
  python scripts/test_windows_desktop.py --compiler /path/to/xu.exe
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile


HARNESS = r'''
fn main() int {
    argv := args()
    if argv.len != 2 { << 1 }
    root := desktop_native_path(argv[1])
    arm := root + "/dist/windows-x64-ui/_build/WebView2Loader_arm64.dll"
    x64 := root + "/dist/windows-x64-ui/_build/WebView2Loader_x64.dll"
    if desktop_windows_find_loader_for(root,20) != arm { eprintln("ARM64 loader discovery failed")
        << 2 }
    if desktop_windows_find_loader_for(root,21) != x64 { eprintln("x64 loader discovery failed")
        << 3 }
    if doctor_windows_find_loader_for(root,20) != arm { << 14 }
    if doctor_windows_find_loader_for(root,21) != x64 { << 15 }
    if doctor_windows_find_loader_for(root + "/arm-only",21).len != 0 { << 16 }
    if doctor_windows_find_loader_for(root + "/x64-only",20).len != 0 { << 17 }
    if doctor_windows_find_loader_for(root + "/misnamed",21).len != 0 { << 18 }
    if desktop_windows_find_loader_for(root + "/arm-only",21).len != 0 { << 10 }
    if desktop_windows_find_loader_for(root + "/x64-only",20).len != 0 { << 11 }
    if desktop_windows_find_loader_for(root + "/misnamed",21).len != 0 { << 12 }
    if desktop_windows_find_loader_for(root + "/generic",20) != root + "/generic/dist/windows-x64-ui/_build/WebView2Loader.dll" { << 13 }
    expected := "spaces / 中文 / apostrophe ' / quote \" / slash \\ / $$HOME"
    output := root + "/shell result.txt"
    command := "printf '%s' " + desktop_shell_quote(&expected) + " > " + desktop_shell_quote(&output)
    if desktop_system(command) != 0 { eprintln("shell execution failed")
        << 4 }
    actual := read_file(output) or (err) { eprintln(err.msg())
        << 5 }
    if actual != expected { eprintln("shell argument round-trip failed: " + actual)
        << 6 }
    if desktop_doctor_bin().len == 0 { eprintln("sibling .exe lookup failed")
        << 7 }
    if desktop_compiler_bin() != root + "/xu.exe" { eprintln("compiler .exe lookup failed")
        << 8 }
    if desktop_system("exit 7") != 7 * 256 { eprintln("shell exit status lost")
        << 9 }
    println("Windows desktop regression checks passed")
    << 0
}
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", type=Path, required=True)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("this regression gate requires a Windows host")
    root = Path(__file__).resolve().parents[1]
    compiler = args.compiler.resolve()
    env = dict(os.environ, XU_ROOT=str(root), XU_STDLIB_ROOT=str(root / "src"), XUPATH="")
    with tempfile.TemporaryDirectory(prefix="xu desktop ") as folder:
        workspace = Path(folder)
        source = workspace / "source"
        source.mkdir()
        (source / "xu.xun").write_text("module: desktop-regression\nversion: !ver 0.1.0\n", encoding="utf-8")
        for file in (root / "src/cmd/desktop").glob("*.xu"):
            text = file.read_text(encoding="utf-8")
            if file.name == "main.xu":
                text = text.replace("fn main() int {", "fn original_desktop_main() int {", 1)
            (source / file.name).write_text(text, encoding="utf-8")
        doctor = (root / "src/cmd/doctor/main.xu").read_text(encoding="utf-8")
        start = doctor.index("fn doctor_windows_loader_matches(")
        end = doctor.index("fn doctor_check_macos(", start)
        (source / "regression.xu").write_text("@main\n" + doctor[start:end] + HARNESS, encoding="utf-8")
        loaders = workspace / "dist/windows-x64-ui/_build"
        loaders.mkdir(parents=True)
        def pe(machine):
            data = bytearray(70)
            data[:2] = b"MZ"
            struct.pack_into("<I", data, 60, 64)
            data[64:68] = b"PE\0\0"
            struct.pack_into("<H", data, 68, machine)
            return data
        for arch, machine in (("arm64", 0xAA64), ("x64", 0x8664)):
            (loaders / f"WebView2Loader_{arch}.dll").write_bytes(pe(machine))
            only = workspace / ("arm-only" if arch == "arm64" else "x64-only") / "dist/windows-x64-ui/_build"
            only.mkdir(parents=True)
            (only / f"WebView2Loader_{arch}.dll").write_bytes(pe(machine))
        for folder, filename in (("misnamed", "WebView2Loader_x64.dll"), ("generic", "WebView2Loader.dll")):
            directory = workspace / folder / "dist/windows-x64-ui/_build"
            directory.mkdir(parents=True)
            (directory / filename).write_bytes(pe(0xAA64))
        executable = workspace / "regression.exe"
        # Only existence is probed by the harness; these are never executed.
        (workspace / "xu-doctor.exe").write_bytes(b"fixture")
        shutil.copy2(compiler, workspace / "xu.exe")
        subprocess.run([str(compiler), "build", str(source), "-o", str(executable)], env=env, check=True)
        subprocess.run([str(executable), str(workspace)], env=env, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
