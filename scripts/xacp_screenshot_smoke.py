#!/usr/bin/env python3
"""Seven screenshot/redaction groups over stdio and the attach launcher.

Uses the product compiler and the real Linux Cairo/Pango raster backend without
opening a desktop window. Every control read has a deadline. No socket needed.
"""
import base64
import json
import math
import os
from pathlib import Path
import re
import shlex
import stat
import struct
import subprocess
import sys
import tempfile
import zlib

from xacp_screen_marshal_smoke import Attached, example_path, frame, hello
from xacp_frame import fd_reader, read_frame
from xacp_screen_marshal_smoke import checked

ROOT = Path(__file__).resolve().parents[1]


def run(command):
    result = subprocess.run([str(x) for x in command], cwd=ROOT,
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, (command, result.stdout, result.stderr)
    return result.stdout


def build_fixture(xu, directory):
    obj = directory / "screen.xuobj"
    run([ROOT / "scripts/run_product_compiler.sh", xu, "build", "--xacp", "--emit-obj",
         example_path("attach/main.xu"), "-o", obj])
    run([sys.executable, ROOT / "scripts/xuobj_to_elf_o.py", obj, directory / "screen.o"])
    flags = shlex.split(run(["pkg-config", "--cflags", "--libs", "gtk4", "pangocairo"]))
    cxx = shlex.split(os.environ.get("CXX", "c++"))
    for name in ("xu_ui_mem", "linux_draw"):
        run([*cxx, "-O2", "-std=c++17", "-DXU_UI_STATIC", "-Isrc/ui/host", "-c",
             ROOT / f"src/ui/host/{name}.cc", "-o", directory / f"{name}.o", *flags])
    shim = directory / "host.cc"
    shim.write_text(r'''
#include "xu_ui_mem.h"
#include "xu_ui_windows.h"
#include "xu_draw_frame.h"
#include <cstdlib>
#include <cstring>
#include <unistd.h>
#include <sys/auxv.h>
extern char **environ;
extern "C" void xu_app_start_hosted(int,char **,char **,long,unsigned long,int (*)(void *(*)(void *),void *));
extern "C" void xu_draw_text_init();
extern "C" int xu_ui_host_run(const char *) { return 127; }
int main(int argc,char **argv) {
    setenv("XU_UI_PACK","1",1); unsetenv("XU_UI_TMP");
    xu_draw_text_init();
    unsigned identity[2];
    if (!xu_ui_window_reserve(identity) || identity[0]!=1 || identity[1]!=1) return 90;
    unsigned char packet[39]={}; memcpy(packet,"XUW1",4);
    auto word=[&](unsigned offset,unsigned value) {
        for(unsigned i=0;i<4;++i) packet[offset+i]=(unsigned char)(value>>(i*8));
    };
    word(4,1);word(8,1);word(12,1);word(16,400);word(20,240);word(24,2);word(28,7);
    memcpy(packet+32,"private",7); unsigned written=0;
    xu_ui_mem_try_write(":xu:/__window_open",packet,sizeof(packet),&written);
    if(written!=sizeof(packet) || !xu_ui_window_claim(1,1) || !xu_ui_window_ready(1,1)) return 91;
    xu_app_start_hosted(argc,argv,environ,sysconf(_SC_PAGESIZE),getauxval(AT_HWCAP),xu_ui_runtime_start_worker);
    return 0;
}
''')
    app = directory / "screen"
    run([*cxx, "-O2", "-std=c++17", "-Isrc/ui/host", shim, directory / "screen.o",
         directory / "xu_ui_mem.o", directory / "linux_draw.o", "-pthread",
         "-Wl,--allow-multiple-definition", "-o", app, *flags])
    return app


def scalar(response, key, indent="  "):
    value = re.search(rf"^{indent}{re.escape(key)}: (?:![ifb] )?(.+)$", response, re.M)
    assert value, (key, response[:2000])
    value = value[1]
    return json.loads(value) if value.startswith('"') else value


def png_pixels(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n", data[:20]
    offset, compressed, chunks = 8, b"", []
    while offset < len(data):
        size, kind = struct.unpack_from(">I4s", data, offset)
        body = data[offset + 8:offset + 8 + size]
        crc, = struct.unpack_from(">I", data, offset + 8 + size)
        assert zlib.crc32(kind + body) == crc
        chunks.append(kind)
        if kind == b"IHDR":
            width, height, depth, color, comp, filt, interlace = struct.unpack(">IIBBBBB", body)
            assert (depth, color, comp, filt, interlace) == (8, 6, 0, 0, 0)
        if kind == b"IDAT":
            compressed += body
        offset += 12 + size
    assert offset == len(data) and chunks == [b"IHDR", b"IDAT", b"IEND"], chunks
    raw = zlib.decompress(compressed)
    stride = width * 4 + 1
    assert len(raw) == height * stride
    assert all(raw[y * stride] == 0 for y in range(height))
    return width, height, b"".join(raw[y * stride + 1:(y + 1) * stride] for y in range(height))


def inline(response):
    assert scalar(response, "mode") == "inline_b64"
    assert scalar(response, "mime") == "image/png"
    png = base64.b64decode(scalar(response, "data"), validate=True)
    assert len(png) == int(scalar(response, "bytes"))
    width, height, pixels = png_pixels(png)
    assert (width, height) == (int(scalar(response, "pixel_width")), int(scalar(response, "pixel_height")))
    return width, height, pixels


def secret_node(response):
    node = response.split("    - id: !i 3\n")[1]
    return node


def exercise(app, launcher, runtime):
    overrides = {"XDG_RUNTIME_DIR": str(runtime), "XU_XACP_SCREENSHOT_MAX_BYTES": ""}

    def peer(**extra):
        return Attached(app, launcher, env_overrides={**overrides, **extra})

    def shot(p, i, extra="", error=None):
        return p.request(frame(i, "ui.screenshot", "\n  win: !i 1" + extra), i, error)

    # 1. Default PNG and node geometry. 2. Secret tree/pixels and RAW opt-in.
    p = peer(XU_XACP_ALLOW_RAW="1")
    try:
        assert "permissions: !i 31\n" in p.request(hello(), 1)
        tree = p.request(frame(2, "ui.tree"), 2)
        assert scalar(tree, "redacted", "") == "true" and "title:" not in tree
        secret = secret_node(tree)
        assert 'text: ""\n' in secret and "redacted: !b true\n" in secret
        rect = tuple(int(float(scalar(secret, k, "      "))) for k in ("x", "y", "width", "height"))
        default = shot(p, 3)
        assert scalar(default, "redacted", "") == "true"
        width, height, pixels = inline(default)
        assert (width, height) == (400, 240)
        x, y, w, h = rect
        grey = bytes((128, 128, 128, 255))
        assert all(pixels[(row * width + x) * 4:(row * width + x + w) * 4] == grey * w
                   for row in range(y, y + h)), "secret rectangle leaked pixels"
        raw_tree = p.request(frame(4, "ui.tree", "\n  raw: !b true"), 4)
        assert scalar(raw_tree, "redacted", "") == "false"
        assert 'text: "xacp-smoke-secret"' in secret_node(raw_tree)
        raw_pixels = inline(shot(p, 5, "\n  raw: !b true"))[2]
        assert raw_pixels != pixels
        assert any(raw_pixels[(row * width + x) * 4:(row * width + x + w) * 4] != grey * w
                   for row in range(y, y + h))
        # Node snapshots translate origin; fractional scale covers edge pixels.
        cropped = inline(shot(p, 6, "\n  node: !i 3\n  scale: !f 0.7"))
        assert cropped[2] == grey * (cropped[0] * cropped[1])
        # RAW must never change later default snapshots or the source Surface.
        assert inline(shot(p, 7))[2] == pixels
        scaled_w, scaled_h, scaled = inline(shot(p, 8, "\n  scale: !f 0.333"))
        left, top = math.floor(x * scaled_w / width), math.floor(y * scaled_h / height)
        right = math.ceil((x + w) * scaled_w / width)
        bottom = math.ceil((y + h) * scaled_h / height)
        assert all(scaled[(row * scaled_w + left) * 4:(row * scaled_w + right) * 4] == grey * (right - left)
                   for row in range(top, bottom))
        p.finish()
    finally:
        p.stop()

    # 3. Default token policy denies RAW and the same id remains usable.
    for allow in ("", "01", "true"):
        p = peer(XU_XACP_ALLOW_RAW=allow)
        try:
            assert "permissions: !i 15\n" in p.request(hello(permissions=31), 1)
            p.request(frame(2, "ui.tree", "\n  raw: !b true"), 2, "permission_denied")
            shot(p, 2, "\n  raw: !b true", "permission_denied")
            p.request(frame(2, "proc.status"), 2)
            p.finish()
        finally:
            p.stop()
    p = Attached(app, launcher, token="", env_overrides={**overrides, "XU_XACP_ALLOW_RAW": "1"})
    try:
        assert "permissions: !i 1\n" in p.request(hello(permissions=31), 1)
        shot(p, 2, "\n  raw: !b true", "permission_denied")
        p.request(frame(2, "proc.status"), 2)
        p.finish()
    finally:
        p.stop()

    # 4. Private files, exclusive collision, FIFO, EOF cleanup and schema path.
    p = peer()
    paths = []
    try:
        p.request(hello(), 1)
        pid = int(scalar(p.request(frame(2, "proc.status"), 2), "pid"))
        directory = runtime / "xacp" / str(pid)
        for i in range(3, 20):
            response = shot(p, i, "\n  mode: file")
            name = scalar(response, "path")
            assert re.fullmatch(r"shot-[0-9]+-[0-9]+\.png", name), name
            assert scalar(response, "dir_hint") == "xacp-runtime"
            assert str(runtime) not in response and "title:" not in response
            path = directory / name
            assert stat.S_IMODE(directory.stat().st_mode) == 0o700
            assert stat.S_IMODE(directory.parent.stat().st_mode) == 0o700
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
            data = path.read_bytes()
            assert len(data) == int(scalar(response, "bytes"))
            assert png_pixels(data)[2] == pixels
            paths.append(path)
        assert not paths[0].exists() and all(path.exists() for path in paths[1:])
        # An existing name is never overwritten or followed.
        generation = re.fullmatch(r"shot-(\d+)-\d+\.png", paths[-1].name)[1]
        conflict = directory / f"shot-{generation}-20.png"
        conflict.symlink_to(paths[-1].name)
        shot(p, 20, "\n  mode: file", "file_unavailable")
        assert conflict.is_symlink()
        conflict.unlink()
        p.request(frame(21, "proc.status"), 21)
        p.finish()
        assert all(not path.exists() for path in paths)
        assert not directory.exists(), "session did not remove its empty pid directory"
    finally:
        p.stop()
    p = peer(XDG_RUNTIME_DIR="", TMPDIR=str(runtime))
    try:
        p.request(hello(), 1)
        pid = int(scalar(p.request(frame(2, "proc.status"), 2), "pid"))
        response = shot(p, 3, "\n  mode: file")
        fallback = runtime / f"xacp-{os.getuid()}" / str(pid) / scalar(response, "path")
        assert fallback.is_file() and stat.S_IMODE(fallback.stat().st_mode) == 0o600
        p.finish()
        assert not fallback.exists()
    finally:
        p.stop()
    p = peer()
    try:
        p.request(hello(), 1)
        shot(p, 2, '\n  mode: file\n  path: "/private/host/dump.png"', "schema_error")
        p.finish()
    finally:
        p.stop()

    # 5. Inline frame overflow and lowered file limit are recoverable.
    p = peer(XU_XACP_SCREENSHOT_MAX_BYTES="1024")
    try:
        p.request(hello(), 1)
        shot(p, 2, "\n  scale: !f 4.0", "screenshot_too_large")
        shot(p, 3, "\n  mode: file", "screenshot_too_large")
        shot(p, 4, "\n  scale: !f 0.1")
        p.finish()
    finally:
        p.stop()

    # 6. Unsafe directories: both shared parent and process directory, plus
    # symlink refusal. Owner mismatch follows the same native fstat gate.
    for unsafe in ("parent", "pid", "symlink"):
        p = peer()
        try:
            p.request(hello(), 1)
            pid = int(scalar(p.request(frame(2, "proc.status"), 2), "pid"))
            parent = runtime / "xacp"
            parent.mkdir(mode=0o700, exist_ok=True)
            directory = parent / str(pid)
            if unsafe == "parent":
                parent.chmod(0o777)
            elif unsafe == "pid":
                directory.mkdir(mode=0o777)
                directory.chmod(0o777)
            else:
                directory.symlink_to(runtime, target_is_directory=True)
            response = shot(p, 3, "\n  mode: file", "file_unavailable")
            assert str(runtime) not in response
            p.request(frame(4, "proc.status"), 4)
            p.finish()
        finally:
            p.stop()
            parent.chmod(0o700)
            if directory.is_symlink():
                directory.unlink()
            elif directory.exists():
                directory.rmdir()

    # 7. UTF-8 truncation, no absolute paths in tree or error messages, and
    # idle/session cleanup. Original transport/schema smoke runs in xacp-test.
    p = peer()
    try:
        p.request(hello(), 1)
        value = "a" * 255 + "中" * 3
        args = "\n  win: !i 1\n  node: !i 1\n  act: set_text\n  text: " + json.dumps(value, ensure_ascii=False)
        p.request(frame(2, "ui.act", args), 2)
        tree = p.request(frame(3, "ui.tree"), 3)
        assert 'text: "' + "a" * 255 + '"' in tree and "text_truncated: !b true" in tree
        value = "/home/host/private.txt /tmp/image.png $HOME/private C:\\Users\\private"
        args = "\n  win: !i 1\n  node: !i 1\n  act: set_text\n  text: " + json.dumps(value, ensure_ascii=False)
        p.request(frame(4, "ui.act", args), 4)
        tree = p.request(frame(5, "ui.tree"), 5)
        assert all(path not in tree for path in ("/home/", "/tmp/", "$HOME", "C:")), tree
        response = p.request(frame(6, "ui.tree", '\n  "/host/private": !b true'), 6, "schema_error")
        assert "/host/" not in response and "<path>" in response
        p.finish()
    finally:
        p.stop()
    p = Attached(app, launcher, idle_timeout_ms="1000", env_overrides=overrides)
    try:
        p.request(hello(), 1)
        pid = int(scalar(p.request(frame(2, "proc.status"), 2), "pid"))
        response = shot(p, 3, "\n  mode: file")
        path = runtime / "xacp" / str(pid) / scalar(response, "path")
        assert path.exists()
        checked(read_frame(fd_reader(p.child.stdout.fileno(), 5)), 0, "session_idle")
        p.finish()
        assert not path.exists()
    finally:
        p.stop()
    print(f"XACP screenshot smoke ({'stdio' if launcher is None else 'attach'}): PASS (7 groups)")


def main():
    if not sys.platform.startswith("linux"):
        print("XACP screenshot smoke: SKIP (fixture uses Linux Cairo/Pango host)")
        return
    xu = Path(os.environ.get("XU", ROOT / "bin/xu")).resolve()
    tool = xu.with_name("xu-xacp" + xu.suffix)
    with tempfile.TemporaryDirectory(prefix="xu-xacp-screenshot-") as tmp:
        directory = Path(tmp)
        app = build_fixture(xu, directory)
        runtime = directory / "runtime"
        runtime.mkdir(mode=0o700)
        for launcher in (None, tool):
            exercise(app, launcher, runtime)


if __name__ == "__main__":
    main()
