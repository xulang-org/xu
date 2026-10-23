#!/usr/bin/env python3
"""Build a true single-file macOS UI app (Xu + Swift host in one Mach-O).

Pipeline:
  1. xu --target macos-{arm64,x64} --emit-obj  →  XUOBJ
  2. xuobj_to_macho_o.py  →  MH_OBJECT (arm64 or x86_64)
  3. swiftc -c -D XU_UI_STATIC host(+plugin) → .o
  4. ar rcs libxu_ui_host.a  →  foreign code as static archive
  5. clang/swiftc link shim + xu.o + libxu_ui_host.a → one executable

Usage (repo root):
  python3 scripts/pack_macos_ui_oneexe.py --app open -o /tmp/xu_open_win
  python3 scripts/pack_macos_ui_oneexe.py --app shaped --arch x64 -o /tmp/xu_shaped_x64

The packer is a product-lane consumer: it resolves a hosted compiler from
``--xu``/``XU_COMPILER`` (or the product seed resolver) and never builds or
selects the Rust bootstrap primer.

For a double-clickable .app (Info.plist + icns + dist zip), use:
  python3 scripts/pack_macos_ui_app.py --app open
"""
from __future__ import annotations

import argparse
import os
import platform
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXAMPLES_ROOT = pathlib.Path(os.environ.get("XU_EXAMPLES_ROOT", ROOT.parent / "xu-examples")).expanduser().resolve()
HOST_SEED_RESOLVER = ROOT / "scripts" / "xu_host_seed.sh"
PRODUCT_COMPILER_RUNNER = ROOT / "scripts" / "run_product_compiler.sh"
XUOBJ_TO_O = ROOT / "scripts" / "xuobj_to_macho_o.py"
AR_HOST = ROOT / "scripts" / "ar_xu_host.py"
sys.path.insert(0, str(ROOT / "scripts"))
from xu_brand import brand_www_extras, resolve_project_icon  # noqa: E402

DEFAULT_WWW = EXAMPLES_ROOT / "examples" / "16_ui_webview" / "open" / "www"

# Match webview.bridge_script() — xu://app/__xu/bridge.js from pack (no TEMP).
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
    "X.invoke=function(n,p){return fetch(B+'/invoke',{method:'POST',headers:{'Content-Type':'text/xun; "
    "charset=utf-8'},body:enc(n,p)}).then(function(r){return r.text();}).then(function(t){var "
    "o=dec(t);if(o.ok==='false'||o.ok==='0')throw new Error(o.error||'error');"
    "return o.result!=null?o.result:t;});};"
    "X.listen=function(n,cb){(X._L=X._L||{})[n]=cb;};"
    "window.invoke=X.invoke;window.listen=function(n,cb){return X.listen(n,cb);};"
    "async function poll(){try{const t=await fetch(B+'/poll').then(function(r){return r.text();});"
    "if(!t||!t.length)return;const o=dec(t);const n=o.name||'';const p=o.payload!=null?o.payload:'';"
    "const cb=(X._L||{})[n];if(cb)cb(p);}catch(e){}}"
    "setInterval(poll,400);"
    "})(window.__XU__);"
)

# Xu --target / Apple clang-swift triples.
ARCH_XU = {"arm64": "macos-arm64", "x64": "macos-x64"}


