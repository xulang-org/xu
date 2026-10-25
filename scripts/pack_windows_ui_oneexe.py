#!/usr/bin/env python3
"""Build a true single-file Windows UI app (no SFX / no TEMP extract).

Pipeline (same model as macOS pack):
  1. xu --target windows-x64 --emit-obj  →  XUOBJ
  2. xuobj_to_coff_o.py  →  PE-COFF .o  (xu_ui_host_run left undefined)
  3. mingw-g++ -c -DXU_UI_STATIC windows_host.cc → host.o
  4. ar rcs libxu_ui_host.a  →  foreign code as static archive
  5. link coff.o + libxu_ui_host.a + icon + WinMain shim → one GUI PE

Usage (repo root):
  python3 scripts/pack_windows_ui_oneexe.py --app shaped

The packer is a product-lane consumer: it resolves a hosted compiler from
``--xu``/``XU_COMPILER`` (or the product seed resolver) and never builds or
selects the Rust bootstrap primer.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXAMPLES_ROOT = pathlib.Path(os.environ.get("XU_EXAMPLES_ROOT", ROOT.parent / "xu-examples")).expanduser().resolve()
OUT_DIR = ROOT / "dist" / "windows-x64-ui"
ZIP = ROOT / "dist" / "windows-x64-ui.zip"
def mingw_tool(name: str) -> str:
    cross = "x86_64-w64-mingw32-" + name
    return shutil.which(cross) or (shutil.which(name) if os.name == "nt" else None) or cross


CXX = mingw_tool("g++")
AR = mingw_tool("ar")
GCC = mingw_tool("gcc")
WINDRES = mingw_tool("windres")
HOST_SEED_RESOLVER = ROOT / "scripts" / "xu_host_seed.sh"
PRODUCT_COMPILER_RUNNER = ROOT / "scripts" / "run_product_compiler.sh"
XUOBJ_TO_O = ROOT / "scripts" / "xuobj_to_coff_o.py"
AR_HOST = ROOT / "scripts" / "ar_xu_host.py"
sys.path.insert(0, str(ROOT / "scripts"))
from xu_brand import ICON_PNG, brand_www_extras, resolve_project_icon  # noqa: E402

DEFAULT_WWW = EXAMPLES_ROOT / "examples" / "16_ui_webview" / "open" / "www"
WEBVIEW2_VER = "1.0.2903.40"
LOADER_CACHE = OUT_DIR / "_build" / f"WebView2Loader-{WEBVIEW2_VER}-x64.dll"


# Match webview.bridge_script() / windows kXuBridgeJs (fetch invoke; poll 50ms).
XU_BRIDGE_JS = (
    "window.__XU__=window.__XU__||{};"
    "(function(X){"
    "function sc(s){s=String(s==null?'':s);if(!s.length)return '!s ';for(var i=0;i<s.length;i++){var "
    "c=s.charCodeAt(i);if(c===10||c===13||c===9||c===35||c===58||c===32||c===33||c===64||c===36)return "
    "'!s '+s;}return s;}"
    "function enc(n,p){return 'name: '+sc(n)+'\\npayload: '+sc(p)+'\\n';}"
    "function dec(t){var o={};String(t||'').split('\\n').forEach(function(line){var "
    "i=line.indexOf(': ');if(i>0){var k=line.slice(0,i),v=line.slice(i+2);if(v.indexOf('!s ')===0)"
    "v=v.slice(3);o[k]=v;}});return o;}"
    "var B='xu://app/__xu';"
    "X._deliver=function(n,p){var cb=(X._L||{})[n];if(cb)try{cb(p);}catch(e){}};"
    "X.invoke=function(n,p){return fetch(B+'/invoke',{method:'POST',headers:{'Content-Type':'text/xun; "
    "charset=utf-8'},body:enc(n,p)}).then(function(r){return r.text();}).then(function(t){var "
    "o=dec(t);if(o.ok==='false'||o.ok==='0')throw new Error(o.error||'error');"
    "return o.result!=null?o.result:t;});};"
    "X.listen=function(n,cb){(X._L=X._L||{})[n]=cb;};"
    "window.invoke=X.invoke;window.listen=function(n,cb){return X.listen(n,cb);};"
    "async function poll(){try{const t=await fetch(B+'/poll').then(function(r){return r.text();});"
    "if(!t||!t.length)return;const o=dec(t);const n=o.name||'';const p=o.payload!=null?o.payload:'';"
    "const cb=(X._L||{})[n];if(cb)cb(p);}catch(e){}}"
    "setInterval(poll,50);"
    "})(window.__XU__);"
)


def write_blob_c(data: bytes, out_c: pathlib.Path, *, symbol: str, comment: str) -> None:
    parts = [
        f"/* {comment} */\n",
        f"const unsigned char {symbol}[] = {{\n",
    ]
    for i in range(0, len(data), 16):
        chunk = ", ".join(f"0x{b:02x}" for b in data[i : i + 16])
        parts.append(f"  {chunk},\n")
    parts.append("};\n")
    parts.append(f"const unsigned int {symbol}_len = {len(data)};\n")
    out_c.write_text("".join(parts), encoding="utf-8")


def write_icon_blob_c(png: pathlib.Path, out_c: pathlib.Path) -> None:
    write_blob_c(png.read_bytes(), out_c, symbol="xu_pack_icon_png", comment="Embedded brand/xu_app_logo.png")


def build_tray_ico_bytes(png: pathlib.Path, work: pathlib.Path) -> bytes:
    """Build a multi-size .ico (16/32/48/256) for Windows tray + exe/window chrome."""
    ico_candidate = png.with_suffix(".ico")
    if ico_candidate.is_file():
        return ico_candidate.read_bytes()

    try:
        from PIL import Image
        sizes = [16, 32, 48, 256]
        imgs: list[tuple[int, bytes]] = []
        src = Image.open(png).convert("RGBA")
        for s in sizes:
            im = src.resize((s, s), Image.Resampling.LANCZOS)
            buf = pathlib.Path(work) / f"tray_{s}.png"
            im.save(buf, format="PNG")
            imgs.append((s, buf.read_bytes()))

        # ICONDIR + ICONDIRENTRY[n] + PNG payloads (Vista+ PNG-in-ICO).
        count = len(imgs)
        header = struct.pack("<HHH", 0, 1, count)
        entries = bytearray()
        payload = bytearray()
        offset = 6 + 16 * count
        for s, data in imgs:
            w = 0 if s >= 256 else s
            h = 0 if s >= 256 else s
            entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(data), offset)
            payload += data
            offset += len(data)
        return bytes(header) + bytes(entries) + bytes(payload)
    except Exception:
        # Fallback without Pillow: wrap raw PNG into standard Vista+ PNG-in-ICO
        png_bytes = png.read_bytes()
        header = struct.pack("<HHH", 0, 1, 1)
        entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png_bytes), 22)
        return bytes(header) + bytes(entry) + png_bytes


def write_icon_ico_blob_c(png: pathlib.Path, out_c: pathlib.Path, work: pathlib.Path) -> None:
    ico = build_tray_ico_bytes(png, work)
    write_blob_c(ico, out_c, symbol="xu_pack_icon_ico", comment="Embedded brand icon as .ico (Windows tray)")
    (work / "xu_app_icon.ico").write_bytes(ico)


def write_loader_blob_c(dll: pathlib.Path, out_c: pathlib.Path) -> None:
    write_blob_c(
        dll.read_bytes(),
        out_c,
        symbol="xu_pack_webview2_loader",
        comment="Embedded WebView2Loader.dll (bootstrap only; engine = system Runtime)",
    )

def write_www_blob_c(
    www_dir: pathlib.Path,
    out_c: pathlib.Path,
    extra: list[tuple[str, bytes]] | None = None,
) -> int:
    if not www_dir.is_dir():
        raise SystemExit(f"missing www dir: {www_dir}")
    files: list[tuple[str, bytes]] = []
    for p in sorted(www_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(www_dir).as_posix()
        if ".." in rel.split("/"):
            continue
        files.append((rel, p.read_bytes()))
    if extra:
        files.extend(extra)
    if not files:
        raise SystemExit(f"empty www dir: {www_dir}")
    parts = [
        "/* Embedded #ui/webview www/ static root. */\n",
        "#include <stddef.h>\n",
        "typedef struct { const char *path; const unsigned char *data; unsigned len; } XuWwwFile;\n",
    ]
    for i, (rel, data) in enumerate(files):
        parts.append(f"static const unsigned char xu_www_{i}[] = {{\n")
        for j in range(0, len(data), 16):
            chunk = ", ".join(f"0x{b:02x}" for b in data[j : j + 16])
            parts.append(f"  {chunk},\n")
        parts.append("};\n")
    parts.append("const XuWwwFile xu_pack_www_files[] = {\n")
    for i, (rel, data) in enumerate(files):
        parts.append(f'  {{"{rel}", xu_www_{i}, {len(data)}}},\n')
    parts.append("};\n")
    parts.append(f"const unsigned xu_pack_www_files_count = {len(files)};\n")
    out_c.write_text("".join(parts), encoding="utf-8")
    return len(files)


APPS = {
    "shaped": {
        "xu_src": str(EXAMPLES_ROOT / "examples/16_ui_webview/shaped/main.xu"),
        "out_name": "XuShaped.exe",
        "title": "Xu Shaped Window",
        "need_webview": False,
    },
    "open": {
        "xu_src": str(EXAMPLES_ROOT / "examples/16_ui_webview/open/main.xu"),
        "out_name": "XuOpenWindow.exe",
        "title": "Xu WebView Window",
        "need_webview": True,
    },
}


def _sh_exec(script: pathlib.Path, args: list[str] | None = None) -> list[str]:
    cmd_args = args or []
    if os.name == "nt" or sys.platform == "win32":
        bash = shutil.which("bash") or shutil.which("sh") or "bash"
        return [bash, str(script), *cmd_args]
    return [str(script), *cmd_args]


def resolve_product_xu(requested: pathlib.Path | None) -> pathlib.Path:
    """Resolve a hosted product compiler; never select/build the Rust primer."""
    if not HOST_SEED_RESOLVER.is_file():
        raise SystemExit(
            f"pack_windows: missing executable seed resolver: {HOST_SEED_RESOLVER}"
        )
    raw = requested
    if raw is None:
        env_value = os.environ.get("XU_COMPILER") or os.environ.get("XU")
        raw = pathlib.Path(env_value).expanduser() if env_value else None

    env = os.environ.copy()
    if raw is not None:
        if not raw.is_absolute():
            raw = pathlib.Path.cwd() / raw
        env["XU_SEED"] = str(raw)
    else:
        env.pop("XU_SEED", None)

    proc = subprocess.run(
        _sh_exec(HOST_SEED_RESOLVER),
        cwd=str(ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(
            "pack_windows: no hosted product xu found; "
            "set --xu PATH or XU_COMPILER (Rust bootstrap is not a product fallback)"
        )
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise SystemExit("pack_windows: xu_host_seed returned an invalid compiler path")
    try:
        compiler = pathlib.Path(lines[0]).resolve()
    except (OSError, RuntimeError) as exc:
        raise SystemExit(
            f"pack_windows: cannot canonicalize resolved compiler: {exc}"
        ) from exc
    is_win = os.name == "nt" or sys.platform == "win32"
    if not compiler.is_file() or (not is_win and not os.access(compiler, os.X_OK)):
        raise SystemExit(f"pack_windows: resolved compiler is not executable: {compiler}")
    return compiler


def run_product_compiler(xu: pathlib.Path, args: list[str]) -> None:
    """Compile through the hermetic product wrapper (clears ambient XUPATH/cache)."""
    if not PRODUCT_COMPILER_RUNNER.is_file():
        raise SystemExit(
            f"pack_windows: missing product compiler wrapper: {PRODUCT_COMPILER_RUNNER}"
        )
    subprocess.check_call(
        _sh_exec(PRODUCT_COMPILER_RUNNER, [str(xu), *args]),
        cwd=str(ROOT),
    )


def ensure_webview2_loader() -> pathlib.Path:
    """Fetch Microsoft.Web.WebView2 nupkg and cache x64 WebView2Loader.dll."""
    import io
    import urllib.request
    import zipfile

    LOADER_CACHE.parent.mkdir(parents=True, exist_ok=True)
    if LOADER_CACHE.is_file() and LOADER_CACHE.stat().st_size > 1000:
        return LOADER_CACHE
    url = f"https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/{WEBVIEW2_VER}"
    print("fetch WebView2Loader:", url)
    req = urllib.request.Request(url, headers={"User-Agent": "xu-pack"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        cands = [
            n
            for n in zf.namelist()
            if n.endswith("WebView2Loader.dll") and ("x64" in n or "win-x64" in n)
        ]
        if not cands:
            raise SystemExit("WebView2 nupkg: no x64 WebView2Loader.dll")
        cands.sort(key=lambda n: (0 if "build/native/x64" in n else 1, n))
        LOADER_CACHE.write_bytes(zf.read(cands[0]))
        print("cached", LOADER_CACHE, "from", cands[0], LOADER_CACHE.stat().st_size)
    return LOADER_CACHE


def build_host_objects(*, with_webview: bool, td: pathlib.Path) -> list[pathlib.Path]:
    stub = td / "webview_stub.cc"
    stub.write_text(
        '#include "xu_content_abi.h"\n'
        "extern \"C\" const XuContentVTable *xu_webview_plugin_vtable(void) { return nullptr; }\n",
        encoding="utf-8",
    )
    host_o = td / "windows_host.o"
    stub_o = td / "webview_stub.o"
    common = [
        CXX,
        "-O2",
        "-std=c++17",
        "-c",
        "-DXU_UI_STATIC",
        # MinGW frames can leave RSP 8-mod-16; GCC then emits movaps for
        # ZeroMemory/WNDCLASS and AVs (0xC0000005) on Windows.
        "-mstackrealign",
        "-Isrc/ui/host",
    ]
    subprocess.check_call(
        [*common, "src/ui/host/windows_host.cc", "-o", str(host_o)],
        cwd=str(ROOT),
    )
    assets_o = td / "xu_pack_assets.o"
    assets_weak_o = td / "xu_pack_assets_weak.o"
    for src, dst in (
        ("src/ui/host/xu_pack_assets.c", assets_o),
        ("src/ui/host/xu_pack_assets_weak.c", assets_weak_o),
    ):
        subprocess.check_call(
            [
                GCC,
                "-O2",
                "-c",
                "-Isrc/ui/host",
                src,
                "-o",
                str(dst),
            ],
            cwd=str(ROOT),
        )
    objs = [host_o, assets_o, assets_weak_o]
    draw_o = td / "windows_draw.o"
    subprocess.check_call(
        [*common, "src/ui/host/windows_draw.cc", "-o", str(draw_o)], cwd=str(ROOT)
    )
    objs.append(draw_o)
    mem_o = td / "xu_ui_mem.o"
    subprocess.check_call(
        [
            CXX,
            "-O2",
            "-std=c++17",
            "-c",
            "-DXU_UI_STATIC",
            "-mstackrealign",
            "-Isrc/ui/host",
            "src/ui/host/xu_ui_mem.cc",
            "-o",
            str(mem_o),
        ],
        cwd=str(ROOT),
    )
    objs.append(mem_o)
    # Always pull string COMDAT helper (shim calls xu_force_cxx_string_syms).
    str_o = td / "cxx_string_force.o"
    subprocess.check_call(
        [
            CXX,
            "-O2",
            "-std=c++17",
            "-c",
            "src/ui/host/cxx_string_force.cc",
            "-o",
            str(str_o),
        ],
        cwd=str(ROOT),
    )
    objs.append(str_o)
    if with_webview:
        wv_o = td / "windows_webview.o"
        subprocess.check_call(
            [*common, "src/ui/host/windows_webview.cc", "-o", str(wv_o)],
            cwd=str(ROOT),
        )
        objs.append(wv_o)
    else:
        subprocess.check_call([*common, str(stub), "-o", str(stub_o)], cwd=str(ROOT))
        objs.append(stub_o)
    return objs


def link_static(
    xu_o: pathlib.Path,
    objs: list[pathlib.Path],
    out_exe: pathlib.Path,
    www: pathlib.Path | None = None,
    *,
    loader: pathlib.Path | None = None,
    console: bool = False,
    icon_png: pathlib.Path | None = None,
    xu_src: pathlib.Path | None = None,
    with_webview: bool = True,
) -> None:
    icon = icon_png if icon_png is not None else ICON_PNG
    if not icon.is_file():
        raise SystemExit(f"missing icon: {icon}")

    with tempfile.TemporaryDirectory() as td0:
        td = pathlib.Path(td0)
        icon_c = td / "icon_blob.c"
        write_icon_blob_c(icon, icon_c)
        icon_o = td / "icon_blob.o"
        subprocess.check_call(
            [GCC, "-O2", "-c", str(icon_c), "-o", str(icon_o)],
        )
        icon_ico_c = td / "icon_ico_blob.c"
        write_icon_ico_blob_c(icon, icon_ico_c, td)
        icon_ico_o = td / "icon_ico_blob.o"
        subprocess.check_call(
            [GCC, "-O2", "-c", str(icon_ico_c), "-o", str(icon_ico_o)],
        )
        ico_path = td / "xu_app_icon.ico"
        print(f"embed tray .ico ({ico_path.stat().st_size} bytes)")
        # PE resource so Explorer / taskbar / Alt-Tab show the app icon on the .exe.
        rc_path = td / "xu_app.rc"
        rc_path.write_text(
            "/* Windows app icon resource (must match IDI_XUAPP in windows_host.cc). */\n"
            "#define IDI_XUAPP 101\n"
            'IDI_XUAPP ICON "xu_app_icon.ico"\n',
            encoding="utf-8",
        )
        if xu_src is not None and xu_src.resolve().parent == (ROOT / "src/cmd/setup").resolve():
            manifest = td / "xu_setup.manifest"
            manifest.write_text(
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">'
                '<trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges>'
                '<requestedExecutionLevel level="asInvoker" uiAccess="false"/>'
                '</requestedPrivileges></security></trustInfo></assembly>', encoding="utf-8")
            rc_path.write_text(rc_path.read_text(encoding="utf-8") + '1 24 "xu_setup.manifest"\n', encoding="utf-8")
        icon_res_o = td / "xu_app_res.o"
        subprocess.check_call(
            [
                WINDRES,
                "-i",
                str(rc_path),
                "-o",
                str(icon_res_o),
                "--input-format=rc",
                "--output-format=coff",
            ],
            cwd=str(td),
        )
        print("embed PE ICON resource (IDI_XUAPP=101)")

        loader_o = None
        loader_extern = ""
        loader_helpers = ""
        loader_setup = ""
        if loader is not None:
            loader_c = td / "loader_blob.c"
            write_loader_blob_c(loader, loader_c)
            loader_o = td / "loader_blob.o"
            subprocess.check_call(
                [GCC, "-O2", "-c", str(loader_c), "-o", str(loader_o)],
            )
            print(f"embed WebView2Loader.dll ({loader.stat().st_size} bytes) → beside exe only")
            loader_extern = (
                "extern const unsigned char xu_pack_webview2_loader[];\n"
                "extern const unsigned int xu_pack_webview2_loader_len;\n"
            )
            loader_helpers = (
                "static int write_loader_to(const char *dir) {\n"
                "  char path[MAX_PATH];\n"
                "  WIN32_FILE_ATTRIBUTE_DATA fad;\n"
                "  if (!dir || !dir[0]) return 0;\n"
                '  snprintf(path, MAX_PATH, "%s\\\\WebView2Loader.dll", dir);\n'
                "  if (GetFileAttributesExA(path, GetFileExInfoStandard, &fad) &&\n"
                "      fad.nFileSizeHigh == 0 &&\n"
                "      fad.nFileSizeLow == xu_pack_webview2_loader_len) {\n"
                "    return 1;\n"
                "  }\n"
                "  return write_bytes(path, xu_pack_webview2_loader, xu_pack_webview2_loader_len);\n"
                "}\n"
                "static int write_loader_beside_exe(void) {\n"
                "  char path[MAX_PATH];\n"
                "  char *slash;\n"
                "  DWORD n = GetModuleFileNameA(NULL, path, MAX_PATH);\n"
                "  if (n == 0 || n >= MAX_PATH) return 0;\n"
                "  slash = strrchr(path, '\\\\');\n"
                "  if (!slash) slash = strrchr(path, '/');\n"
                "  if (!slash) return 0;\n"
                "  *slash = 0;\n"
                "  return write_loader_to(path);\n"
                "}\n"
            )
            # Beside the exe only — never create %TEMP%\xu_ui_*.
            loader_setup = (
                "  if (!write_loader_beside_exe()) return 0;\n"
                '  log_line("WebView2Loader beside exe");\n'
            )

        www_o = None
        if www is not None:
            www_c = td / "www_blob.c"
            extra = brand_www_extras(xu_src if xu_src is not None else icon, icon) if with_webview else []
            if with_webview:
                extra.append(("__xu/bridge.js", XU_BRIDGE_JS.encode("utf-8")))
            n = write_www_blob_c(www, www_c, extra=extra)
            www_o = td / "www_blob.o"
            subprocess.check_call(
                [GCC, "-O2", "-c", str(www_c), "-o", str(www_o)],
            )
            print(f"www: embed {n} files from {www} (in-memory xu://; no TEMP extract)")
        else:
            # Strong empty www table (PE archive won't pull weak.o for undef refs).
            www_c = td / "www_blob_empty.c"
            www_c.write_text(
                "typedef struct { const char *path; const unsigned char *data; unsigned len; } XuWwwFile;\n"
                "const XuWwwFile xu_pack_www_files[] = {{0, 0, 0}};\n"
                "const unsigned xu_pack_www_files_count = 0;\n",
                encoding="utf-8",
            )
            www_o = td / "www_blob_empty.o"
            subprocess.check_call(
                [GCC, "-O2", "-c", str(www_c), "-o", str(www_o)],
            )

        host_a = td / "libxu_ui_host.a"
        subprocess.check_call(
            [
                sys.executable,
                str(AR_HOST),
                "--ar",
                AR,
                "-o",
                str(host_a),
                *[str(o) for o in objs],
            ],
            cwd=str(ROOT),
        )

        # UI apps: PE subsystem WINDOWS (-mwindows) + WinMain — no console flash.
        # --console / XU_UI_CONSOLE=1: AllocConsole so println is visible while debugging.
        shim = td / "winmain_shim.c"
        shim.write_text(
            "/* Pack entry: embed icon + www + WebView2Loader, then Xu xu_app_start. */\n"
            "#define WIN32_LEAN_AND_MEAN\n"
            "#include <stdio.h>\n"
            "#include <string.h>\n"
            "#include <stdint.h>\n"
            "#include <windows.h>\n"
            "#include \"xu_ui_mem.h\"\n#include \"xu_pack_assets.h\"\n#include \"xu_ui_text.h\"\n"
            "\n"
            "typedef void (WINAPI *ExitProcessFn)(UINT);\n"
            "\n"
            "extern const unsigned char xu_pack_icon_png[];\n"
            "extern const unsigned int xu_pack_icon_png_len;\n"
            + loader_extern
            + "\n"
            "static int write_bytes(const char *path, const void *data, DWORD n) {\n"
            "  HANDLE h = CreateFileA(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS,\n"
            "                         FILE_ATTRIBUTE_NORMAL, NULL);\n"
            "  if (h == INVALID_HANDLE_VALUE) return 0;\n"
            "  DWORD w = 0;\n"
            "  BOOL ok = WriteFile(h, data, n, &w, NULL);\n"
            "  CloseHandle(h);\n"
            "  return ok && w == n;\n"
            "}\n"
            "\n"
            + loader_helpers
            +             "static char g_log_path[MAX_PATH];\n"
            "static char g_trace_path[MAX_PATH];\n"
            "static HANDLE g_log_std = INVALID_HANDLE_VALUE;\n"
            "static DWORD g_main_tid = 0;\n"
            "static CRITICAL_SECTION g_log_cs;\n"
            "static int g_log_cs_ready = 0;\n"
            "\n"
            "static void log_write_raw(const char *s, DWORD n) {\n"
            "  DWORD w = 0;\n"
            "  if (!s || !n) return;\n"
            "  if (g_log_cs_ready) EnterCriticalSection(&g_log_cs);\n"
            "  if (g_log_std != INVALID_HANDLE_VALUE) {\n"
            "    WriteFile(g_log_std, s, n, &w, NULL);\n"
            "    WriteFile(g_log_std, \"\\r\\n\", 2, &w, NULL);\n"
            "    FlushFileBuffers(g_log_std);\n"
            "  } else if (g_log_path[0]) {\n"
            "    HANDLE h = CreateFileA(g_log_path, FILE_APPEND_DATA,\n"
            "                          FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,\n"
            "                          OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);\n"
            "    if (h != INVALID_HANDLE_VALUE) {\n"
            "      WriteFile(h, s, n, &w, NULL);\n"
            "      WriteFile(h, \"\\r\\n\", 2, &w, NULL);\n"
            "      CloseHandle(h);\n"
            "    }\n"
            "  }\n"
            "  if (g_log_cs_ready) LeaveCriticalSection(&g_log_cs);\n"
            "}\n"
            "\n"
            "/* Xu Write/fail-loud uses GetStdHandle — GUI PE has none unless we bind. */\n"
            "static void bind_xu_stdio_to_log(void) {\n"
            "  if (!g_log_path[0]) return;\n"
            "  if (!g_log_cs_ready) {\n"
            "    InitializeCriticalSection(&g_log_cs);\n"
            "    g_log_cs_ready = 1;\n"
            "  }\n"
            "  g_log_std = CreateFileA(g_log_path, GENERIC_WRITE,\n"
            "                         FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,\n"
            "                         OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);\n"
            "  if (g_log_std == INVALID_HANDLE_VALUE) return;\n"
            "  SetFilePointer(g_log_std, 0, NULL, FILE_END);\n"
            "  SetStdHandle(STD_OUTPUT_HANDLE, g_log_std);\n"
            "  SetStdHandle(STD_ERROR_HANDLE, g_log_std);\n"
            "}\n"
            "\n"
            "static void log_line(const char *s) {\n"
            "  if (!s) return;\n"
            "  log_write_raw(s, (DWORD)strlen(s));\n"
            "  fprintf(stderr, \"%s\\n\", s);\n"
            "  fflush(stderr);\n"
            "}\n"
            "\n"
            "static void init_log_path(void) {\n"
            "  char exe[MAX_PATH];\n"
            "  char *slash;\n"
            "  char *dot;\n"
            "  DWORD n = GetModuleFileNameA(NULL, exe, MAX_PATH);\n"
            "  g_log_path[0] = 0;\n"
            "  g_trace_path[0] = 0;\n"
            "  if (n == 0 || n >= MAX_PATH) {\n"
            "    GetTempPathA(MAX_PATH, g_log_path);\n"
            "    strcat(g_log_path, \"xu_ui.log\");\n"
            "    snprintf(g_trace_path, MAX_PATH, \"%s.trace.txt\", g_log_path);\n"
            "    DeleteFileA(g_log_path);\n"
            "    DeleteFileA(g_trace_path);\n"
            "    SetEnvironmentVariableA(\"XU_PACK_TRACE\", g_trace_path);\n"
            "    SetEnvironmentVariableA(\"XU_UI_LOG\", g_log_path);\n"
            "    return;\n"
            "  }\n"
            "  slash = strrchr(exe, '\\\\');\n"
            "  if (!slash) slash = strrchr(exe, '/');\n"
            "  snprintf(g_log_path, MAX_PATH, \"%s\", exe);\n"
            "  dot = strrchr(g_log_path, '.');\n"
            "  if (dot && _stricmp(dot, \".exe\") == 0) strcpy(dot, \".log\");\n"
            "  else strcat(g_log_path, \".log\");\n"
            "  snprintf(g_trace_path, MAX_PATH, \"%s\", exe);\n"
            "  dot = strrchr(g_trace_path, '.');\n"
            "  if (dot && _stricmp(dot, \".exe\") == 0) strcpy(dot, \".trace.txt\");\n"
            "  else strcat(g_trace_path, \".trace.txt\");\n"
            "  DeleteFileA(g_log_path);\n"
            "  DeleteFileA(g_trace_path);\n"
            "  SetEnvironmentVariableA(\"XU_PACK_TRACE\", g_trace_path);\n"
            "  SetEnvironmentVariableA(\"XU_UI_LOG\", g_log_path);\n"
            "}\n"
            "\n"
            "static LONG WINAPI xu_veh(EXCEPTION_POINTERS *ep) {\n"
            "  char msg[768];\n"
            "  unsigned long code = 0;\n"
            "  void *addr = NULL;\n"
            "  void *rip = NULL;\n"
            "  void *rsp = NULL;\n"
            "  void *rax = NULL;\n"
            "  void *rcx = NULL;\n"
            "  void *rdx = NULL;\n"
            "  void *r8 = NULL;\n"
            "  void *r9 = NULL;\n"
            "  void *s0 = NULL;\n"
            "  void *s1 = NULL;\n"
            "  void *s2 = NULL;\n"
            "  void *s3 = NULL;\n"
            "  if (ep && ep->ExceptionRecord) {\n"
            "    code = (unsigned long)ep->ExceptionRecord->ExceptionCode;\n"
            "    addr = ep->ExceptionRecord->ExceptionAddress;\n"
            "  }\n"
            "  /* OutputDebugString raises DBG_PRINTEXCEPTION_* — not a crash. */\n"
            "  if (code == 0x40010006UL || code == 0x4001000AUL)\n"
            "    return EXCEPTION_CONTINUE_SEARCH;\n"
            "  if (ep && ep->ContextRecord) {\n"
            "    rip = (void *)(uintptr_t)ep->ContextRecord->Rip;\n"
            "    rsp = (void *)(uintptr_t)ep->ContextRecord->Rsp;\n"
            "    rax = (void *)(uintptr_t)ep->ContextRecord->Rax;\n"
            "    rcx = (void *)(uintptr_t)ep->ContextRecord->Rcx;\n"
            "    rdx = (void *)(uintptr_t)ep->ContextRecord->Rdx;\n"
            "    r8 = (void *)(uintptr_t)ep->ContextRecord->R8;\n"
            "    r9 = (void *)(uintptr_t)ep->ContextRecord->R9;\n"
            "    if (rsp) {\n"
            "      s0 = ((void **)rsp)[0];\n"
            "      s1 = ((void **)rsp)[1];\n"
            "      s2 = ((void **)rsp)[2];\n"
            "      s3 = ((void **)rsp)[3];\n"
            "    }\n"
            "  }\n"
            "  snprintf(msg, sizeof(msg),\n"
            "           \"VEH exception 0x%08lX at %p rip=%p rsp=%p\\r\\n\"\n"
            "           \"  rax=%p rcx=%p rdx=%p r8=%p r9=%p\\r\\n\"\n"
            "           \"  stack %p %p %p %p\",\n"
            "           code, addr, rip, rsp, rax, rcx, rdx, r8, r9, s0, s1, s2, s3);\n"
            "  log_line(msg);\n"
            "  return EXCEPTION_CONTINUE_SEARCH;\n"
            "}\n"
            "\n"
            "static LONG WINAPI xu_unhandled(EXCEPTION_POINTERS *ep) {\n"
            "  char msg[384];\n"
            "  unsigned long code = 0;\n"
            "  void *addr = NULL;\n"
            "  if (ep && ep->ExceptionRecord) {\n"
            "    code = (unsigned long)ep->ExceptionRecord->ExceptionCode;\n"
            "    addr = ep->ExceptionRecord->ExceptionAddress;\n"
            "  }\n"
            "  snprintf(msg, sizeof(msg),\n"
            "           \"Xu crashed (exception 0x%08lX at %p).\\r\\nSee .log / .trace.txt next to exe.\",\n"
            "           code, addr);\n"
            "  log_line(msg);\n"
            "  /* No MessageBox: debug-only; set XU_UI_DEBUG=1 to alert. */\n"
            "  {\n"
            "    char dbg[8];\n"
            "    if (GetEnvironmentVariableA(\"XU_UI_DEBUG\", dbg, sizeof(dbg)) > 0 && dbg[0] == '1')\n"
            "      MessageBoxA(NULL, msg, \"Xu\", MB_OK | MB_ICONERROR);\n"
            "  }\n"
            "  return EXCEPTION_EXECUTE_HANDLER;\n"
            "}\n"
            "\n"
            "static ExitProcessFn g_real_ExitProcess = NULL;\n"
            "\n"
            "static void WINAPI hooked_ExitProcess(UINT code) {\n"
            "  char msg[320];\n"
            "  char work[MAX_PATH];\n"
            "  DWORD tid = GetCurrentThreadId();\n"
            "  snprintf(msg, sizeof(msg),\n"
            "           \"ExitProcess(%u) tid=%lu main=%lu%s\",\n"
            "           (unsigned)code, (unsigned long)tid, (unsigned long)g_main_tid,\n"
            "           (tid == g_main_tid) ? \" (main)\" : \" (worker)\");\n"
            "  log_line(msg);\n"
            "  if (GetEnvironmentVariableA(\"XU_UI_TMP\", work, MAX_PATH) > 0) {\n"
            "    char tp[MAX_PATH];\n"
            "    FILE *f;\n"
            "    char line[256];\n"
            "    snprintf(tp, MAX_PATH, \"%s\\\\xu_main_trace.txt\", work);\n"
            "    f = fopen(tp, \"r\");\n"
            "    if (f) {\n"
            "      log_line(\"--- xu_main_trace ---\");\n"
            "      while (fgets(line, sizeof(line), f)) {\n"
            "        size_t L = strlen(line);\n"
            "        while (L > 0 && (line[L-1]=='\\n' || line[L-1]=='\\r')) line[--L]=0;\n"
            "        if (line[0]) log_line(line);\n"
            "      }\n"
            "      fclose(f);\n"
            "    }\n"
            "    snprintf(tp, MAX_PATH, \"%s\\\\xu_host_trace.txt\", work);\n"
            "    f = fopen(tp, \"r\");\n"
            "    if (f) {\n"
            "      log_line(\"--- xu_host_trace ---\");\n"
            "      while (fgets(line, sizeof(line), f)) {\n"
            "        size_t L = strlen(line);\n"
            "        while (L > 0 && (line[L-1]=='\\n' || line[L-1]=='\\r')) line[--L]=0;\n"
            "        if (line[0]) log_line(line);\n"
            "      }\n"
            "      fclose(f);\n"
            "    }\n"
            "    snprintf(tp, MAX_PATH, \"%s\\\\xu_worker_trace.txt\", work);\n"
            "    f = fopen(tp, \"r\");\n"
            "    if (f) {\n"
            "      log_line(\"--- xu_worker_trace ---\");\n"
            "      while (fgets(line, sizeof(line), f)) {\n"
            "        size_t L = strlen(line);\n"
            "        while (L > 0 && (line[L-1]=='\\n' || line[L-1]=='\\r')) line[--L]=0;\n"
            "        if (line[0]) log_line(line);\n"
            "      }\n"
            "      fclose(f);\n"
            "    }\n"
            "  }\n"
            "  if (code != 0) {\n"
            "    char dbg[8];\n"
            "    if (GetEnvironmentVariableA(\"XU_UI_DEBUG\", dbg, sizeof(dbg)) > 0 && dbg[0] == '1') {\n"
            "      snprintf(msg, sizeof(msg),\n"
            "               \"Xu exited with code %u.\\r\\n\"\n"
            "               \"See XuOpenWindow.log beside the exe\",\n"
            "               (unsigned)code);\n"
            "      MessageBoxA(NULL, msg, \"Xu\", MB_OK | MB_ICONERROR);\n"
            "    }\n"
            "  }\n"
            "  if (g_real_ExitProcess) g_real_ExitProcess(code);\n"
            "}\n"
            "\n"
            "static void hook_exit_process(void) {\n"
            "  HMODULE base = GetModuleHandleA(NULL);\n"
            "  IMAGE_DOS_HEADER *dos;\n"
            "  IMAGE_NT_HEADERS *nt;\n"
            "  IMAGE_IMPORT_DESCRIPTOR *imp;\n"
            "  if (!base) return;\n"
            "  dos = (IMAGE_DOS_HEADER *)base;\n"
            "  if (dos->e_magic != IMAGE_DOS_SIGNATURE) return;\n"
            "  nt = (IMAGE_NT_HEADERS *)((char *)base + dos->e_lfanew);\n"
            "  if (nt->Signature != IMAGE_NT_SIGNATURE) return;\n"
            "  if (!nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress) return;\n"
            "  imp = (IMAGE_IMPORT_DESCRIPTOR *)((char *)base +\n"
            "        nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress);\n"
            "  for (; imp->Name; imp++) {\n"
            "    char *dll = (char *)base + imp->Name;\n"
            "    IMAGE_THUNK_DATA *thunk;\n"
            "    IMAGE_THUNK_DATA *orig;\n"
            "    if (!dll) continue;\n"
            "    if (_stricmp(dll, \"KERNEL32.dll\") != 0 && _stricmp(dll, \"kernel32.dll\") != 0) continue;\n"
            "    if (!imp->OriginalFirstThunk || !imp->FirstThunk) continue;\n"
            "    thunk = (IMAGE_THUNK_DATA *)((char *)base + imp->FirstThunk);\n"
            "    orig = (IMAGE_THUNK_DATA *)((char *)base + imp->OriginalFirstThunk);\n"
            "    for (; thunk->u1.Function; thunk++, orig++) {\n"
            "      IMAGE_IMPORT_BY_NAME *nm;\n"
            "      DWORD old = 0;\n"
            "      if (orig->u1.Ordinal & IMAGE_ORDINAL_FLAG) continue;\n"
            "      nm = (IMAGE_IMPORT_BY_NAME *)((char *)base + (DWORD)orig->u1.AddressOfData);\n"
            "      if (!nm || strcmp(nm->Name, \"ExitProcess\") != 0) continue;\n"
            "      g_real_ExitProcess = (ExitProcessFn)(uintptr_t)thunk->u1.Function;\n"
            "      if (!VirtualProtect(&thunk->u1.Function, sizeof(void *), PAGE_READWRITE, &old))\n"
            "        return;\n"
            "      thunk->u1.Function = (ULONGLONG)(uintptr_t)hooked_ExitProcess;\n"
            "      VirtualProtect(&thunk->u1.Function, sizeof(void *), old, &old);\n"
            "      log_line(\"hooked ExitProcess\");\n"
            "      return;\n"
            "    }\n"
            "  }\n"
            "  log_line(\"ExitProcess hook missed\");\n"
            "}\n"
            "\n"
            "static void maybe_alloc_console(void) {\n"
            "  char buf[8];\n"
            "  DWORD n = GetEnvironmentVariableA(\"XU_UI_CONSOLE\", buf, sizeof(buf));\n"
            f"  int want = {(1 if console else 0)};\n"
            "  if (n > 0 && buf[0] == '1') want = 1;\n"
            "  {\n"
            "    const char *cl = GetCommandLineA();\n"
            "    if (cl && strstr(cl, \"--console\")) want = 1;\n"
            "  }\n"
            "  if (!want) return;\n"
            "  /* Never AttachConsole(parent): attaching then crashing can kill PowerShell's window. */\n"
            "  FreeConsole();\n"
            "  if (!AllocConsole()) {\n"
            "    log_line(\"AllocConsole failed\");\n"
            "    return;\n"
            "  }\n"
            "  SetConsoleTitleA(\"Xu UI debug console\");\n"
            "  freopen(\"CONOUT$\", \"w\", stdout);\n"
            "  freopen(\"CONOUT$\", \"w\", stderr);\n"
            "  freopen(\"CONIN$\", \"r\", stdin);\n"
            "  /* Keep Xu GetStdHandle → log file (CRT stderr is console). */\n"
            "  if (g_log_std != INVALID_HANDLE_VALUE) {\n"
            "    SetStdHandle(STD_OUTPUT_HANDLE, g_log_std);\n"
            "    SetStdHandle(STD_ERROR_HANDLE, g_log_std);\n"
            "  }\n"
            "}\n"
            "\n"
            "static int xu_pack_setup(void) {\n"
            "  xu_ui_set_asset_reader(xu_pack_asset_ptr);\n  xu_draw_text_init();\n"
            "  char exe_dir[MAX_PATH];\n"
            "  char line[640];\n"
            "  char *slash;\n"
            "  DWORD n;\n"
            "  /* No %TEMP%\\\\xu_ui_* workdir — mailbox is in-process (:xu: / xu_ui_mem). */\n"
            '  SetEnvironmentVariableA("XU_UI_TMP", "");\n'
            '  SetEnvironmentVariableA("XU_UI_PACK", "1");\n'
            '  SetEnvironmentVariableA("XU_UI_WWW", ":mem:");\n'
            + loader_setup
            + "  n = GetModuleFileNameA(NULL, exe_dir, MAX_PATH);\n"
            "  if (n > 0 && n < MAX_PATH) {\n"
            "    slash = strrchr(exe_dir, '\\\\');\n"
            "    if (!slash) slash = strrchr(exe_dir, '/');\n"
            "    if (slash) {\n"
            "      *slash = 0;\n"
            "      SetCurrentDirectoryA(exe_dir);\n"
            "    }\n"
            "  }\n"
            '  snprintf(line, sizeof(line), "cwd pack (no xu_ui TEMP dir)");\n'
            "  log_line(line);\n"
            '  log_line("www=:mem: icon=:pack: bridge=:pack: mailbox=:xu:");\n'
            "  return 1;\n"
            "}\n"
            "\n"
            "int WINAPI WinMain(HINSTANCE a, HINSTANCE b, LPSTR c, int d) {\n"
            "  (void)a; (void)b; (void)c; (void)d;\n"
            "  g_main_tid = GetCurrentThreadId();\n"
            "  init_log_path();\n"
            "  bind_xu_stdio_to_log();\n"
            "  AddVectoredExceptionHandler(1, xu_veh);\n"
            "  SetUnhandledExceptionFilter(xu_unhandled);\n"
            "  log_line(\"WinMain begin\");\n"
            "  maybe_alloc_console();\n"
            "  if (!xu_pack_setup()) {\n"
            "    log_line(\"pack setup failed\");\n"
            '    MessageBoxA(NULL, "pack setup failed (WebView2Loader beside exe)", "Xu", MB_OK | MB_ICONERROR);\n'
            "    return 1;\n"
            "  }\n"
            "  hook_exit_process();\n"
            "  /* UI/COM must run on this thread (not a worker). */\n"
            "  /* Skip xu_app_start (bundled _start): step Xu inits so .log shows the crash site. */\n"
            "  {\n"
            "    extern void xu_force_cxx_string_syms(void);\n"
            "    extern void _rt_collect_args(void);\n"
            "    extern void _rt_xu_mark(void);\n"
            "    extern void _rt_collect_env(void);\n"
            "    extern void _rt_win_sysinfo(void);\n"
            "    extern int _xu_main(void);\n"
            "    char *cmdline;\n"
            "    int rc;\n"
            "    log_line(\"before xu_force_cxx_string_syms\");\n"
            "    xu_force_cxx_string_syms();\n"
            "    log_line(\"after xu_force_cxx_string_syms\");\n"
            "    cmdline = GetCommandLineA();\n"
            "    log_line(\"GetCommandLineA ok\");\n"
            "    /* Xu windows-x64 helpers use SysV A0=rdi (not Win64 rcx). */\n"
            "    __asm__ __volatile__(\n"
            "      \"mov %[cl], %%rdi\\n\\t\"\n"
            "      \"call _rt_collect_args\\n\\t\"\n"
            "      :\n"
            "      : [cl] \"r\" (cmdline)\n"
            "      : \"rax\", \"rcx\", \"rdx\", \"rsi\", \"rdi\", \"r8\", \"r9\", \"r10\", \"r11\",\n"
            "        \"xmm0\", \"xmm1\", \"xmm2\", \"xmm3\", \"xmm4\", \"xmm5\", \"memory\");\n"
            "    log_line(\"after _rt_collect_args\");\n"
            "    _rt_xu_mark();\n"
            "    log_line(\"after _rt_xu_mark\");\n"
            "    _rt_collect_env();\n"
            "    log_line(\"after _rt_collect_env\");\n"
            "    _rt_win_sysinfo();\n"
            "    log_line(\"after _rt_win_sysinfo\");\n"
            "    log_line(\"calling _xu_main\");\n"
            "    /* Realign RSP: Win64 → SysV/SSE (movaps) in host/webview. */\n"
            "    __asm__ __volatile__(\n"
            "      \"push %%rbp\\n\\t\"\n"
            "      \"mov %%rsp, %%rbp\\n\\t\"\n"
            "      \"and $~15, %%rsp\\n\\t\"\n"
            "      \"sub $32, %%rsp\\n\\t\"\n"
            "      \"call _xu_main\\n\\t\"\n"
            "      \"mov %%rbp, %%rsp\\n\\t\"\n"
            "      \"pop %%rbp\\n\\t\"\n"
            "      \"mov %%eax, %[rc]\\n\\t\"\n"
            "      : [rc] \"=r\" (rc)\n"
            "      :\n"
            "      : \"rax\", \"rcx\", \"rdx\", \"rsi\", \"rdi\", \"r8\", \"r9\", \"r10\", \"r11\",\n"
            "        \"xmm0\", \"xmm1\", \"xmm2\", \"xmm3\", \"xmm4\", \"xmm5\", \"memory\");\n"
            "    {\n"
            "      char m[64];\n"
            "      snprintf(m, sizeof(m), \"_xu_main returned %d\", rc);\n"
            "      log_line(m);\n"
            "    }\n"
            "    if (g_real_ExitProcess) g_real_ExitProcess((UINT)rc);\n"
            "    else ExitProcess((UINT)rc);\n"
            "  }\n"
            "  return 0;\n"
            "}\n",
            encoding="utf-8",
        )
        setup_project = ROOT / "src" / "cmd" / "setup"
        if xu_src is not None and xu_src.resolve().parent == setup_project.resolve():
            startup = setup_project / "windows_startup.h"
            shim_source = shim.read_text(encoding="utf-8")
            shim_source = '#include "' + startup.as_posix() + '"\n' + shim_source
            # The header needs Win32 types before its helper declarations.
            shim_source = '#include <windows.h>\n' + shim_source
            shim_source = shim_source.replace(
                "  g_main_tid = GetCurrentThreadId();",
                "  { int setup_code = xu_setup_startup(); if (setup_code >= 0) return setup_code; }\n"
                "  g_main_tid = GetCurrentThreadId();", 1)
            shim_source = shim_source.replace(
                "    if (g_real_ExitProcess) g_real_ExitProcess((UINT)rc);",
                "    if (rc == 0) xu_setup_notify_environment();\n"
                "    if (g_real_ExitProcess) g_real_ExitProcess((UINT)rc);", 1)
            shim.write_text(shim_source, encoding="utf-8")
        shim_o = td / "winmain_shim.o"
        subprocess.check_call(
            [GCC, "-O2", "-c", "-Isrc/ui/host", str(shim), "-o", str(shim_o)],
        )

        libs = [
            "-luser32",
            "-ladvapi32",
            "-lgdi32",
            "-lgdiplus",
            "-ldwrite",
            "-limm32",
            "-lole32",
            "-lshell32",
            "-luuid",
            "-lcomdlg32",
            "-lshlwapi",
        ]
        if any(o.name == "windows_webview.o" for o in objs):
            libs.insert(libs.index("-lshell32"), "-loleaut32")

        cmd = [
            CXX,
            "-O2",
            str(xu_o),
            # whole-archive: WebView plugin only reached via bootstrap string
            "-Wl,--whole-archive",
            str(host_a),
            "-Wl,--no-whole-archive",
            str(icon_o),
            str(icon_ico_o),
            str(icon_res_o),
            str(shim_o),
            "-o",
            str(out_exe),
            # Always GUI subsystem for UI oneexe (no black console on double-click).
            # Optional console I/O via AllocConsole (--console / XU_UI_CONSOLE=1).
            "-mwindows",
            "-static",
            "-static-libgcc",
            "-static-libstdc++",
            # Force-pull libstdc++ definition if stub is optimized out.
            "-Wl,-u,__cxa_pure_virtual",
            *libs,
        ]
        if any(o.name == "windows_webview.o" for o in objs):
            # Pull cxx_string_force.o; do NOT use -Wl,-u on _M_construct itself —
            # that left a ghost undefined symbol at abs 0 next to a real T definition.
            cmd.extend(["-Wl,-u,xu_force_cxx_string_syms"])
        if loader_o is not None:
            cmd.insert(cmd.index(str(shim_o)) + 1, str(loader_o))
        if www_o is not None:
            cmd.insert(cmd.index(str(shim_o)) + 1, str(www_o))
        subprocess.check_call(cmd, cwd=str(ROOT))
        # Enlarge PE stack (default commit 4KB can crash deep Xu frames on some hosts).
        subprocess.check_call(
            [sys.executable, str(ROOT / "scripts" / "pe_patch_stack.py"), str(out_exe)],
            cwd=str(ROOT),
        )
        print("subsystem: WINDOWS (GUI); console_debug:", "on" if console else "off (XU_UI_CONSOLE=1 or --console)")


def clean_public_dir(keep: set[str]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for p in list(OUT_DIR.iterdir()):
        if p.name in keep or p.name == "_build":
            continue
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            for c in p.rglob("*"):
                if c.is_file():
                    c.unlink()
            for c in sorted(p.rglob("*"), reverse=True):
                if c.is_dir():
                    c.rmdir()
            p.rmdir()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", choices=sorted(APPS), default="shaped")
    ap.add_argument(
        "--src",
        type=pathlib.Path,
        default=None,
        help="arbitrary .xu entry (overrides --app)",
    )
    ap.add_argument("-o", "--output", type=pathlib.Path, default=None)
    ap.add_argument(
        "--www",
        type=pathlib.Path,
        default=None,
        help="static www/ to embed (default: demo www for open)",
    )
    ap.add_argument("--webview", action="store_true", help="force WebView2 host plugin")
    ap.add_argument("--no-webview", action="store_true", help="force shell-only host")
    ap.add_argument("--no-publish", action="store_true", help="build only the requested executable")
    ap.add_argument(
        "--xu",
        dest="xu_compiler",
        type=pathlib.Path,
        default=None,
        help="hosted product Xu compiler (default: XU_COMPILER or product seed resolver)",
    )
    ap.add_argument(
        "--console",
        action="store_true",
        help="enable AllocConsole by default (also: set XU_UI_CONSOLE=1 at runtime)",
    )
    args = ap.parse_args()

    if args.src is not None:
        xu_src = args.src if args.src.is_absolute() else ROOT / args.src
        if xu_src.is_dir() and (xu_src / "main.xu").is_file():
            xu_src = xu_src / "main.xu"
        if not xu_src.is_file():
            raise SystemExit(f"missing --src: {xu_src}")
        if args.no_webview:
            need_webview = False
        elif args.webview:
            need_webview = True
        else:
            text = xu_src.read_text(encoding="utf-8", errors="ignore")
            need_webview = "#ui/webview" in text or "#webview" in text or "webview." in text
        out_name = (args.output.name if args.output else xu_src.stem + ".exe")
        cfg = {
            "xu_src": str(xu_src),
            "out_name": out_name,
            "need_webview": need_webview,
            "title": xu_src.stem,
        }
        www = args.www
        if www is None and need_webview:
            sib = xu_src.parent / "www"
            www = sib if sib.is_dir() else None
    else:
        cfg = dict(APPS[args.app])
        xu_src = ROOT / cfg["xu_src"]
        www = args.www
        if www is None and args.app == "open":
            sib = pathlib.Path(xu_src).parent / "www"
            www = sib if sib.is_dir() else DEFAULT_WWW

    if www is not None and not www.is_absolute():
        www = ROOT / www

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "_build").mkdir(parents=True, exist_ok=True)

    # Resolve the product compiler before any optional network/dependency work;
    # a missing hosted seed must fail in the boundary seam, never after a
    # WebView2 download or an accidental primer build.
    xu = resolve_product_xu(args.xu_compiler)

    loader = None
    if cfg["need_webview"]:
        loader = ensure_webview2_loader()

    with tempfile.TemporaryDirectory(prefix="xu_win_ui_") as td0:
        td = pathlib.Path(td0)
        xuobj = td / "app.xuobj"
        xu_o = td / "app.o"
        run_product_compiler(
            xu,
            [
                "build",
                # A module entry may use sibling files (for example setup's
                # architecture adapters and native SDK downloader).
                str(xu_src.parent if xu_src.name == "main.xu" and (xu_src.parent / "xu.xun").is_file() else xu_src),
                "--target",
                "windows-x64",
                "--emit-obj",
                "-o",
                str(xuobj),
            ],
        )
        subprocess.check_call(
            [sys.executable, str(XUOBJ_TO_O), str(xuobj), str(xu_o)],
            cwd=str(ROOT),
        )
        (OUT_DIR / "_build" / "app.o").write_bytes(xu_o.read_bytes())

        objs = build_host_objects(with_webview=cfg["need_webview"], td=td)
        # Always compile cxxabi stub (resolves __cxa_pure_virtual for MinGW PE).
        cxa_o = td / "cxxabi_stub.o"
        subprocess.check_call(
            [
                CXX,
                "-O2",
                "-std=c++17",
                "-c",
                "src/ui/host/cxxabi_stub.cc",
                "-o",
                str(cxa_o),
            ],
            cwd=str(ROOT),
        )
        objs.append(cxa_o)
        if args.output is not None:
            out_exe = args.output if args.output.is_absolute() else (pathlib.Path.cwd() / args.output)
            if not str(out_exe).lower().endswith(".exe"):
                out_exe = pathlib.Path(str(out_exe) + ".exe")
        else:
            out_exe = OUT_DIR / cfg["out_name"]
        link_static(
            xu_o,
            objs,
            out_exe,
            www=www,
            with_webview=cfg["need_webview"],
            loader=loader,
            console=args.console,
            icon_png=resolve_project_icon(pathlib.Path(xu_src)),
            xu_src=pathlib.Path(xu_src),
        )

    if args.no_publish:
        return

    keep = {cfg["out_name"], "README.txt", "XuShaped.exe", "XuOpenWindow.exe"}
    clean_public_dir(keep=keep)
    # Drop stale side-by-side Loader from older packs (now embedded in the PE).
    stale = OUT_DIR / "WebView2Loader.dll"
    if stale.is_file():
        stale.unlink()

    lines = [
        f"{cfg['title']} - Windows x64",
        "",
        f"Double-click {cfg['out_name']}  (single PE; GUI; no console).",
        "Needs Edge WebView2 Runtime (usually preinstalled on Win10/11).",
        "www/icon/bridge stay in the PE. No %TEMP%\\xu_ui_* directory.",
        "WebView2Loader.dll is written next to the exe (once).",
        "",
        "If it fails: open XuOpenWindow.log next to the exe (always written).",
        "",
        "Debug console (opens a SEPARATE window; does not attach to PowerShell):",
        f"  .\\{cfg['out_name']} --console",
        "PowerShell env (optional):",
        f'  $env:XU_UI_CONSOLE="1"; .\\{cfg["out_name"]}',
        "",
        "Content: xu://app/ (www embedded). Esc / right-click Close.",
    ]
    if not cfg["need_webview"]:
        lines = [
            f"{cfg['title']} - Windows x64",
            "",
            f"Double-click {cfg['out_name']} (GUI subsystem; no WebView2).",
            "",
            "True single PE: Xu + libxu_ui_host.a (static).",
        ]
    (OUT_DIR / "README.txt").write_bytes("\r\n".join(lines).encode("ascii", errors="replace"))

    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ("XuShaped.exe", "XuOpenWindow.exe"):
            p = OUT_DIR / name
            if p.is_file():
                z.write(p, f"windows-x64-ui/{name}")
        z.write(OUT_DIR / "README.txt", "windows-x64-ui/README.txt")

    print("ship:", out_exe, out_exe.stat().st_size, "bytes")
    print("zip:", ZIP, ZIP.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
