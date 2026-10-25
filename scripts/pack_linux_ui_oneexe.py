#!/usr/bin/env python3
"""Build Linux UI app via libxu_ui_host.a (static link — no cgo / no second process).

Pipeline:
  1. xu --emit-obj  →  XUOBJ
  2. xuobj_to_elf_o.py  →  ELF ET_REL .o  (xu_ui_host_run undefined)
  3. c++ -c -DXU_UI_STATIC linux_host(+webview) → .o
  4. ar rcs libxu_ui_host.a
  5. c++ link xu.o + libxu_ui_host.a → one executable

Usage (Linux with GTK4):
  python3 scripts/pack_linux_ui_oneexe.py --app shaped -o /tmp/xu_shaped

The packer is a product-lane consumer: it resolves a hosted compiler from
``--xu``/``XU_COMPILER`` (or the product seed resolver) and never builds or
selects the Rust bootstrap primer.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXAMPLES_ROOT = pathlib.Path(os.environ.get("XU_EXAMPLES_ROOT", ROOT.parent / "xu-examples")).expanduser().resolve()
HOST_SEED_RESOLVER = ROOT / "scripts" / "xu_host_seed.sh"
PRODUCT_COMPILER_RUNNER = ROOT / "scripts" / "run_product_compiler.sh"
AR_HOST = ROOT / "scripts" / "ar_xu_host.py"
XUOBJ_TO_ELF = ROOT / "scripts" / "xuobj_to_elf_o.py"
OUT_DIR = ROOT / "dist" / "linux-ui"
sys.path.insert(0, str(ROOT / "scripts"))
from xu_brand import brand_www_extras, resolve_project_icon  # noqa: E402

DEFAULT_WWW = EXAMPLES_ROOT / "examples" / "16_ui_webview" / "open" / "www"


def write_blob_c(data: bytes, out_c: pathlib.Path, *, symbol: str, comment: str) -> None:
    parts = [f"/* {comment} */\n", f"const unsigned char {symbol}[] = {{\n"]
    for i in range(0, len(data), 16):
        chunk = ", ".join(f"0x{b:02x}" for b in data[i : i + 16])
        parts.append(f"  {chunk},\n")
    parts.append("};\n")
    parts.append(f"const unsigned int {symbol}_len = {len(data)};\n")
    out_c.write_text("".join(parts), encoding="utf-8")


def write_www_blob_c(
    www_dir: pathlib.Path,
    out_c: pathlib.Path,
    extra: list[tuple[str, bytes]] | None = None,
) -> int:
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
        "/* Embedded #ui/webview www/ — served from memory. */\n",
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
        "out_default": "xu_shaped",
        "need_webview": False,
    },
    "open": {
        "xu_src": str(EXAMPLES_ROOT / "examples/16_ui_webview/open/main.xu"),
        "out_default": "xu_open_win",
        "need_webview": True,
    },
}


def pkg_flags(pkg: str) -> list[str]:
    out = subprocess.check_output(["pkg-config", "--cflags", "--libs", pkg], text=True)
    return out.split()


def gtk_flags() -> list[str]:
    flags = pkg_flags("gtk4")
    # The shell calls Xlib directly when GTK was built with its X11 backend.
    # GTK's public pkg-config flags do not propagate that direct dependency.
    if subprocess.call(["pkg-config", "--exists", "x11"]) == 0:
        flags.extend(pkg_flags("x11"))
    return flags


def build_host_a(*, with_webview: bool, td: pathlib.Path, cxx: str) -> pathlib.Path:
    common = [cxx, "-O2", "-std=c++17", "-c", "-DXU_UI_STATIC", "-Isrc/ui/host"]
    gtk = gtk_flags()
    host_o = td / "linux_host.o"
    subprocess.check_call(
        [*common, "src/ui/host/linux_host.cc", "-o", str(host_o), *gtk],
        cwd=str(ROOT),
    )
    objs = [host_o]
    mem_o = td / "xu_ui_mem.o"
    subprocess.check_call(
        [cxx, "-O2", "-std=c++17", "-c", "-Isrc/ui/host", "src/ui/host/xu_ui_mem.cc", "-o", str(mem_o)],
        cwd=str(ROOT),
    )
    objs.append(mem_o)
    assets_o = td / "xu_pack_assets.o"
    assets_weak_o = td / "xu_pack_assets_weak.o"
    for src, dst in (
        ("src/ui/host/xu_pack_assets.c", assets_o),
        ("src/ui/host/xu_pack_assets_weak.c", assets_weak_o),
    ):
        subprocess.check_call(
            [cxx, "-O2", "-x", "c", "-c", "-Isrc/ui/host", src, "-o", str(dst)],
            cwd=str(ROOT),
        )
    objs.append(assets_o)
    objs.append(assets_weak_o)
    if with_webview:
        wv_o = td / "linux_webview.o"
        wv = pkg_flags("webkitgtk-6.0")
        subprocess.check_call(
            [*common, "src/ui/host/linux_webview.cc", "-o", str(wv_o), *gtk, *wv],
            cwd=str(ROOT),
        )
        objs.append(wv_o)
    else:
        stub = td / "webview_stub.cc"
        stub.write_text(
            '#include "xu_content_abi.h"\n'
            'extern "C" const XuContentVTable *xu_webview_plugin_vtable(void) { return nullptr; }\n',
            encoding="utf-8",
        )
        stub_o = td / "webview_stub.o"
        subprocess.check_call([*common, str(stub), "-o", str(stub_o)], cwd=str(ROOT))
        objs.append(stub_o)

    host_a = td / "libxu_ui_host.a"
    subprocess.check_call(
        [sys.executable, str(AR_HOST), "-o", str(host_a), *[str(o) for o in objs]],
        cwd=str(ROOT),
    )
    return host_a


def resolve_product_xu(requested: pathlib.Path | None) -> pathlib.Path:
    """Resolve a hosted product compiler; never select/build the Rust primer."""
    if not HOST_SEED_RESOLVER.is_file() or not os.access(
        HOST_SEED_RESOLVER, os.X_OK
    ):
        raise SystemExit(
            f"pack_linux: missing executable seed resolver: {HOST_SEED_RESOLVER}"
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
            "pack_linux: no hosted product xu found; "
            "set --xu PATH or XU_COMPILER (Rust bootstrap is not a product fallback)"
        )
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise SystemExit("pack_linux: xu_host_seed returned an invalid compiler path")
    try:
        compiler = pathlib.Path(lines[0]).resolve()
    except (OSError, RuntimeError) as exc:
        raise SystemExit(
            f"pack_linux: cannot canonicalize resolved compiler: {exc}"
        ) from exc
    if not compiler.is_file() or not os.access(compiler, os.X_OK):
        raise SystemExit(f"pack_linux: resolved compiler is not executable: {compiler}")
    return compiler


def run_product_compiler(xu: pathlib.Path, args: list[str]) -> None:
    """Compile through the hermetic product wrapper (clears ambient XUPATH/cache)."""
    if not PRODUCT_COMPILER_RUNNER.is_file() or not os.access(
        PRODUCT_COMPILER_RUNNER, os.X_OK
    ):
        raise SystemExit(
            f"pack_linux: missing product compiler wrapper: {PRODUCT_COMPILER_RUNNER}"
        )
    subprocess.check_call(
        [str(PRODUCT_COMPILER_RUNNER), str(xu), *args],
        cwd=str(ROOT),
    )


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
    ap.add_argument("--cxx", default="c++")
    ap.add_argument(
        "--xu",
        dest="xu_compiler",
        type=pathlib.Path,
        default=None,
        help="hosted product Xu compiler (default: XU_COMPILER or product seed resolver)",
    )
    ap.add_argument("--archive-only", action="store_true", help="only build libxu_ui_host.a")
    ap.add_argument("--www", type=pathlib.Path, default=None, help="static www/ to embed")
    ap.add_argument("--webview", action="store_true", help="force WebKitGTK host plugin")
    ap.add_argument("--no-webview", action="store_true", help="force shell-only host")
    ap.add_argument(
        "--target",
        choices=("linux-x64", "linux-arm64"),
        default=None,
        help="linux target for xu --emit-obj (default: host)",
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
        cfg = {
            "xu_src": str(xu_src.parent if xu_src.name == "main.xu" and (xu_src.parent / "xu.xun").is_file() else xu_src),
            "out_default": xu_src.stem,
            "need_webview": need_webview,
        }
        www = args.www
        if www is None and need_webview:
            sib = xu_src.parent / "www"
            www = sib if sib.is_dir() else None
    else:
        cfg = dict(APPS[args.app])
        xu_src = ROOT / cfg["xu_src"]
        www = args.www
        if www is None and cfg["need_webview"]:
            sib = pathlib.Path(xu_src).parent / "www"
            www = sib if sib.is_dir() else DEFAULT_WWW

    if www is not None and not www.is_absolute():
        www = ROOT / www
    out = args.output or (OUT_DIR / cfg["out_default"])

    if shutil.which("pkg-config") is None:
        raise SystemExit("pack_linux: need pkg-config + gtk4")
    if subprocess.call(["pkg-config", "--exists", "gtk4"]) != 0:
        raise SystemExit("pack_linux: gtk4 not found (install libgtk-4-dev)")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="xu_linux_ui_") as td0:
        td = pathlib.Path(td0)
        host_a = build_host_a(with_webview=cfg["need_webview"], td=td, cxx=args.cxx)
        shipped_a = OUT_DIR / "libxu_ui_host.a"
        shipped_a.write_bytes(host_a.read_bytes())
        print("archive:", shipped_a, shipped_a.stat().st_size, "bytes")

        if args.archive_only:
            print("ship-archive:", shipped_a)
            return

        xu = resolve_product_xu(args.xu_compiler)
        xuobj = td / "app.xuobj"
        xu_o = td / "app.o"
        xu_cmd = ["build", str(xu_src.parent if xu_src.name == "main.xu" and (xu_src.parent / "xu.xun").is_file() else xu_src), "--emit-obj", "-o", str(xuobj)]
        if args.target:
            xu_cmd[2:2] = ["--target", args.target]
        run_product_compiler(xu, xu_cmd)
        subprocess.check_call(
            [sys.executable, str(XUOBJ_TO_ELF), str(xuobj), str(xu_o)],
            cwd=str(ROOT),
        )

        icon_png = resolve_project_icon(xu_src)
        if not icon_png.is_file():
            raise SystemExit(f"missing icon: {icon_png}")
        icon_c = td / "icon_blob.c"
        write_blob_c(
            icon_png.read_bytes(),
            icon_c,
            symbol="xu_pack_icon_png",
            comment="Embedded brand/xu_app_logo.png — in-memory",
        )
        icon_o = td / "icon_blob.o"
        subprocess.check_call([args.cxx, "-x", "c", "-c", "-O2", str(icon_c), "-o", str(icon_o)])

        extra_o: list[str] = [str(icon_o)]
        if www is not None:
            www_c = td / "www_blob.c"
            extra = brand_www_extras(xu_src, icon_png) if cfg["need_webview"] else None
            n = write_www_blob_c(www, www_c, extra=extra)
            www_o = td / "www_blob.o"
            subprocess.check_call([args.cxx, "-x", "c", "-c", "-O2", str(www_c), "-o", str(www_o)])
            extra_o.append(str(www_o))
            print(f"www: embed {n} files from {www} (in-memory xu://)")

        shim = td / "shim.c"
        shim.write_text(
            "/* Pack entry: www/icon stay in the ELF; IPC is in-process :xu: mailbox. */\n"
            "#include <stdlib.h>\n#include \"xu_ui_mem.h\"\n#include \"xu_pack_assets.h\"\n#include \"xu_ui_text.h\"\n"
            "#include <unistd.h>\n"
            "#include <sys/auxv.h>\n"
            "extern char **environ;\n"
            "#ifdef __cplusplus\nextern \"C\" {\n#endif\n"
            "void xu_app_start_hosted(int argc, char **argv, char **envp, long page_size, unsigned long hwcap, int (*start_worker)(void *(*)(void *), void *));\n"
            "int xu_ui_runtime_start_worker(void *(*entry)(void *), void *argument);\n"
            "#ifdef __cplusplus\n}\n#endif\n"
            "static void xu_pack_setup(void) {\n  xu_ui_set_asset_reader(xu_pack_asset_ptr);\n  xu_draw_text_init();\n"
            "  /* No /tmp/xu_ui_* workdir — mailbox is in-process (:xu: / xu_ui_mem). */\n"
            "  unsetenv(\"XU_UI_TMP\");\n"
            "  setenv(\"XU_UI_PACK\", \"1\", 1);\n"
            "  setenv(\"XU_UI_WWW\", \":mem:\", 1);\n"
            "}\n"
            "__attribute__((constructor)) static void xu_pack_ctor(void) { xu_pack_setup(); }\n"
            "int main(int argc, char **argv) {\n"
            "  xu_pack_setup();\n"
            "  xu_app_start_hosted(argc, argv, environ, sysconf(_SC_PAGESIZE), getauxval(AT_HWCAP), xu_ui_runtime_start_worker);\n"
            "  return 0;\n"
            "}\n",
            encoding="utf-8",
        )
        shim_o = td / "shim.o"
        subprocess.check_call([args.cxx, "-x", "c", "-c", "-O2", "-Isrc/ui/host", str(shim), "-o", str(shim_o)])

        link = [
            args.cxx,
            "-O2",
            str(shim_o),
            str(xu_o),
            *extra_o,
            # whole-archive: content plugin only reached via bootstrap string
            "-Wl,--whole-archive",
            str(host_a),
            "-Wl,--no-whole-archive",
            "-Wl,--allow-multiple-definition",
            "-o",
            str(out),
            *gtk_flags(),
        ]
        if cfg["need_webview"]:
            link.extend(pkg_flags("webkitgtk-6.0"))
        subprocess.check_call(link, cwd=str(ROOT))
        print("ship:", out, out.stat().st_size, "bytes")
        print("link: via --whole-archive libxu_ui_host.a")


if __name__ == "__main__":
    main()
