#!/usr/bin/env python3
"""Build a double-clickable macOS .app bundle for Xu UI demos.

Wraps the single Mach-O from pack_macos_ui_oneexe.py into:
  XuOpenWindow.app/
    Contents/
      Info.plist
      PkgInfo
      MacOS/<exe>
      Resources/AppIcon.icns

Usage (repo root):
  python3 scripts/pack_macos_ui_app.py --app open
  python3 scripts/pack_macos_ui_app.py --app shaped --arch x64
  python3 scripts/pack_macos_ui_app.py --app shaped -o /tmp/XuShaped.app
  open dist/macos-arm64-ui/XuOpenWindow.app
"""
from __future__ import annotations

import argparse
import os
import pathlib
import plistlib
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
ONEEXE = ROOT / "scripts" / "pack_macos_ui_oneexe.py"
sys.path.insert(0, str(ROOT / "scripts"))
from xu_brand import ICON_PNG, resolve_project_icon  # noqa: E402

# Keep in sync with pack_macos_ui_oneexe.APPS keys.
APPS = {
    "open": {
        "bundle": "XuOpenWindow",
        "display": "Xu WebView Window",
        "identifier": "dev.xu.ui.openwindow",
        "need_webview": True,
    },
    "remote": {
        "bundle": "XuRemote",
        "display": "Xu Remote HTTP",
        "identifier": "dev.xu.ui.remote",
        "need_webview": True,
    },
    "shaped": {
        "bundle": "XuShaped",
        "display": "Xu Shaped Window",
        "identifier": "dev.xu.ui.shaped",
        "need_webview": False,
    },
    "shaped_webview": {
        "bundle": "XuShapedWebView",
        "display": "Xu Shaped WebView",
        "identifier": "dev.xu.ui.shapedwebview",
        "need_webview": True,
    },
}


def host_arch() -> str:
    m = os.uname().machine
    if m in ("arm64", "aarch64"):
        return "arm64"
    if m in ("x86_64", "amd64"):
        return "x64"
    raise SystemExit(f"unsupported host machine: {m}")


def dist_dir(arch: str) -> pathlib.Path:
    return ROOT / "dist" / f"macos-{arch}-ui"


def png_to_icns(png: pathlib.Path, icns: pathlib.Path, work: pathlib.Path) -> None:
    """Build AppIcon.icns via sips + iconutil (macOS only)."""
    if not png.is_file():
        raise SystemExit(f"missing icon: {png}")
    iconset = work / "AppIcon.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)

    # (pixel_size, iconutil filename)
    sizes = [
        (16, "icon_16x16.png"),
        (32, "diana.s@example.org"),
        (32, "icon_32x32.png"),
        (64, "ivan.p@example.net"),
        (128, "icon_128x128.png"),
        (256, "wendy.h@example.net"),
        (256, "icon_256x256.png"),
        (512, "wendy.h@example.net"),
        (512, "icon_512x512.png"),
        (1024, "walt.e@example.net"),
    ]
    for px, name in sizes:
        out = iconset / name
        # Upscale from 512 source for 1024 if needed — sips handles it.
        subprocess.check_call(
            ["sips", "-z", str(px), str(px), str(png), "--out", str(out)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    subprocess.check_call(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)])
    if not icns.is_file() or icns.stat().st_size < 100:
        raise SystemExit(f"iconutil failed to write {icns}")


def write_info_plist(
    path: pathlib.Path,
    *,
    bundle_name: str,
    display_name: str,
    identifier: str,
    exe_name: str,
) -> None:
    # Minimal, Finder-friendly plist (binary via plistlib).
    info = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleDisplayName": display_name,
        "CFBundleExecutable": exe_name,
        "CFBundleIconFile": "AppIcon",
        "CFBundleIdentifier": identifier,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": bundle_name,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
        # Avoid App Nap delaying IPC/timer drain for UI host.
        "NSSupportsAutomaticTermination": False,
        "NSSupportsSuddenTermination": False,
    }
    with path.open("wb") as f:
        plistlib.dump(info, f)


def assemble_app(
    binary: pathlib.Path,
    app_path: pathlib.Path,
    *,
    bundle_name: str,
    display_name: str,
    identifier: str,
    icns: pathlib.Path,
) -> None:
    if app_path.exists():
        shutil.rmtree(app_path)
    macos = app_path / "Contents" / "MacOS"
    resources = app_path / "Contents" / "Resources"
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)

    exe_name = bundle_name
    dest_bin = macos / exe_name
    shutil.copy2(binary, dest_bin)
    dest_bin.chmod(0o755)

    shutil.copy2(icns, resources / "AppIcon.icns")
    write_info_plist(
        app_path / "Contents" / "Info.plist",
        bundle_name=bundle_name,
        display_name=display_name,
        identifier=identifier,
        exe_name=exe_name,
    )
    (app_path / "Contents" / "PkgInfo").write_text("APPL????", encoding="ascii")


def build_oneexe(
    app_key: str,
    out_bin: pathlib.Path,
    www: pathlib.Path | None,
    arch: str,
    xu_compiler: pathlib.Path | None,
) -> None:
    cmd = [
        sys.executable,
        str(ONEEXE),
        "--app",
        app_key,
        "--arch",
        arch,
        "-o",
        str(out_bin),
    ]
    if www is not None:
        cmd.extend(["--www", str(www)])
    if xu_compiler is not None:
        cmd.extend(["--xu", str(xu_compiler)])
    subprocess.check_call(cmd, cwd=str(ROOT))


