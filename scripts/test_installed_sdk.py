#!/usr/bin/env python3
"""Exercise an actual SDK archive from an unrelated, space-containing directory."""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
import xml.etree.ElementTree as ET


def check_windows_invoker_manifest(binary: Path):
    """Check the SDK tool's execution level using the Windows loader."""
    if os.name != "nt":
        return
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LoadLibraryExW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_ulong]
    kernel.LoadLibraryExW.restype = ctypes.c_void_p
    kernel.FindResourceW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    kernel.FindResourceW.restype = ctypes.c_void_p
    kernel.SizeofResource.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel.SizeofResource.restype = ctypes.c_ulong
    kernel.LoadResource.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel.LoadResource.restype = ctypes.c_void_p
    kernel.LockResource.argtypes = [ctypes.c_void_p]
    kernel.LockResource.restype = ctypes.c_void_p
    kernel.FreeLibrary.argtypes = [ctypes.c_void_p]
    module = kernel.LoadLibraryExW(str(binary), None, 0x22)
    if not module:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        resource = kernel.FindResourceW(module, 1, 24)
        if not resource:
            raise RuntimeError(f"executable has no embedded application manifest: {binary}")
        pointer = kernel.LockResource(kernel.LoadResource(module, resource))
        size = kernel.SizeofResource(module, resource)
        if not pointer or not size:
            raise ctypes.WinError(ctypes.get_last_error())
        root = ET.fromstring(ctypes.string_at(pointer, size))
        level = root.find('.//{urn:schemas-microsoft-com:asm.v3}requestedExecutionLevel')
        if level is None or level.get("level") != "asInvoker" or level.get("uiAccess") != "false":
            raise RuntimeError(f"executable does not declare current-user execution: {binary}")
    finally:
        kernel.FreeLibrary(module)