def apple_triple(arch: str) -> str:
    """Match host macOS SDK (pinning macos11/12 breaks Swift/AppKit at runtime)."""
    cpu = "arm64" if arch == "arm64" else "x86_64"
    try:
        sdk = subprocess.check_output(
            ["xcrun", "--sdk", "macosx", "--show-sdk-version"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        major = sdk.split(".")[0]
        if major.isdigit():
            return f"{cpu}-apple-macos{major}"
    except (OSError, subprocess.CalledProcessError):
        pass
    return f"{cpu}-apple-macos"


def host_arch() -> str:
    m = platform.machine().lower()
    if m in ("arm64", "aarch64"):
        return "arm64"
    if m in ("x86_64", "amd64"):
        return "x64"
    raise SystemExit(f"unsupported host machine: {m}")


def write_icon_blob_c(png: pathlib.Path, out_c: pathlib.Path) -> None:
    data = png.read_bytes()
    parts = [
        "/* Embedded brand/xu_app_logo.png — served from memory, not extracted. */\n",
        "const unsigned char xu_pack_icon_png[] = {\n",
    ]
    for i in range(0, len(data), 16):
        chunk = ", ".join(f"0x{b:02x}" for b in data[i : i + 16])
        parts.append(f"  {chunk},\n")
    parts.append("};\n")
    parts.append(f"const unsigned int xu_pack_icon_png_len = {len(data)};\n")
    out_c.write_text("".join(parts), encoding="utf-8")


def write_www_blob_c(
    www_dir: pathlib.Path,
    out_c: pathlib.Path,
    extra: list[tuple[str, bytes]] | None = None,
) -> int:
    """Embed www/ files as path table + bytes (host serves from memory via xu://)."""
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
    parts.append(f"const XuWwwFile xu_pack_www_files[] = {{\n")
    for i, (rel, data) in enumerate(files):
        parts.append(f'  {{"{rel}", xu_www_{i}, {len(data)}}},\n')
    parts.append("};\n")
    parts.append(f"const unsigned xu_pack_www_files_count = {len(files)};\n")
    out_c.write_text("".join(parts), encoding="utf-8")
    return len(files)


APPS = {
    "open": {
        "xu_src": str(EXAMPLES_ROOT / "examples/16_ui_webview/open/main.xu"),
        "out_default": "/tmp/xu_open_win",
        "title": "Xu WebView Window",
        "plugin": "src/ui/host/macos_webview.swift",
        "frameworks": ["AppKit", "UserNotifications", "WebKit", "QuartzCore"],
    },
    "remote": {
        "xu_src": str(EXAMPLES_ROOT / "examples/16_ui_webview/remote/main.xu"),
        "out_default": "/tmp/xu_remote",
        "title": "Xu Remote HTTP + xu:// IPC",
        "plugin": "src/ui/host/macos_webview.swift",
        "frameworks": ["AppKit", "UserNotifications", "WebKit", "QuartzCore"],
    },
    "shaped": {
        "xu_src": str(EXAMPLES_ROOT / "examples/16_ui_webview/shaped/main.xu"),
        "out_default": "/tmp/xu_shaped",
        "title": "Xu Shaped Window",
        "plugin": None,
        "frameworks": ["AppKit", "UserNotifications", "QuartzCore"],
    },
    "shaped_webview": {
        "xu_src": str(EXAMPLES_ROOT / "examples/16_ui_webview/shaped_webview/main.xu"),
        "out_default": "/tmp/xu_shaped_wv",
        "title": "Xu Shaped WebView",
        "plugin": "src/ui/host/macos_webview.swift",
        "frameworks": ["AppKit", "UserNotifications", "WebKit", "QuartzCore"],
    },
}


def resolve_product_xu(requested: pathlib.Path | None) -> pathlib.Path:
    """Resolve a hosted product compiler; never select/build the Rust primer."""
    if not HOST_SEED_RESOLVER.is_file() or not os.access(
        HOST_SEED_RESOLVER, os.X_OK
    ):
        raise SystemExit(
            f"pack_macos: missing executable seed resolver: {HOST_SEED_RESOLVER}"
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
        [str(HOST_SEED_RESOLVER)],
        cwd=str(ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(
            "pack_macos: no hosted product xu found; "
            "set --xu PATH or XU_COMPILER (Rust bootstrap is not a product fallback)"
        )
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise SystemExit("pack_macos: xu_host_seed returned an invalid compiler path")
    try:
        compiler = pathlib.Path(lines[0]).resolve()
    except (OSError, RuntimeError) as exc:
        raise SystemExit(
            f"pack_macos: cannot canonicalize resolved compiler: {exc}"
        ) from exc
    if not compiler.is_file() or not os.access(compiler, os.X_OK):
        raise SystemExit(f"pack_macos: resolved compiler is not executable: {compiler}")
    return compiler


def run_product_compiler(xu: pathlib.Path, args: list[str]) -> None:
    """Compile through the hermetic product wrapper (clears ambient XUPATH/cache)."""
    if not PRODUCT_COMPILER_RUNNER.is_file() or not os.access(
        PRODUCT_COMPILER_RUNNER, os.X_OK
    ):
        raise SystemExit(
            f"pack_macos: missing product compiler wrapper: {PRODUCT_COMPILER_RUNNER}"
        )
    subprocess.check_call(
        [str(PRODUCT_COMPILER_RUNNER), str(xu), *args],
        cwd=str(ROOT),
    )


def needs_webview_src(src: pathlib.Path) -> bool:
    text = src.read_text(encoding="utf-8", errors="ignore")
    return "#ui/webview" in text or "#webview" in text or "webview." in text


def resolve_macos_cfg(args: argparse.Namespace) -> tuple[pathlib.Path, dict, pathlib.Path | None]:
    """Return (xu_src, cfg-like dict, www)."""
    if args.src is not None:
        xu_src = args.src if args.src.is_absolute() else ROOT / args.src
        if xu_src.is_dir() and (xu_src / "main.xu").is_file():
            xu_src = xu_src / "main.xu"
        if not xu_src.is_file():
            raise SystemExit(f"missing --src: {xu_src}")
        if args.no_webview:
            need_wv = False
        elif args.webview:
            need_wv = True
        else:
            need_wv = needs_webview_src(xu_src)
        try:
            rel = str(xu_src.relative_to(ROOT))
        except ValueError:
            rel = str(xu_src)
        cfg = {
            "xu_src": rel,
            "out_default": "/tmp/" + xu_src.stem,
            "plugin": "src/ui/host/macos_webview.swift" if need_wv else None,
            "frameworks": (
                ["AppKit", "UserNotifications", "WebKit", "QuartzCore"]
                if need_wv
                else ["AppKit", "UserNotifications", "QuartzCore"]
            ),
            "need_webview": need_wv,
        }
        www = args.www
        if www is None and need_wv:
            sib = xu_src.parent / "www"
            www = sib if sib.is_dir() else None
        return xu_src, cfg, www

    cfg = dict(APPS[args.app])
    cfg["need_webview"] = cfg.get("plugin") is not None
    xu_src = ROOT / cfg["xu_src"]
    www = args.www
    if www is None and args.app in ("open", "shaped_webview", "remote"):
        sib = xu_src.parent / "www"
        www = sib if sib.is_dir() else DEFAULT_WWW
    return xu_src, cfg, www


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", choices=sorted(APPS), default="open")
    ap.add_argument(
        "--src",
        type=pathlib.Path,
        default=None,
        help="arbitrary .xu entry (overrides --app)",
    )
    ap.add_argument("-o", "--output", type=pathlib.Path, default=None)
    ap.add_argument(
        "--arch",
        choices=sorted(ARCH_XU),
        default=None,
        help="macos arch (default: host machine — arm64 or x64)",
    )
    ap.add_argument(
        "--xu",
        dest="xu_compiler",
        type=pathlib.Path,
        default=None,
        help="hosted product Xu compiler (default: XU_COMPILER or product seed resolver)",
    )
    ap.add_argument(
        "--www",
        type=pathlib.Path,
        default=None,
        help="static www/ to embed",
    )
    ap.add_argument("--webview", action="store_true", help="force WebKit host plugin")
    ap.add_argument("--no-webview", action="store_true", help="force shell-only host (no WebKit)")
    args = ap.parse_args()
    arch = args.arch or host_arch()
    triple = apple_triple(arch)
    xu_target = ARCH_XU[arch]
    xu_src, cfg, www = resolve_macos_cfg(args)
    out = args.output or pathlib.Path(cfg["out_default"])
    if www is not None and not www.is_absolute():
        www = ROOT / www

    xu = resolve_product_xu(args.xu_compiler)
    with tempfile.TemporaryDirectory(prefix="xu_mac_ui_") as td0:
        td = pathlib.Path(td0)
        xuobj = td / "app.xuobj"
        xu_o = td / "app.o"
        run_product_compiler(
            xu,
            [
                "build",
                str(xu_src),
                "--target",
                xu_target,
                "--emit-obj",
                "-o",
                str(xuobj),
            ],
        )
        subprocess.check_call(
            [sys.executable, str(XUOBJ_TO_O), str(xuobj), str(xu_o)],
            cwd=str(ROOT),
        )

        host_srcs = [str(ROOT / "src/ui/host/macos_host.swift"), str(ROOT / "src/ui/host/macos_draw.swift")]
        if cfg["plugin"]:
            host_srcs.append(str(ROOT / cfg["plugin"]))
        # swiftc -c writes .o next to sources by default; force -o via one module emit
        host_o_dir = td / "host"
        host_o_dir.mkdir()
        cmd = [
            "swiftc",
            "-target",
            triple,
            "-parse-as-library",
            "-c",
            "-O",
            "-D",
            "XU_UI_STATIC",
            "-module-name",
            "XuUIHost",
            *host_srcs,
            "-working-directory",
            str(host_o_dir),
        ]
        for fw in cfg["frameworks"]:
            cmd.extend(["-framework", fw])
        subprocess.check_call(cmd, cwd=str(ROOT))
        host_objs = sorted(host_o_dir.glob("*.o"))
        if not host_objs:
            host_objs = []
            for src in host_srcs:
                o = td / (pathlib.Path(src).stem + ".o")
                c2 = [
                    "swiftc",
                    "-target",
                    triple,
                    "-parse-as-library",
                    "-c",
                    "-O",
                    "-D",
                    "XU_UI_STATIC",
                    "-module-name",
                    "XuUIHost",
                    src,
                    "-o",
                    str(o),
                ]
                for fw in cfg["frameworks"]:
                    c2.extend(["-framework", fw])
                subprocess.check_call(c2, cwd=str(ROOT))
                host_objs.append(o)

        pack_assets_o = td / "xu_pack_assets.o"
        pack_assets_weak_o = td / "xu_pack_assets_weak.o"
        mem_o = td / "xu_ui_mem.o"
        clang_c = ["clang", "-target", triple, "-c", "-O2", "-Isrc/ui/host"]
        clang_cxx = ["clang++", "-std=c++17", "-target", triple, "-c", "-O2", "-Isrc/ui/host"]
        for src, dst in (
            (ROOT / "src/ui/host/xu_pack_assets.c", pack_assets_o),
            (ROOT / "src/ui/host/xu_pack_assets_weak.c", pack_assets_weak_o),
        ):
            subprocess.check_call([*clang_c, str(src), "-o", str(dst)], cwd=str(ROOT))
        subprocess.check_call(
            [*clang_cxx, str(ROOT / "src/ui/host/xu_ui_mem.cc"), "-o", str(mem_o)],
            cwd=str(ROOT),
        )
        host_objs.append(pack_assets_o)
        host_objs.append(pack_assets_weak_o)
        host_objs.append(mem_o)

        icon_png = resolve_project_icon(xu_src)
        if not icon_png.is_file():
            raise SystemExit(f"missing icon: {icon_png}")
        icon_c = td / "icon_blob.c"
        write_icon_blob_c(icon_png, icon_c)
        icon_o = td / "icon_blob.o"
        subprocess.check_call([*clang_c, str(icon_c), "-o", str(icon_o)])

        www_o = None
        if www is not None:
            www_c = td / "www_blob.c"
            extra = brand_www_extras(xu_src, icon_png) if cfg["need_webview"] else []
            if cfg["need_webview"]:
                extra.append(("__xu/bridge.js", XU_BRIDGE_JS.encode("utf-8")))
            n = write_www_blob_c(www, www_c, extra=extra)
            www_o = td / "www_blob.o"
            subprocess.check_call([*clang_c, str(www_c), "-o", str(www_o)])
            print(f"www: embed {n} files from {www} (in-memory xu://)")

        shim = td / "shim.c"
        shim.write_text(
            "/* Packaged UI entry: www/icon stay in the binary; IPC is in-process :xu: mailbox. */\n"
            "#include <stdlib.h>\n#include \"xu_ui_mem.h\"\n#include \"xu_pack_assets.h\"\n#include \"xu_ui_text.h\"\n"
            "\n"
            "void xu_app_start(int argc, char **argv);\n"
            "\n"
            "static void xu_pack_setup(void) {\n  xu_ui_set_asset_reader(xu_pack_asset_ptr);\n  xu_draw_text_init();\n"
            "  /* No /tmp/xu_ui_* workdir — mailbox is in-process (:xu: / xu_ui_mem). */\n"
            "  unsetenv(\"XU_UI_TMP\");\n"
            "  setenv(\"XU_UI_PACK\", \"1\", 1);\n"
            "  setenv(\"XU_UI_WWW\", \":mem:\", 1);\n"
            "}\n"
            "\n"
            "int main(int argc, char **argv) {\n"
            "  xu_pack_setup();\n"
            "  xu_app_start(argc, argv);\n"
            "  return 0;\n"
            "}\n",
            encoding="utf-8",
        )
        shim_o = td / "shim.o"
        subprocess.check_call([*clang_c, str(shim), "-o", str(shim_o)])

        host_a = td / "libxu_ui_host.a"
        subprocess.check_call(
            [
                sys.executable,
                str(AR_HOST),
                "-o",
                str(host_a),
                *[str(o) for o in host_objs],
            ],
            cwd=str(ROOT),
        )

        link = [
            "swiftc",
            "-target",
            triple,
            "-O",
            "-o",
            str(out),
            str(shim_o),
            str(icon_o),
            str(xu_o),
        ]
        if www_o is not None:
            link.append(str(www_o))
        for fw in cfg["frameworks"]:
            link.extend(["-framework", fw])
        # force_load: XuWebViewPluginBootstrap is only reached via NSClassFromString;
        # without this, ld dead-strips macos_webview.o from the static archive.
        link.extend(["-Xlinker", "-force_load", "-Xlinker", str(host_a)])
        # Prefer host's strong _xu_ui_host_run over Xu weak stub.
        link.extend(["-Xlinker", "-undefined", "-Xlinker", "dynamic_lookup"])
        subprocess.check_call(link, cwd=str(ROOT))

    print("ship:", out, out.stat().st_size, "bytes", f"arch={arch}", f"target={xu_target}")
    print("run:", out)
    print("link: via -force_load libxu_ui_host.a (keep content plugin)")


if __name__ == "__main__":
    main()