def write_readme(out_dir: pathlib.Path, cfg: dict, app_name: str, arch: str) -> None:
    lines = [
        f"{cfg['display']} - macOS {arch}",
        "",
        f"Double-click {app_name}.app  (or: open {app_name}.app).",
        "Single Mach-O inside Contents/MacOS; www/icon embedded in-process.",
        "",
    ]
    if cfg["need_webview"]:
        lines.append("Needs macOS WebKit (system). Content: xu://app/.")
    else:
        lines.append("No WebKit required (shaped / draw shell).")
    lines.extend(
        [
            "",
            "Rebuild:",
            f"  python3 scripts/pack_macos_ui_app.py --app <name> --arch {arch}",
            "",
            "Raw oneexe (no .app wrapper):",
            f"  python3 scripts/pack_macos_ui_oneexe.py --app <name> --arch {arch} -o /tmp/xu_bin",
        ]
    )
    (out_dir / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def zip_dist(out_dir: pathlib.Path, zip_path: pathlib.Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(out_dir.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(out_dir).as_posix())


def main() -> None:
    ap = argparse.ArgumentParser(description="Pack Xu UI demo as a macOS .app bundle")
    ap.add_argument("--app", choices=sorted(APPS), default="open")
    ap.add_argument(
        "--arch",
        choices=("arm64", "x64"),
        default=None,
        help="macos arch (default: host machine — arm64 or x64)",
    )
    ap.add_argument(
        "-o",
        "--output",
        type=pathlib.Path,
        default=None,
        help="output .app path (default: dist/macos-<arch>-ui/<Bundle>.app)",
    )
    ap.add_argument(
        "--www",
        type=pathlib.Path,
        default=None,
        help="static www/ to embed (passed through to oneexe packer)",
    )
    ap.add_argument(
        "--xu",
        dest="xu_compiler",
        type=pathlib.Path,
        default=None,
        help="hosted product Xu compiler (passed through; default: product seed resolver)",
    )
    ap.add_argument(
        "--no-zip",
        action="store_true",
        help="skip writing dist/macos-*-ui.zip",
    )
    args = ap.parse_args()
    arch = args.arch or host_arch()
    cfg = APPS[args.app]
    out_dir = dist_dir(arch)
    out_dir.mkdir(parents=True, exist_ok=True)

    app_path = args.output
    if app_path is None:
        app_path = out_dir / f"{cfg['bundle']}.app"
    elif not str(app_path).endswith(".app"):
        app_path = pathlib.Path(str(app_path) + ".app")
    if not app_path.is_absolute():
        app_path = (pathlib.Path.cwd() / app_path).resolve()

    www = args.www
    if www is not None and not www.is_absolute():
        www = ROOT / www

    with tempfile.TemporaryDirectory(prefix="xu_mac_app_") as td0:
        td = pathlib.Path(td0)
        bin_path = td / cfg["bundle"]
        print(f"build oneexe → {bin_path} (arch={arch})")
        xu_compiler = args.xu_compiler
        if xu_compiler is not None and not xu_compiler.is_absolute():
            xu_compiler = (ROOT / xu_compiler).resolve()
        build_oneexe(args.app, bin_path, www, arch, xu_compiler)

        icns = td / "AppIcon.icns"
        xu_src = pathlib.Path(os.environ.get("XU_EXAMPLES_ROOT", ROOT.parent / "xu-examples")).expanduser().resolve() / "examples" / "16_ui_webview" / args.app / "main.xu"
        icon_png = resolve_project_icon(xu_src) if xu_src.is_file() else ICON_PNG
        print(f"build icns from {icon_png}")
        png_to_icns(icon_png, icns, td)

        print(f"assemble {app_path}")
        assemble_app(
            bin_path,
            app_path,
            bundle_name=cfg["bundle"],
            display_name=cfg["display"],
            identifier=cfg["identifier"],
            icns=icns,
        )

    # Always refresh README next to default dist when shipping there.
    if app_path.parent == out_dir or args.output is None:
        write_readme(out_dir, cfg, cfg["bundle"], arch)
        # Keep only current app + README in dist (like windows-x64-ui open ship).
        for p in list(out_dir.iterdir()):
            if p.name.endswith(".app") and p.resolve() != app_path.resolve():
                # Do not delete sibling apps if user asked for custom -o elsewhere;
                # when shipping to dist, leave other apps unless rebuilding open default.
                pass
        if not args.no_zip:
            zip_path = ROOT / "dist" / f"macos-{arch}-ui.zip"
            zip_dist(out_dir, zip_path)
            print(f"zip: {zip_path} ({zip_path.stat().st_size} bytes)")

    # Clear quarantine + ad-hoc sign so Finder double-click works on local builds.
    try:
        subprocess.call(
            ["xattr", "-cr", str(app_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass
    try:
        subprocess.check_call(
            [
                "codesign",
                "--force",
                "--deep",
                "--sign",
                "-",
                str(app_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"warning: codesign ad-hoc failed: {e}")

    exe = app_path / "Contents" / "MacOS" / cfg["bundle"]
    print(f"ship: {app_path}")
    print(f"  exe: {exe} ({exe.stat().st_size} bytes)")
    print(f"  icon: {app_path / 'Contents' / 'Resources' / 'AppIcon.icns'}")
    print(f"run: open {app_path}")


if __name__ == "__main__":
    main()