def run(args, *, cwd, env, timeout: int = 600):
    try:
        result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        def text(value):
            return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
        raise RuntimeError(f"{args}: timed out after {error.timeout}s\n"
                           f"{text(error.stdout)}\n{text(error.stderr)}") from error
    if result.returncode:
        raise RuntimeError(f"{args}: exit {result.returncode}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def activate(prefix, cwd, env):
    if os.name == "nt":
        # Use native PowerShell, including for installations containing spaces.
        script = cwd / "activate.ps1"
        script.write_text('param($Root)\n. "$Root\\env.ps1"\n. "$Root\\env.ps1"\n'
                          'Write-Output ("XU_ENV_JSON=" + (@{XU_ROOT=$env:XU_ROOT; '
                          'XU_STDLIB_ROOT=$env:XU_STDLIB_ROOT; XUPATH=$env:XUPATH; '
                          'PATH=$env:Path} | ConvertTo-Json -Compress))\n')
        output = run(["pwsh", "-NoProfile", "-File", str(script), str(prefix)], cwd=cwd, env=env)
    else:
        script = 'source "$1/env.sh"; source "$1/env.sh"; "$2" -c \'import json,os; print("XU_ENV_JSON=" + json.dumps({k: os.environ[k] for k in ("XU_ROOT", "XU_STDLIB_ROOT", "XUPATH", "PATH")}))\''
        output = run(["bash", "-c", script, "sdk-activation", str(prefix), sys.executable], cwd=cwd, env=env)
    values = json.loads(next(line[len("XU_ENV_JSON="):] for line in output.splitlines() if line.startswith("XU_ENV_JSON=")))
    return env | values



def macos_input_clock(prefix: Path, project: Path, env):
    """Compare the SDK's actual mouse callback with Xu's Darwin clock domain."""
    if sys.platform != "darwin":
        return
    host = prefix / "src/ui/host"
    sdk = env.get("XU_TEST_SYSROOT") or run(["xcrun", "--show-sdk-path"], cwd=project, env=env).strip()
    runtime_source = project / "runtime_clock.xu"
    runtime_source.write_text('@main\n#time\nfn main() int {\n    println(time.instant().nanoseconds())\n    << 0\n}\n')
    runtime_clock = project / "runtime-clock"
    run([str(prefix / "bin/xu"), "build", str(runtime_source), "-o", str(runtime_clock)], cwd=project, env=env)
    objects = []
    for name in ("xu_ui_mem.cc", "xu_pack_assets.c", "xu_pack_assets_weak.c"):
        obj = project / (name + ".o")
        compiler = "clang++" if name.endswith(".cc") else "clang"
        flags = ["-std=c++17"] if name.endswith(".cc") else []
        run(["xcrun", compiler, *flags, "-isysroot", sdk, "-I" + str(host),
             "-c", str(host / name), "-o", str(obj)], cwd=project, env=env)
        objects.append(str(obj))
    source = project / "native_input_clock.swift"
    source.write_text(r'''import AppKit
import Darwin
@main struct InputClockProbe {
    static func runtimeClock() -> Int64 {
        let process = Process(), pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: CommandLine.arguments[1])
        process.standardOutput = pipe
        try! process.run()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        precondition(process.terminationStatus == 0)
        return Int64(String(data: data, encoding: .utf8)!.trimmingCharacters(in: .whitespacesAndNewlines))!
    }
    static func monotonic() -> Int64 {
        var value = timespec()
        precondition(clock_gettime(CLOCK_MONOTONIC, &value) == 0)
        return Int64(value.tv_sec) * 1_000_000_000 + Int64(value.tv_nsec)
    }
    static func main() {
        let view = DrawCanvasView(frame: NSRect(x: 0, y: 0, width: 100, height: 100))
        view.inputEnabled = true
        var line = ""
        view.onInput = { line = $0 }
        let event = NSEvent.mouseEvent(with: .mouseMoved, location: NSPoint(x: 10, y: 20),
            modifierFlags: [], timestamp: ProcessInfo.processInfo.systemUptime, windowNumber: 0,
            context: nil, eventNumber: 0, clickCount: 0, pressure: 0)!
        let runtimeBefore = runtimeClock()
        let before = monotonic()
        view.mouseMoved(with: event)
        let after = monotonic()
        let runtimeAfter = runtimeClock()
        let stamp = Int64(line.split(separator: "\t").last!)!
        precondition(stamp >= before && stamp <= after, "native input and Xu use different clocks")
        precondition(stamp >= runtimeBefore && stamp <= runtimeAfter, "native input and installed compiler use different clocks")
        print("native-input-clock: PASS")
    }
}
''')
    executable = project / "native-input-clock"
    run(["xcrun", "swiftc", "-D", "XU_UI_STATIC", "-sdk", sdk, "-module-cache-path", str(project / "swift-cache"),
         str(host / "macos_host.swift"), str(host / "macos_draw.swift"), str(source), *objects,
         "-lc++", "-framework", "AppKit", "-framework", "UserNotifications", "-framework", "QuartzCore",
         "-o", str(executable)], cwd=project, env=env)
    assert run([str(executable), str(runtime_clock)], cwd=project, env=env).strip() == "native-input-clock: PASS"
    print("installed-sdk: native-input-clock PASS")


def linux_application_object(xu, target, work, env):
    machine = {"linux-arm64": 183, "linux-x64": 62}.get(target)
    if machine is None:
        return
    env = env.copy()
    env.pop("XU_UI_PACK", None)
    project = work / "Linux application object"
    project.mkdir()
    (project / "main.xu").write_text('''@main
#os
fn main() {
    args := os.argv()
    println(args[1])
    println(os.getenv("XU_APP_ENTRY_PROBE"))
}
''')
    run([xu, "build", "main.xu", "--emit-obj", "-o", "app.xuobj"], cwd=project, env=env)
    run([xu, "_elf_o", "app.xuobj", "app.o"], cwd=project, env=env)
    header = (project / "app.o").read_bytes()[:20]
    assert header[:6] == b"\x7fELF\x02\x01" and header[16:18] == b"\x01\x00", header
    assert int.from_bytes(header[18:20], "little") == machine, header
    cc = shutil.which("cc", path=env["PATH"])
    if cc:
        (project / "host.c").write_text('''#include <stdlib.h>
extern char **environ;
void xu_app_start(int argc, char **argv, char **envp, long page_size, unsigned long hwcap);
int main(int argc, char **argv) {
    if (setenv("XU_APP_ENTRY_PROBE", "C host environment", 1) != 0) return 1;
    xu_app_start(argc, argv, environ, 4096, 0);
    return 1;
}
''')
        run([cc, "-fPIE", "-pie", "host.c", "app.o", "-o", "app"], cwd=project, env=env)
        actual = run([str(project / "app"), "argument with spaces"], cwd=project, env=env).splitlines()
        assert actual == ["argument with spaces", "C host environment"], actual
    print("installed-sdk: linux-application-object PASS")


def gpu_layout(xu: str, project: Path, env):
    """Exercise the installed layout API without a window or SDL runtime."""
    project.mkdir()
    (project / "gpu_layout.xu").write_text('''@main
#gpu/layout
fn rejects(format int, width int, height int, levels int, row int, offset int) bool {
    layout.texture_2d(format, width, height, levels, row, offset) or (err) { << true }
    << false
}
fn check() int {
    tight := layout.texture_2d(layout.RGBA8_SRGB, 3, 5, 0, 1, 1) or >>
    assert(tight.level_count() == 3 && tight.total_bytes() == 72)
    base := tight.level(0) or >>
    assert(base.width == 3 && base.height == 5 && base.row_bytes == 12)
    $copy := base
    copy.row_bytes = 99
    assert((tight.level(0) or >>).row_bytes == 12)
    transfer := layout.texture_2d(layout.RGBA8_UNORM, 3, 5, 0, 256, 512) or >>
    assert(transfer.total_bytes() == 2304)
    assert((transfer.level(1) or >>).offset == 1536)
    assert((transfer.level(2) or >>).row_pitch == 256)
    blocks := layout.texture_2d(layout.BC1_RGBA_UNORM, 3, 5, 0, 1, 1) or >>
    assert(blocks.total_bytes() == 32 && (blocks.level(0) or >>).block_rows == 2)
    largest := layout.texture_2d(layout.R8_UNORM, 9223372036854775807, 1, 1, 1, 1) or >>
    assert(largest.total_bytes() == 9223372036854775807)
    assert((layout.mip_count_2d(9223372036854775807, 1) or >>) == 63)
    assert(rejects(layout.R8_UNORM, 9223372036854775807, 1, 1, 2, 1))
    assert(rejects(layout.RGBA32_FLOAT, 9223372036854775807, 1, 1, 1, 1))
    assert(rejects(999, 1, 1, 1, 1, 1) && rejects(layout.R8_UNORM, 0, 1, 1, 1, 1))
    assert(rejects(layout.R8_UNORM, 1, 1, 2, 1, 1) && rejects(layout.R8_UNORM, 1, 1, 1, 3, 1))
    for format in 1:21 {
        info := layout.format_info(format) or >>
        assert(info.block_bytes > 0 && info.depth == (format == layout.DEPTH32_FLOAT))
    }
    println("GPU layout: 72/2304/32 bytes; checked int64; no device")
    << 0
}
fn main() int {
    << check() or (err) { eprintln(err.msg())
        << 1 }
}
''')
    isolated = env | {"SDL_VIDEODRIVER": "nonexistent", "XU_GAME_SDL_LIBRARY": "nonexistent"}
    program = project / ("gpu layout.exe" if os.name == "nt" else "gpu layout")
    for level in ("-O0", "-O2", "-O3"):
        run([xu, "build", "gpu_layout.xu", level, "-o", str(program)], cwd=project, env=isolated)
        assert run([str(program)], cwd=project, env=isolated).strip() == "GPU layout: 72/2304/32 bytes; checked int64; no device"
    print("installed-sdk: gpu-layout PASS (-O0/-O2/-O3; no device)")


def gpu_device_import(xu: str, project: Path, env):
    """Compile the source-backed GPU package without a GPU runtime."""
    project.mkdir()
    (project / "main.xu").write_text('''@main
#gpu
#strings
fn check() int {
    gpu.open(gpu.DeviceOptions{backend: gpu.AUTO, debug: false, shader_formats: 0}) or (err) {
        message := err.msg()
        assert(strings.contains(&message, "SDL 3 GPU runtime unavailable"))
        println("GPU device: source backend, explicit missing-runtime error")
        << 0
    }
    << 1
}
fn main() int { << check() or (err) { eprintln(err.msg())
    << 1 } }
''')
    isolated = env | {"XU_GPU_SDL_LIBRARY": str(project / "missing SDL runtime")}
    program = project / ("GPU device.exe" if os.name == "nt" else "GPU device")
    run([xu, "build", "main.xu", "-o", str(program)], cwd=project, env=isolated)
    assert run([str(program)], cwd=project, env=isolated).strip() == "GPU device: source backend, explicit missing-runtime error"
    print("installed-sdk: gpu-device-import PASS (no SDL headers or runtime; no application native declaration)")


def native_byte_spans(xu: str, target: str, project: Path, env):
    """Check byte-span descriptors and COW on each native installed SDK."""
    project.mkdir()
    (project / "native.json").write_text(json.dumps({"module": "sdk_bytes", "abi": "xu-c-2", "exports": [
        {"name": "copy", "params": ["u8_span", "u8_span_mut", "int"], "ret": "int"},
        {"name": "mixed", "params": ["u8_span"] + ["f64"] * 9 + ["i64_span", "bool", "i32", "u32", "u8", "u8_span_mut"], "ret": "f64"}]}))
    (project / "native.c").write_text('''#include "xu_native.h"
xu_int XU_NATIVE_SYMBOL(xu_sdk_bytes_copy)(const xu_u8_span *src, const xu_u8_span_mut *dst, xu_int bias) {
    if (!src || !dst || src->len != dst->len || src->len < 0) return -1;
    for (xu_int i = 0; i < src->len; ++i) dst->data[i] = (unsigned char)(src->data[i] + bias);
    return src->len;
}
double XU_NATIVE_SYMBOL(xu_sdk_bytes_mixed)(const xu_u8_span *src, double a, double b, double c, double d, double e,
    double f, double g, double h, double i, const xu_i64_span *ints, _Bool flag, int narrow, unsigned int positive,
    unsigned char byte, const xu_u8_span_mut *dst) {
    if (src->len != 4 || ints->len != 1 || dst->len != 1 || !flag || narrow != -7 || positive != 4000000000u || byte != 255) return -1;
    dst->data[0] = src->data[2];
    return a + b + c + d + e + f + g + h + i + ints->data[0];
}
''')
    (project / "xu.xun").write_text('module: main\nversion: !ver 0.1.0\nnative:\n  sdk_bytes: file:./bytes.a\n')
    run([xu, "native", "compile", "--manifest", "native.json", "--target", target,
         "-o", "bytes.a", "native.c"], cwd=project, env=env)
    (project / "main.xu").write_text('''@main
#sdk_bytes
struct Bytes { guard int
 data []u8
 tail u8 }
fn main() int {
    source := Bytes{guard: 91,data: [u8(0),u8(127),u8(128),u8(255)],tail: u8(17)}
    $output := [u8(73),u8(73),u8(73),u8(73)]
    snapshot := ~output
    assert(sdk_bytes.copy(&source.data,$&output,129)==4)
    assert(output[0]==u8(129) && output[1]==u8(0) && output[2]==u8(1) && output[3]==u8(128))
    assert(snapshot[0]==u8(73) && snapshot[3]==u8(73) && source.data[3]==u8(255))
    $holder := Bytes{guard: 123,data: [u8(73),u8(73),u8(73),u8(73)],tail: u8(19)}
    retained := ~holder
    assert(sdk_bytes.copy(&source.data,$&holder.data,129)==4)
    assert(holder.data[0]==u8(129) && holder.data[3]==u8(128) && retained.data[0]==u8(73))
    assert(holder.guard==123 && holder.tail==u8(19) && source.guard==91 && source.tail==u8(17))
    empty := []u8{}
    $destination := []u8{}
    assert(sdk_bytes.copy(&empty,$&destination,0)==0)
    ints := [10]
    $mixed_output := [u8(73)]
    mixed_snapshot := ~mixed_output
    result := sdk_bytes.mixed(&source.data,1.0,2.0,3.0,4.0,5.0,6.0,7.0,8.0,9.0,&ints,true,i32(-7),u32(4000000000),u8(255),$&mixed_output)
    assert(result==55.0 && mixed_output[0]==u8(128) && mixed_snapshot[0]==u8(73))
    println("Native byte spans: packed bytes, borrowed fields, COW and empty views; mixed scalar ABI")
    << 0
}
''')
    program = project / ("native bytes.exe" if os.name == "nt" else "native bytes")
    for level in ("-O0", "-O2", "-O3"):
        run([xu, "build", "main.xu", level, "-o", str(program)], cwd=project, env=env)
        assert run([str(program)], cwd=project, env=env).strip() == "Native byte spans: packed bytes, borrowed fields, COW and empty views; mixed scalar ABI"
    print("installed-sdk: native-byte-spans PASS (-O0/-O2/-O3)")


def smoke(archive: Path | None, work: Path, native_setup: bool = False, installer: Path | None = None):
    prefix = work / "installed Xu SDK"
    project = work / "user project with spaces"
    project.mkdir()
    extra = work / "custom package search root"
    (extra / "sdk_probe").mkdir(parents=True)
    (extra / "sdk_probe/mod.xu").write_text('@sdk_probe\npub fn answer() int { << 42 }\n')
    env = dict(os.environ)
    for key in ("XU_ROOT", "XU_STDLIB_ROOT", "XUOS", "XUARCH", "XU_PACKAGES_ROOT", "XU_VSCODE_ROOT", "XU_BOOT_EXTRA"):
        env.pop(key, None)
    env.update(XU_SKIP_EDITOR_INSTALL="1", XUPATH=str(extra), XU_CACHE=str(work / "package cache"))

    if installer:
        check_windows_invoker_manifest(installer)
        run([str(installer), "--prefix", str(prefix), "--yes", "--no-modify-path"], cwd=project, env=env)
        manifest_file = prefix / "bundle.json"
        manifest = json.loads(manifest_file.read_text()) if manifest_file.is_file() else {"version": "", "target": "host", "lane": "product"}
    else:
        assert archive is not None, "archive must be provided when installer is None"
        extract = work / "unpacked SDK"
        extract.mkdir()
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as source:
                source.extractall(extract)
        else:
            with tarfile.open(archive) as source:
                source.extractall(extract, filter="data")
        bundle, = (p for p in extract.iterdir() if p.is_dir())
        manifest = json.loads((bundle / "bundle.json").read_text())
        if os.name == "nt":
            for setup in (bundle / "xu-setup.exe", bundle / "bin/xu-setup.exe"):
                check_windows_invoker_manifest(setup)
        if native_setup:
            setup = bundle / ("xu-setup.exe" if os.name == "nt" else "xu-setup")
            run([str(setup), "--prefix", str(prefix), "--yes", "--no-modify-path"], cwd=project, env=env)
        elif os.name == "nt":
            run(["pwsh", "-NoProfile", "-File", str(bundle / "install.ps1"), "-Prefix", str(prefix), "-NoModifyPath"], cwd=project, env=env)
        else:
            run(["bash", str(bundle / "install.sh"), "--prefix", str(prefix), "--no-modify-path", "--yes"], cwd=project, env=env)
    if os.name == "nt":
        check_windows_invoker_manifest(prefix / "bin/xu-update.exe")
    active = activate(prefix, project, env)
    entries = active["XUPATH"].split(os.pathsep)
    assert entries.count(str(extra)) == 1, entries
    assert entries.count(str(prefix / "src")) == 1, entries
    assert active["PATH"].split(os.pathsep).count(str(prefix / "bin")) == 1
    xu = shutil.which("xu", path=active["PATH"])
    assert xu and Path(xu).parent == prefix / "bin", xu
    assert manifest["version"] in run([xu, "--version"], cwd=project, env=active)
    if manifest["target"] == "linux-x64":
        compiler_wasm = work / "xu.wasm"
        run([xu, "build", str(prefix / "src/cmd/compile"), "--target", "wasm32-wasi",
             "-o", str(compiler_wasm)], cwd=project, env=active)
        with compiler_wasm.open("rb") as module:
            assert module.read(8) == b"\x00asm\x01\x00\x00\x00"
    (project / "main.xu").write_text('''@main
#strings
#sdk_probe
fn main() int {
    word := "installed"
    println(strings.to_upper(&word))
    println(sdk_probe.answer())
    << 0
}
''')
    (project / "xu.xun").write_text('module: main\nversion: !ver 0.1.0\nrequire:\n  sdk_probe: file:../custom package search root\n')
    assert run([xu, "run", "main.xu"], cwd=project, env=active).splitlines() == ["INSTALLED", "42"]
    program = project / ("user program.exe" if os.name == "nt" else "user program")
    run([xu, "build", "main.xu", "-o", str(program)], cwd=project, env=active)
    assert run([str(program)], cwd=project, env=active).splitlines() == ["INSTALLED", "42"]
    # Values of CLI options must not become dependency policy flags. This
    # project has a real dependency but deliberately no existing lock entry.
    policy_project = work / "output named like a policy flag"
    policy_project.mkdir()
    (policy_project / "main.xu").write_text('@main\n#sdk_probe\nfn main() int { println(sdk_probe.answer())\n    << 0 }\n')
    (policy_project / "xu.xun").write_text('module: main\nversion: !ver 0.1.0\nrequire:\n  sdk_probe: file:../custom package search root\n')
    run([xu, "build", "main.xu", "-o", "--frozen"], cwd=policy_project, env=active)
    policy_program = policy_project / ("--frozen.exe" if os.name == "nt" else "--frozen")
    assert run([str(policy_program)], cwd=policy_project, env=active).strip() == "42"
    # Executable-relative stdlib discovery must work without activation.
    clean = active.copy()
    clean.pop("XU_STDLIB_ROOT", None)
    clean.pop("XU_ROOT", None)
    assert run([xu, "run", "main.xu"], cwd=project, env=clean).splitlines() == ["INSTALLED", "42"]
    gpu_layout(xu, work / "GPU layout project", clean)
    gpu_device_import(xu, work / "GPU device project", clean)
    native_byte_spans(xu, manifest["target"], work / "native byte spans", clean)
    # SDK root discovery is independent of external GUI toolchain availability.
    # Doctor may report missing GTK/Swift/MinGW here, but must locate this SDK
    # before probing those host dependencies. Exercise direct PATH and CLI use.
    # Windows CreateProcess does not use the supplied child environment for
    # bare-command lookup. Resolve the activated PATH explicitly on every OS.
    path_doctor = shutil.which("xu-doctor", path=clean["PATH"])
    assert path_doctor and Path(path_doctor).resolve().parent == (prefix / "bin").resolve(), path_doctor
    for command in ([xu, "doctor"], [path_doctor]):
        doctor = subprocess.run([*command, "--target", manifest["target"]], cwd=project,
                                env=clean, text=True, capture_output=True, timeout=90)
        match = re.search(r"(?m)^  \[ok\]\s+Xu SDK root\s+(.+)$", doctor.stdout)
        assert match, (doctor.returncode, doctor.stdout, doctor.stderr)
        assert Path(match.group(1).strip()).resolve() == prefix.resolve(), doctor.stdout
    macos_input_clock(prefix, project, clean)
    linux_application_object(xu, manifest["target"], work, clean)
    # Exercise the actual desktop entry and sibling Doctor invocation. The small
    # project deliberately has no icon, so it stops before external GUI builds.
    desktop = subprocess.run([xu, "build", str(project), "--desktop", "--no-webview",
                              "--target", manifest["target"]], cwd=project,
                             env=clean, text=True, capture_output=True, timeout=90)
    match = re.search(r"(?m)^  \[ok\]\s+Xu SDK root\s+(.+)$", desktop.stdout)
    assert match, (desktop.returncode, desktop.stdout, desktop.stderr)
    assert Path(match.group(1).strip()).resolve() == prefix.resolve(), desktop.stdout
    stale = work / "stale checkout"
    (stale / "src/ui/host").mkdir(parents=True)
    for marker in ("macos_host.swift", "xu_content_abi.h"):
        (stale / "src/ui/host" / marker).write_text("")
    doctor = subprocess.run([xu, "doctor", "--target", manifest["target"]], cwd=project,
                            env=clean | {"XU_ROOT": str(stale)}, text=True, capture_output=True, timeout=90)
    match = re.search(r"(?m)^  \[ok\]\s+Xu SDK root\s+(.+)$", doctor.stdout)
    assert match and Path(match.group(1).strip()).resolve() == prefix.resolve(), doctor.stdout
    # PATH lookup finds the compiler and its sibling tools from outside the SDK.
    run([xu, "fmt", "main.xu"], cwd=project, env=active)
    (project / "exit.xu").write_text('@main\nfn main() int { << 7 }\n')
    child = subprocess.run([xu, "run", "exit.xu"], cwd=project, env=active, capture_output=True, text=True, timeout=90)
    assert child.returncode == 7, (child.returncode, child.stderr)
    (project / "args.xu").write_text('@main\n#os\nfn main() int {\n    args := os.argv()\n    println(args[1])\n    println(args[2])\n    << 0\n}\n')
    for arguments in (["argument with spaces", 'quote"value\\'], ["", ""], ['space and \\', 'two\\\\"quotes']):
        actual = run([xu, "run", "args.xu", "--", *arguments], cwd=project, env=active).splitlines()
        assert actual == arguments, (arguments, actual)
    arguments = ["-O0", "-O2"]
    actual = run([xu, "run", "args.xu", "-O3", "--", *arguments], cwd=project, env=active).splitlines()
    assert actual == arguments, (arguments, actual)
    # Exercise optimized compilation and child execution in the installed CLI.
    # All input is created in the user's temporary project, independent of tests/.
    (project / "loop.xu").write_text('@main\nfn main() int {\n    $total := 0\n    $i := 0\n    while i < 32768 {\n        total = total + i\n        i = i + 1\n    }\n    println(total)\n    << 0\n}\n')
    for level in ("-O0", "-O2", "-O3"):
        run([xu, "build", "loop.xu", level, "-o", str(program)], cwd=project, env=active)
        assert run([str(program)], cwd=project, env=active).strip() == "536854528"
        assert run([xu, "run", "loop.xu", level], cwd=project, env=active).strip() == "536854528"
    # Native map adapters must preserve the coroutine context when calling
    # ordinary Xu hashing and growth policy functions with entry stack guards.
    (project / "map_worker.xu").write_text('''@main
fn worker(done chan int) {
    $integers := map[int]int{}
    $names := map[string]int{}
    for i in 0:128 {
        integers[i] = i * 3
        names[str(i)] = i * 5
    }
    $total := 0
    for i in 0:128 {
        total += integers[i]
        total += names[str(i)]
    }
    done <- total
}
fn main() {
    done := chan int{cap: 1}
    xu worker(done)
    println(<-done)
}
''')
    for level in ("-O0", "-O2", "-O3"):
        run([xu, "build", "map_worker.xu", level, "-o", str(program)], cwd=project, env=active)
        assert run([str(program)], cwd=project, env=active).strip() == "65024"
    # Verify shared calls, mutable methods, function values and mutation on
    # error paths without corrupting adjacent packed records.
    (project / "borrow_record.xu").write_text('''@main
#errors
struct Record { value int
 guard int
 label string }
fn read(r &Record) int { << r.value + r.guard + r.label.len }
fn change(r $&Record) int { r.value += 11
 r.label = "new" + "-field"
 << 0 }
fn (r $&Record) bump() int { r.value += 7
 << r.value }
fn fail_after_change(r $&Record) int { r.value += 3
 >> errors.new("expected") }
struct Packed { a i32
 b i32
 c u8 }
fn (p $&Packed) bump() int { p.a += i32(2)
 p.c += u8(1)
 << int(p.a) + int(p.b) + int(p.c) }
struct@ Mutator { fn change($&Record) int }
struct Worker { n int }
fn (w Worker) change(r $&Record) int { << change(r) }
struct Tiny { a u8
 b u8 }
fn main() int {
 $records := [Record{value: 1,guard: 100,label: "old"},Record{value: 2,guard: 200,label: "old"}]
 i := 1
 r := $&records[i]
 println(read(&*r))
 println(r.bump())
 f := change
 _ := f(r)
 for once in 0:1 { _ := fail_after_change(r) or (err) { println(err.msg())
 -> } }
 println(read(&*r))
 println(records[0].value)
 println(records[0].guard)
 println(records[0].label)
 $packed := [Packed{a: 1,b: 2,c: 3},Packed{a: 10,b: 20,c: 30}]
 p := $&packed[i]
 println(p.bump())
 println(int(packed[0].a))
 println(int(packed[0].c))
 println(int(packed[1].a))
 println(int(packed[1].c))
 $values := map[int]Record{}
 values[3] = Record{value: 4,guard: 50,label: "map"}
 m := $&values[3]
 println(m.bump())
 println(read(&*m))
 dynamic := Mutator(Worker{n: 1})
 println(dynamic.change(m))
 read_fn := read
 println(read_fn(&*m))
 packed[1] = Packed{a: 20,b: 30,c: 40}
 copy := packed[1]
 println(int(copy.c))
 packed[1] = copy
 packed.push(Packed{a: 50,b: 60,c: 70})
 println(packed.len)
 $last := $&packed[2]
 println(last.bump())
 println(int(last.c))
 println(int(packed[1].c))
 $tiny := [Tiny{a: 1,b: 2},Tiny{a: 3,b: 4},Tiny{a: 5,b: 6}]
 tiny[1] = Tiny{a: 7,b: 8}
 copied := tiny[1]
 println(int(copied.b))
 println(int(tiny[0].a))
 println(int(tiny[0].b))
 println(int(tiny[2].a))
 println(int(tiny[2].b))
 << 0
}
''')
    for level in ("-O0", "-O2", "-O3"):
        run([xu, "build", "borrow_record.xu", level, "-o", str(program)], cwd=project, env=active)
        actual = run([str(program)], cwd=project, env=active).splitlines()
        assert actual == ["205", "9", "expected", "232", "1", "100", "old", "63", "1", "3", "12", "31", "11", "64", "0", "81", "40", "3", "183", "71", "40", "8", "1", "2", "5", "6"], actual
    # Returned element borrows alias their original storage while the owner
    # is live. Keep these entry points separate from the desktop smoke app.
    borrow_project = work / "borrow lifetime project"
    borrow_project.mkdir()
    (borrow_project / "borrow_element.xu").write_text('''@main
struct Record { value int
 guard int }
fn identity(r $&Record) $&Record { << r }
fn main() {
    $records := [Record{value: 1, guard: 101}, Record{value: 2, guard: 202}]
    i := 1
    r := identity($&records[i])
    r.value = 3
    println(r.guard)
    println(records[i].value)
    println(records[0].value)
}
''')
    actual = run([xu, "run", "borrow_element.xu", "-O2"], cwd=borrow_project, env=active).splitlines()
    assert actual == ["202", "3", "1"], actual
    (borrow_project / "borrow_escape.xu").write_text('''@main
fn identity(s &string) &string { << s }
fn escape(source &string) &string {
    words := ["one", "two"]
    << identity(&words[1])
}
fn main() {
    source := "source"
    println(escape(&source).len)
}
''')
    rejected = subprocess.run([xu, "build", "borrow_escape.xu", "-o", str(program)], cwd=borrow_project,
                              env=active, text=True, capture_output=True, timeout=90)
    assert rejected.returncode != 0 and "cannot return a reference to local data" in rejected.stderr, (rejected.stdout, rejected.stderr)
    # Passive help has deterministic hover delay, dismissal and edge placement.
    # An ordinary build must remain a plain executable even with UI imports;
    # no native GUI host, brand icon, or external GUI toolchain is needed.
    tooltip_project = work / "tooltip project"
    tooltip_project.mkdir()
    (tooltip_project / "tooltip_state.xu").write_text('''@main
#ui
#ui/widgets
#ui/layout
#time
#errors
fn expect(value bool,message string) int {
    if !value { >> errors.new(message) }
    << 0
}
fn input(kind int,x f64,y f64,now time.Instant) ui.InputEvent {
    << ui.InputEvent{kind: kind,window_id: 1,canvas_id: 1,generation: 1,x: x,y: y,dx: 0.0,dy: 0.0,
        button: ui.BUTTON_LEFT,buttons: 0,modifiers: 0,key: 0,scan: 0,repeat: 0,click_count: 0,time_ns: now.nanoseconds()}
}
fn verify() int {
    identity := ui.CanvasEvent{window_id: 1,canvas_id: 1,generation: 1}
    anchor := layout.Rect{x: 140.0,y: 180.0,width: 80.0,height: 40.0}
    size := layout.Size{width: 120.0,height: 60.0}
    viewport := layout.Rect{x: 0.0,y: 0.0,width: 400.0,height: 400.0}
    $tip := widgets.tooltip(&identity,10,&anchor,&size,&viewport) or >>
    start := time.instant()
    move := input(ui.EV_POINTER_MOVE,160.0,200.0,start)
    _ := tip.input(&move) or >>
    expect(!tip.is_open(),"hover opened before delay") or >>
    _ := tip.tick(start.add(time.milliseconds(499) or >>) or >>,true) or >>
    expect(!tip.is_open(),"hover opened at 499ms") or >>
    shown := start.add(time.milliseconds(500) or >>) or >>
    _ := tip.tick(shown,true) or >>
    expect(tip.is_open(),"hover did not open at 500ms") or >>
    bounds := tip.bounds()
    expect(bounds.y + bounds.height <= anchor.y && bounds.x == 120.0,"default top/center placement") or >>
    click := input(ui.EV_POINTER_DOWN,160.0,200.0,shown)
    _ := tip.input(&click) or >>
    expect(!tip.is_open(),"click did not dismiss") or >>
    _ := tip.input(&move) or >>
    _ := tip.tick(shown.add(time.seconds(1) or >>) or >>,true) or >>
    expect(!tip.is_open(),"click suppression lost before leaving") or >>
    leave := input(ui.EV_POINTER_MOVE,380.0,380.0,shown)
    _ := tip.input(&leave) or >>
    _ := tip.input(&move) or >>
    _ := tip.tick(shown.add(time.seconds(1) or >>) or >>,true) or >>
    expect(tip.is_open(),"hover did not reset after leaving") or >>
    _ := tip.input(&leave) or >>
    expect(!tip.is_open(),"hover leave did not close") or >>
    tip.set_focus(true,shown) or >>
    expect(tip.is_open(),"keyboard focus did not open") or >>
    $escape := input(ui.EV_KEY_DOWN,0.0,0.0,shown)
    escape.key = ui.KEY_ESCAPE
    _ := tip.input(&escape) or >>
    expect(!tip.is_open(),"Escape did not dismiss") or >>
    tip.set_focus(true,shown) or >>
    expect(!tip.is_open(),"Escape suppression lost") or >>
    tip.set_focus(false,shown) or >>
    tip.set_focus(true,shown) or >>
    expect(tip.is_open(),"refocus did not reset suppression") or >>
    for side in 0:4 {
        $placement := widgets.overlay_placement()
        placement.side = side
        placement.align = widgets.OVERLAY_CENTER
        tip.set_placement(&placement) or >>
        b := tip.bounds()
        if side == widgets.OVERLAY_BOTTOM { expect(b.y >= anchor.y + anchor.height,"bottom placement") or >> }
        if side == widgets.OVERLAY_TOP { expect(b.y + b.height <= anchor.y,"top placement") or >> }
        if side == widgets.OVERLAY_LEFT { expect(b.x + b.width <= anchor.x,"left placement") or >> }
        if side == widgets.OVERLAY_RIGHT { expect(b.x >= anchor.x + anchor.width,"right placement") or >> }
    }
    $placement := widgets.overlay_placement()
    placement.side = widgets.OVERLAY_TOP
    tip.set_placement(&placement) or >>
    edge := layout.Rect{x: 4.0,y: 4.0,width: 80.0,height: 40.0}
    tip.set_geometry(&edge,&size,&viewport) or >>
    flipped := tip.bounds()
    expect(flipped.y >= edge.y + edge.height,"edge did not flip") or >>
    tip.set_enabled(false) or >>
    expect(!tip.is_open() && !tip.is_visible(),"disabled tooltip stayed visible") or >>
    println("tooltip state and placement PASS")
    << 0
}
fn main() int { << verify() or (err) { eprintln(err.msg())
    << 1 } }
''')
    run([xu, "build", "tooltip_state.xu", "-O2", "-o", str(program)], cwd=tooltip_project, env=active)
    tooltip_output = run([str(program)], cwd=project, env=active).strip()
    assert tooltip_output == "tooltip state and placement PASS", tooltip_output
    # Canonical bundled modules resolve from their installed manifest root.
    if (prefix / "packages/xu.xun").is_file():
        (project / "xu.xun").write_text('module: main\nversion: !ver 0.1.0\nrequire:\n  "github.com/xulang-org/packages": file:' + (prefix / "packages").as_posix() + '\n')
        (project / "main.xu").write_text('@main\nredis #"github.com/xulang-org/packages/redis"\nfn main() int {\n    value := redis.int_value(42)\n    answer := value.as_int() or (err) { << 1 }\n    println(answer)\n    << 0\n}\n')
        assert run([xu, "run", "main.xu"], cwd=project, env=active).strip() == "42"
        example = prefix / "examples/21_standalone_redis/main.xu"
        if example.is_file():
            run([xu, "check", str(example)], cwd=project, env=active)
    # Imported constant names are checked through real installed examples.
    # Declaration-only migration can leave the compiler and hello-world smoke
    # green while the bundled UI and service examples no longer type-check.
    if (prefix / "examples").is_dir():
        examples = [
            "16_ui_webview/draw/main.xu",
            "16_ui_webview/widgets/main.xu",
            "16_ui_webview/style_gallery/main.xu",
            "16_ui_webview/component_workshop/main.xu",
        ]
        if (prefix / "packages/xu.xun").is_file():
            examples += ["47_standalone_websocket/main.xu", "49_standalone_dns/main.xu"]
        for relative in examples:
            example = prefix / "examples" / relative
            if not example.is_file():
                raise RuntimeError(f"SDK example is missing: {relative}")
            check_target = str(example.parent if (example.parent / "xu.xun").is_file() else example)
            run([xu, "check", check_target], cwd=project, env=active)
            print(f"installed-sdk: example-check PASS {relative}")
    print(f"installed-sdk: PASS target={manifest['target']} lane={manifest['lane']} version={manifest['version']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="path to SDK archive (.tar.gz or .zip)")
    parser.add_argument("--installer", type=Path, help="path to standalone setup installer executable")
    parser.add_argument("--native-setup", action="store_true", help="verify the native installer instead of the shell script")
    args = parser.parse_args()
    if not args.archive and not args.installer:
        parser.error("either --archive or --installer is required")
    with tempfile.TemporaryDirectory(prefix="xu-sdk-smoke-") as directory:
        smoke(
            args.archive.resolve() if args.archive else None,
            Path(directory).resolve(),
            args.native_setup,
            installer=args.installer.resolve() if args.installer else None,
        )


if __name__ == "__main__":
    main()
