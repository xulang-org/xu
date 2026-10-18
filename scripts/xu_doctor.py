#!/usr/bin/env python3
"""Desktop toolchain doctor — implementation detail for product `xu doctor`.

User entry is the self-hosted Xu product.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOST_SEED_RESOLVER = ROOT / "scripts" / "xu_host_seed.sh"

HOSTED = {
    "macos-arm64",
    "macos-x64",
    "linux-arm64",
    "linux-x64",
    "windows-x64",
}


def which(bin_name: str) -> str | None:
    return shutil.which(bin_name)


def run_ok(argv: list[str]) -> bool:
    try:
        r = subprocess.run(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return r.returncode == 0
    except OSError:
        return False


def version_line(bin_name: str, args: list[str]) -> str:
    try:
        r = subprocess.run(
            [bin_name, *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode != 0:
            return ""
        for stream in (r.stdout, r.stderr):
            for line in stream.splitlines():
                line = line.strip()
                if line:
                    return line
    except OSError:
        pass
    return ""


def check_bin(name: str, bin_name: str, ver_args: list[str]) -> tuple[str, str, str]:
    """Return (tag, name, detail) where tag is ok|missing|skip."""
    path = which(bin_name)
    if not path:
        return "missing", name, f"not found: {bin_name}"
    ver = version_line(bin_name, ver_args)
    detail = f"{path} ({ver})" if ver else path
    return "ok", name, detail


def default_target() -> str:
    # Prefer explicit env; else host guess.
    os_name = os.environ.get("XUOS", "").strip().lower()
    arch = os.environ.get("XUARCH", "").strip().lower()
    if os_name and arch:
        t = f"{os_name}-{arch}"
        if t in HOSTED:
            return t
    u = sys.platform
    machine = os.uname().machine if hasattr(os, "uname") else ""
    if u == "darwin":
        return "macos-arm64" if machine in ("arm64", "aarch64") else "macos-x64"
    if u.startswith("linux"):
        return "linux-arm64" if machine in ("arm64", "aarch64") else "linux-x64"
    if u.startswith("win"):
        return "windows-x64"
    return "macos-arm64"


def _configured_compiler() -> str:
    """Return an explicit compiler override, preserving precedence.

    ``XU_COMPILER`` is the product-facing spelling; ``XU`` and ``XU_SEED``
    remain accepted for compatibility with the shell build helpers.  The
    value is always passed through ``xu_host_seed.sh`` below, so a primer path
    cannot be smuggled into the product lane by setting an environment
    variable.
    """

    for name in ("XU_COMPILER", "XU", "XU_SEED"):
        value = os.environ.get(name, "").strip()
        if value:
            return os.path.expanduser(value)
    return ""


def _resolve_xu_seed(lane: str) -> str | None:
    """Resolve the hosted product compiler through the shared policy."""
    if lane != "product":
        raise ValueError(f"unsupported compiler lane: {lane}")
    if not HOST_SEED_RESOLVER.is_file():
        return None
    resolver_cmd = [str(HOST_SEED_RESOLVER)]
    if not os.access(HOST_SEED_RESOLVER, os.X_OK):
        # Git-Bash/MSYS hosts may expose the script without a Unix executable
        # bit.  Still use the same resolver; never replace it with PATH lookup.
        bash = which("bash")
        if not bash:
            return None
        resolver_cmd = [bash, str(HOST_SEED_RESOLVER)]

    env = os.environ.copy()
    candidate = _configured_compiler()

    # Preserve the caller's lexical path for the boundary check.  Resolving
    # it before classification would turn a bootstrap symlink to an external
    # executable into an apparently hosted path.
    candidate_path: pathlib.Path | None = None
    if candidate:
        candidate_path = pathlib.Path(candidate).expanduser()
        if not candidate_path.is_absolute():
            candidate_path = ROOT / candidate_path
        candidate_path = candidate_path.absolute()

    # Always set XU_SEED explicitly.  An empty value asks the resolver for its
    # hosted auto-discovery and prevents a stale ambient value from changing
    # the lane behind the doctor's back.
    env["XU_SEED"] = str(candidate_path) if candidate_path is not None else ""
    try:
        proc = subprocess.run(
            resolver_cmd,
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        return None
    try:
        resolved = pathlib.Path(lines[0]).resolve()
    except (OSError, RuntimeError):
        return None
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        return None
    return str(resolved)


def find_xu_bin(lane: str = "product") -> str | None:
    """Find an executable for ``lane`` without an implicit primer fallback."""

    return _resolve_xu_seed(lane)


def macos_checks(target: str) -> list[tuple[str, str, str]]:
    out = [
        check_bin("python3", "python3", ["--version"]),
        check_bin("swiftc", "swiftc", ["--version"]),
        check_bin("clang", "clang", ["--version"]),
        check_bin("clang++", "clang++", ["--version"]),
    ]
    sdk = run_ok(["xcode-select", "-p"])
    out.append(
        (
            "ok" if sdk else "missing",
            "macOS SDK",
            "xcode-select -p ok" if sdk else "run: xcode-select --install",
        )
    )
    if target.endswith("x64"):
        triple = "x86_64-apple-macos"  # host SDK; avoid pinning macos11/12

        ok = False
        try:
            p = subprocess.run(
                ["clang", "-target", triple, "-x", "c", "-c", "-", "-o", "/dev/null"],
                input="int x;\n",
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            ok = p.returncode == 0
        except OSError:
            ok = False
        out.append(
            (
                "ok" if ok else "missing",
                "x86_64 cross clang",
                f"-target {triple}",
            )
        )
    return out


def windows_checks() -> list[tuple[str, str, str]]:
    out = [
        check_bin("python3", "python3", ["--version"]),
        check_bin("mingw g++", "x86_64-w64-mingw32-g++", ["--version"]),
        check_bin("mingw gcc", "x86_64-w64-mingw32-gcc", ["--version"]),
        check_bin("mingw ar", "x86_64-w64-mingw32-ar", ["--version"]),
    ]
    wr = which("x86_64-w64-mingw32-windres")
    out.append(
        (
            "ok" if wr else "skip",
            "mingw windres",
            wr or "optional (icon resource)",
        )
    )
    return out


def linux_checks(need_webview: bool) -> list[tuple[str, str, str]]:
    out = [check_bin("python3", "python3", ["--version"])]
    cxx = "c++" if which("c++") else ("clang++" if which("clang++") else "")
    if not cxx:
        out.append(("missing", "C++ compiler", "need c++ or clang++"))
    else:
        out.append(check_bin("C++ compiler", cxx, ["--version"]))
    out.append(check_bin("pkg-config", "pkg-config", ["--version"]))
    gtk = run_ok(["pkg-config", "--exists", "gtk4"])
    out.append(
        (
            "ok" if gtk else "missing",
            "gtk4",
            "pkg-config --exists gtk4" if gtk else "install libgtk-4-dev",
        )
    )
    if need_webview:
        wv = run_ok(["pkg-config", "--exists", "webkitgtk-6.0"])
        out.append(
            (
                "ok" if wv else "missing",
                "webkitgtk-6.0",
                "pkg-config --exists webkitgtk-6.0"
                if wv
                else "install libwebkitgtk-6.0-dev",
            )
        )
    return out


def run_doctor(target: str, need_webview: bool, lane: str = "product") -> bool:
    checks: list[tuple[str, str, str]] = []

    pack = ROOT / "scripts" / "xu_desktop_pack.py"
    host = ROOT / "src" / "ui" / "host"
    if host.is_dir() and pack.is_file():
        checks.append(("ok", "xu repo root", str(ROOT)))
        checks.append(("ok", "xu_desktop_pack.py", str(pack)))
    else:
        checks.append(
            (
                "missing",
                "xu repo root",
                "need src/ui/host + scripts/xu_desktop_pack.py",
            )
        )

    xu_bin = find_xu_bin(lane)
    if xu_bin:
        checks.append(("ok", "xu binary (--emit-obj)", xu_bin))
    else:
        missing_detail = "need hosted bin/xu or developer/bin snapshot; set XU_COMPILER/XU_SEED"
        checks.append(
            (
                "missing",
                "xu binary (--emit-obj)",
                missing_detail,
            )
        )

    if target not in HOSTED:
        checks.append(("missing", "target", f"not a hosted desktop target: {target}"))
    elif target.startswith("macos-"):
        checks.extend(macos_checks(target))
    elif target.startswith("windows-"):
        if target != "windows-x64":
            checks.append(("missing", "target", "windows currently windows-x64 only"))
        else:
            checks.extend(windows_checks())
    elif target.startswith("linux-"):
        checks.extend(linux_checks(need_webview))

    print(f"xu doctor — desktop toolchain ({target}, lane={lane})")
    ok_all = True
    for tag, name, detail in checks:
        if tag == "missing":
            ok_all = False
        label = f"[{tag}]"
        print(f"  {label:9} {name:24} {detail}")
    if ok_all:
        print("summary: ready for desktop pack")
    else:
        print("summary: not ready — fix [missing] items, then retry")
    return ok_all


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Check host tools for Xu desktop oneexe packing (scripts/, not bootstrap)."
    )
    ap.add_argument(
        "--target",
        default=None,
        help="macos-arm64|macos-x64|windows-x64|linux-x64|linux-arm64",
    )
    ap.add_argument(
        "--desktop",
        action="store_true",
        help="explicit desktop probe (default behaviour; kept for clarity)",
    )
    ap.add_argument(
        "--webview",
        action="store_true",
        help="also require WebView deps (Linux webkitgtk)",
    )
    ap.add_argument("--lane", choices=("product",), default="product")
    args = ap.parse_args()
    lane = args.lane
    target = args.target or default_target()
    if target not in HOSTED and not target.startswith(("macos-", "linux-", "windows-")):
        print(f"xu doctor: unknown or freestanding target {target}", file=sys.stderr)
        raise SystemExit(1)
    ok = run_doctor(target, args.webview, lane)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
