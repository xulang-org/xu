#!/usr/bin/env python3
"""Xu Programming Language — Cross-platform Development Environment Bundler.

Packages self-contained, production-grade SDK distribution archives for:
  - macos-arm64, macos-x64
  - linux-x64, linux-arm64, linux-loongarch64, linux-riscv64
  - windows-x64, windows-arm64
  - devkit-all (all-in-one multi-platform devkit)

Each bundle contains:
  1. bin/ (xu compiler + xu-doctor + xu-fmt + xu-doc + xu-map + xu-desktop)
  2. src/ (standard library + UI runtime host source)
  3. packages/ (optional external ecosystem drivers: redis, mysql, postgres, sqlite, etcd, etc.)
  4. include/ (C FFI header xu_native.h)
  5. editors/ (VS Code syntax & language extension vsix)
  6. examples/ (getting started examples)
  7. install.sh / install.ps1 (one-click offline & online installers)
  8. env.sh / env.ps1 (instant session environment activators)
  9. uninstall.sh / uninstall.ps1 (clean uninstallers)
 10. README.md, LICENSE, VERSION
"""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

from companion_repos import project_root, package_directories, vscode_package_files

REPO_ROOT = Path(__file__).resolve().parent.parent

SUPPORTED_TARGETS = [
    "macos-arm64",
    "macos-x64",
    "linux-x64",
    "linux-arm64",
    "linux-loongarch64",
    "linux-riscv64",
    "windows-x64",
    "windows-arm64",
]

SIBLING_TOOLS = [
    ("xu-doctor", "src/cmd/doctor"),
    ("xu-fmt", "src/cmd/fmt"),
    ("xu-doc", "src/cmd/doc"),
    ("xu-map", "src/cmd/map"),
    ("xu-desktop", "src/cmd/desktop"),
]


def get_host_target() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "darwin":
        os_name = "macos"
    elif system == "linux":
        os_name = "linux"
    elif system in ("windows", "msys", "cygwin"):
        os_name = "windows"
    else:
        os_name = "unknown"

    if machine in ("x86_64", "amd64"):
        arch_name = "x64"
    elif machine in ("arm64", "aarch64"):
        arch_name = "arm64"
    elif machine == "loongarch64":
        arch_name = "loongarch64"
    elif machine == "riscv64":
        arch_name = "riscv64"
    else:
        arch_name = machine

    return f"{os_name}-{arch_name}"


def read_version() -> str:
    version_file = REPO_ROOT / "VERSION"
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    raise FileNotFoundError(f"missing release VERSION: {version_file}")


def compute_sha256(file_path: Path) -> str:
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


def validate_binary(path: Path, target: str) -> None:
    """Reject placeholders and wrong-OS/ISA executables without a runner."""
    with path.open("rb") as source:
        header = source.read(64)
        if target.startswith("windows-") and header[:2] == b"MZ" and len(header) == 64:
            source.seek(struct.unpack_from("<I", header, 60)[0])
            pe = source.read(6)
            machine = {"windows-x64": 0x8664, "windows-arm64": 0xAA64}[target]
            if len(pe) == 6 and pe[:4] == b"PE\0\0" and struct.unpack_from("<H", pe, 4)[0] == machine:
                return
        elif target.startswith("linux-") and len(header) >= 20 and header[:6] == b"\x7fELF\x02\x01":
            machine = {"linux-x64": 62, "linux-arm64": 183, "linux-riscv64": 243, "linux-loongarch64": 258}[target]
            if struct.unpack_from("<H", header, 18)[0] == machine:
                return
        elif target.startswith("macos-") and len(header) >= 8 and header[:4] == b"\xcf\xfa\xed\xfe":
            cpu = {"macos-x64": 0x01000007, "macos-arm64": 0x0100000C}[target]
            if struct.unpack_from("<I", header, 4)[0] == cpu:
                return
    raise ValueError(f"Executable does not match {target}: {path}")


def build_environment() -> dict[str, str]:
    env = os.environ.copy()
    env["XUPATH"] = ""
    env["XU_STDLIB_ROOT"] = str(REPO_ROOT / "src")
    for key in ("XUOS", "XUARCH", "XU_BOOT_EXTRA", "XU_HEAP_STATS"):
        env.pop(key, None)
    return env


def ensure_compiler_built(xu_bin: Path, target: str, cache_dir: Path) -> None:
    if target == get_host_target():
        return
    output = cache_dir / target / ("xu.exe" if target.startswith("windows-") else "xu")
    if not output.is_file():
        output.parent.mkdir(parents=True, exist_ok=True)
        main = REPO_ROOT / "src/cmd/compile/main.xu"
        sources = [main] + [p for p in sorted(main.parent.glob("*.xu")) if p != main]
        print(f"  [cross-compile] Building xu for {target}...")
        result = subprocess.run([str(xu_bin), "build", *map(str, sources), "--target", target, "-o", str(output)],
                                cwd=REPO_ROOT, env=build_environment(), capture_output=True)
        if result.returncode:
            output.unlink(missing_ok=True)
            raise RuntimeError(f"Failed to build xu for {target}: {result.stderr.decode(errors='replace')}")
    validate_binary(output, target)


def ensure_tool_built(xu_bin: Path, target: str, tool_name: str, src_dir: str, cache_dir: Path) -> Path:
    """Ensures sibling tool is built for the given target."""
    is_windows = target.startswith("windows")
    exe_suffix = ".exe" if is_windows else ""
    target_tool_name = f"{tool_name}{exe_suffix}"
    cached_tool = cache_dir / target / target_tool_name

    if cached_tool.exists() and cached_tool.stat().st_size > 0:
        validate_binary(cached_tool, target)
        return cached_tool

    cached_tool.parent.mkdir(parents=True, exist_ok=True)
    # Otherwise cross-compile with xu
    print(f"  [cross-compile] Building {tool_name} for {target}...")
    cmd = [
        str(xu_bin),
        "build",
        str(REPO_ROOT / src_dir),
        "--target",
        target,
        "-o",
        str(cached_tool),
    ]
    run_res = subprocess.run(cmd, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=build_environment())
    if run_res.returncode != 0:
        cached_tool.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to build {tool_name} for {target}: {run_res.stderr.decode(errors='replace')}")

    # Windows may emit .exe; promote to the unsuffixed tool name.
    exe_file = Path(f"{cached_tool}.exe")
    if exe_file.exists() and not cached_tool.exists():
        shutil.move(exe_file, cached_tool)
    cached_tool.chmod(0o755)
    validate_binary(cached_tool, target)
    return cached_tool


def assemble_bundle_dir(target: str, stage_dir: Path, xu_bin: Path, cache_dir: Path, version: str):
    """Assembles all files into stage_dir for the given target."""
    is_windows = target.startswith("windows")
    bin_dir = stage_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    # 1. Compiler binary
    xu_target_name = "xu.exe" if is_windows else "xu"
    cached_xu = cache_dir / target / xu_target_name
    target_xu = xu_bin if target == get_host_target() else cached_xu
    if not target_xu.exists():
        target_xu = REPO_ROOT / "bin" / "platform" / target / xu_target_name
    if not target_xu.exists():
        # Fallback to bin/xu or developer/bin
        dev_xu = REPO_ROOT / "developer" / "bin" / f"xu.{target.replace('-', '.')}{'.exe' if is_windows else ''}"
        if dev_xu.exists():
            target_xu = dev_xu
        elif target == get_host_target():
            target_xu = xu_bin

    if not target_xu.exists():
        raise FileNotFoundError(f"Missing compiler binary for target {target}: {target_xu}")

    validate_binary(target_xu, target)
    shutil.copy2(target_xu, bin_dir / xu_target_name)
    (bin_dir / xu_target_name).chmod(0o755)

    # 2. Sibling tools
    for tool_name, src_dir in SIBLING_TOOLS:
        built_tool = ensure_tool_built(xu_bin, target, tool_name, src_dir, cache_dir)
        dest_name = f"{tool_name}.exe" if is_windows else tool_name
        shutil.copy2(built_tool, bin_dir / dest_name)
        (bin_dir / dest_name).chmod(0o755)

    # 3. Standard Library (src/)
    dest_src = stage_dir / "src"
    dest_src.mkdir(parents=True, exist_ok=True)
    for sub in sorted(p.name for p in (REPO_ROOT / "src").iterdir() if p.is_dir()):
        src_sub = REPO_ROOT / "src" / sub
        if src_sub.exists():
            shutil.copytree(
                src_sub,
                dest_src / sub,
                ignore=shutil.ignore_patterns("*.xin", "*.o", "*.a", "*.obj", "*.xulib", "*.lib", "*.so", "*.so.*", "*.dll", "*.dylib", ".DS_Store", "__pycache__"),
            )

    # 4. Drivers & Packages (packages/)
    dest_packages = stage_dir / "packages"
    packages_source = project_root("packages")
    if os.environ.get("XU_PACKAGES_ROOT") and not packages_source.is_dir():
        raise FileNotFoundError(f"XU_PACKAGES_ROOT does not exist: {packages_source}")
    if packages_source.is_dir():
        if (packages_source / "xu.xun").is_file():
            dest_packages.mkdir(parents=True, exist_ok=True)
            shutil.copy2(packages_source / "xu.xun", dest_packages / "xu.xun")
        for module in package_directories(packages_source):
            shutil.copytree(module, dest_packages / module.name,
                ignore=shutil.ignore_patterns("*.xin", "*.o", "*.a", "*.obj", "*.xulib", "*.lib", "*.so", "*.so.*", "*.dll", "*.dylib", ".DS_Store",
                    "__pycache__", ".git", ".pytest_cache", "docs", "reports", "notes", "tmp", "build"))

    # 5. C Native Headers (include/)
    dest_include = stage_dir / "include"
    if (REPO_ROOT / "include").exists():
        shutil.copytree(REPO_ROOT / "include", dest_include)

    # 6. Editors (VS Code)
    dest_editors = stage_dir / "editors"
    dest_editors.mkdir(parents=True, exist_ok=True)
    vscode_src = project_root("vscode")
    extension_files = vscode_package_files(vscode_src)
    if extension_files:
        dest_vscode = dest_editors / "vscode"
        dest_vscode.mkdir(parents=True, exist_ok=True)
        for source in extension_files:
            shutil.copy2(source, dest_vscode / source.name)

    # 7. Examples
    dest_examples = stage_dir / "examples"
    examples_src = project_root("examples") / "examples"
    if examples_src.exists():
        shutil.copytree(
            examples_src,
            dest_examples,
            ignore=shutil.ignore_patterns("*.xin", "*.exe", "*.o", "*.a", ".DS_Store"),
        )
        # Companion checkout paths have one more parent than installed examples.
        # Rebase only the official module locator; local example assets keep
        # their existing relative paths and the source checkout stays untouched.
        for manifest in dest_examples.rglob("xu.xun"):
            relative = os.path.relpath(dest_packages, manifest.parent).replace(os.sep, "/")
            text = manifest.read_text(encoding="utf-8")
            text = re.sub(r'(?m)^(\s*"?github\.com/xulang-org/packages"?\s*:\s*)file:[^\r\n]+',
                          lambda match: match[1] + "file:" + relative, text)
            manifest.write_text(text, encoding="utf-8")

    # 8. Scripts & Metadata
    scripts_to_copy = [
        "install.sh",
        "install.ps1",
        "uninstall.sh",
        "uninstall.ps1",
        "env.sh",
        "env.ps1",
    ]
    for script_name in scripts_to_copy:
        src_path = REPO_ROOT / "scripts" / script_name
        if src_path.exists():
            shutil.copy2(src_path, stage_dir / script_name)
            if script_name.endswith(".sh"):
                (stage_dir / script_name).chmod(0o755)

    for doc_name in ["README.md", "LICENSE", "VERSION"]:
        doc_path = REPO_ROOT / doc_name
        if doc_path.exists():
            shutil.copy2(doc_path, stage_dir / doc_name)

    # Generate custom README for the bundle
    bundle_readme = stage_dir / "README.md"
    bundle_readme_content = f"""# Xu Programming Language Development Environment (v{version})

Platform: **{target}**

Xu is a fast, safe, GC-free systems programming language combining Go-style tooling, Rust-style memory safety without garbage collection, and V-style clean syntax.

## Package Contents

- **`bin/`**: Complete CLI toolchain
  - `xu`: Compiler (`xu build`, `xu run`, `xu check`, `xu test`, etc.)
  - `xu-doctor`: Platform toolchain & desktop readiness diagnosis
  - `xu-fmt`: Fast source code formatter
  - `xu-doc`: Markdown API documentation generator & HTTP server
  - `xu-map`: Visual flowchart & architecture graph generator
  - `xu-desktop`: Cross-platform desktop native app & webview packager
- **`src/`**: Standard library source code (`#os`, `#io`, `#net`, `#crypto`, `#database/sql`, `#ui`, etc.)
- **`packages/`**: Optional external database, storage and messaging modules from the independent packages repository (when available at packaging time)
- **`include/`**: C ABI FFI headers (`xu_native.h`)
- **`editors/`**: Official Visual Studio Code extension (`xu-language-*.vsix`)
- **`examples/`**: Official hands-on example programs

## Quick Installation

### Unix (macOS / Linux):
```bash
./install.sh
```
Or specify a custom install directory:
```bash
./install.sh --prefix /opt/xu
```

### Windows (PowerShell):
```powershell
.\\install.ps1
```

### Instant Try (No System Modification):
- Unix: `source env.sh`
- Windows: `. .\\env.ps1`

## Verify Installation

```bash
xu --version
xu doctor
xu run examples/01_hello/main.xu
```

The compiler finds `src/` beside its own `bin/` directory. Activation also sets
`XU_STDLIB_ROOT` explicitly and preserves existing `XUPATH` entries. `XUPATH`
uses `:` on Unix and `;` on Windows, including when cross-compiling. Declare
external module identities in your application's `xu.xun` `require:` entries;
`XUPATH` does not replace those declarations. Bundled drivers are one module,
`github.com/xulang-org/packages`, whose local `file:` locator is the installed
`packages/` directory. Native FFI and desktop builds need their platform's
C/linker and UI SDK dependencies; `xu doctor` reports their availability.
External native libraries are built from their packaged sources on the target
platform; build outputs from the developer checkout are excluded from the SDK.
"""
    bundle_readme.write_text(bundle_readme_content, encoding="utf-8")


def package_tar_gz(source_dir: Path, output_file: Path, archive_root_name: str):
    """Packages directory into .tar.gz with normalized permissions."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output_file, "w:gz") as tar:
        tar.add(source_dir, arcname=archive_root_name)


def package_zip(source_dir: Path, output_file: Path, archive_root_name: str):
    """Packages directory into .zip."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_file, "w", zipfile.ZIP_DEFLATED) as zip_f:
        for root, _, files in os.walk(source_dir):
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(source_dir)
                zip_f.write(full_path, arcname=f"{archive_root_name}/{rel_path}")


def main():
    parser = argparse.ArgumentParser(description="Package cross-platform Xu development environment release bundles.")
    parser.add_argument("--target", choices=SUPPORTED_TARGETS + ["host"], help="Target platform to package")
    parser.add_argument("--all", action="store_true", help="Package all supported platforms")
    parser.add_argument("--bundle-devkit", action="store_true", help="Also build devkit-all universal archive")
    parser.add_argument("--out-dir", default="dist/release", help="Output directory for generated archives")
    parser.add_argument("--compiler", type=Path, help="Hosted compiler used to build the SDK (native host)")
    parser.add_argument("--lane", choices=("product", "oracle"), default="product", help="Evidence lane; oracle archives are CI diagnostics")
    args = parser.parse_args()

    version = read_version()
    host_target = get_host_target()
    out_dir = REPO_ROOT / args.out_dir
    stage_root = REPO_ROOT / "dist" / "staging"

    xu_bin = (args.compiler or REPO_ROOT / "bin" / ("xu.exe" if host_target.startswith("windows-") else "xu")).resolve()
    if not xu_bin.exists():
        print(f"Error: {xu_bin} not found. Please build xu first (make xu).", file=sys.stderr)
        sys.exit(1)
    validate_binary(xu_bin, host_target)
    from check_release_identity import xu_cli_version
    if xu_cli_version(xu_bin) != version:
        raise ValueError(f"Compiler version does not match VERSION ({version}): {xu_bin}")
    if args.lane == "product":
        from verify_product_provenance import verify
        report = subprocess.run([sys.executable, str(REPO_ROOT / "scripts/check_bootstrap_xu_boundary.py"),
                                 "--strict-freeze", "--json"], cwd=REPO_ROOT,
                                capture_output=True, text=True, check=True)
        closure = json.loads(report.stdout)["source_manifest"]
        if not closure["complete"]:
            raise ValueError("Product SDK requires a complete current source closure")
        verify(xu_bin, closure["closure_sha256"])
    else:
        sidecar = xu_bin.parent / "chain.env"
        values = dict(line.split("=", 1) for line in sidecar.read_text().splitlines() if "=" in line)
        if values.get("status") != "PASS" or values.get("lane") != "oracle" or values.get("gen4_sha256") != compute_sha256(xu_bin):
            raise ValueError("Oracle SDK requires a confirmed native oracle chain")
    # A tool cache is valid only for this compiler and this complete source tree.
    source_hash = hashlib.sha256()
    for source in sorted((REPO_ROOT / "src").rglob("*")):
        if source.is_file() and source.suffix in (".xu", ".xun", ".h", ".c", ".cc"):
            source_hash.update(source.relative_to(REPO_ROOT).as_posix().encode())
            source_hash.update(source.read_bytes())
    cache_dir = REPO_ROOT / "dist" / "tool_cache" / version / compute_sha256(xu_bin) / source_hash.hexdigest()

    targets_to_build = []
    if args.all:
        targets_to_build = SUPPORTED_TARGETS
    elif args.target:
        targets_to_build = [host_target if args.target == "host" else args.target]
    else:
        # Default to host target
        targets_to_build = [host_target]

    print("================================================================")
    print(f"Xu Development Environment Packaging (v{version})")
    print(f"Host: {host_target}")
    print(f"Targets: {', '.join(targets_to_build)}")
    print(f"Output: {out_dir}")
    print("================================================================")

    out_dir.mkdir(parents=True, exist_ok=True)
    generated_archives = []

    for target in targets_to_build:
        print(f"\n[Packaging] Building development environment bundle for {target}...")
        stage_dir = stage_root / target / f"xu-{version}"
        if stage_dir.exists():
            shutil.rmtree(stage_dir)
        stage_dir.mkdir(parents=True, exist_ok=True)

        ensure_compiler_built(xu_bin, target, cache_dir)
        assemble_bundle_dir(target, stage_dir, xu_bin, cache_dir, version)
        (stage_dir / "TARGET").write_text(target + "\n", encoding="utf-8")
        (stage_dir / "bundle.json").write_text(json.dumps({
            "schema": 1, "version": version, "target": target, "lane": args.lane,
            "binaries": {p.name: compute_sha256(p) for p in sorted((stage_dir / "bin").iterdir())},
        }, indent=2) + "\n", encoding="utf-8")

        archive_stem = f"xu-v{version}-{target}"
        if target.startswith("windows"):
            archive_file = out_dir / f"{archive_stem}.zip"
            print(f"  [archive] Creating ZIP: {archive_file.name}...")
            package_zip(stage_dir, archive_file, f"xu-v{version}")
        else:
            archive_file = out_dir / f"{archive_stem}.tar.gz"
            print(f"  [archive] Creating TAR.GZ: {archive_file.name}...")
            package_tar_gz(stage_dir, archive_file, f"xu-v{version}")

        size_mb = archive_file.stat().st_size / (1024 * 1024)
        sha256 = compute_sha256(archive_file)
        print(f"  [ok] {archive_file.name} ({size_mb:.2f} MB) - SHA256: {sha256[:12]}...")
        generated_archives.append((archive_file, target, size_mb, sha256))

    # Also build universal devkit if requested or if --all is specified
    if args.bundle_devkit or args.all:
        print(f"\n[Packaging] Building universal all-in-one DevKit archive...")
        devkit_stage = stage_root / "devkit-all" / f"xu-{version}-devkit"
        if devkit_stage.exists():
            shutil.rmtree(devkit_stage)
        devkit_stage.mkdir(parents=True, exist_ok=True)

        # Use host target as base structure
        assemble_bundle_dir(host_target, devkit_stage, xu_bin, cache_dir, version)

        # Every platform needs its own compiler AND sibling tools.
        bin_platform_dir = devkit_stage / "bin" / "platform"
        for target in SUPPORTED_TARGETS:
            ensure_compiler_built(xu_bin, target, cache_dir)
            platform_stage = stage_root / "devkit-platforms" / target
            if platform_stage.exists():
                shutil.rmtree(platform_stage)
            assemble_bundle_dir(target, platform_stage, xu_bin, cache_dir, version)
            shutil.copytree(platform_stage / "bin", bin_platform_dir / target)
        (devkit_stage / "bundle.json").write_text(json.dumps({
            "schema": 1, "version": version, "target": "devkit-all", "lane": args.lane,
            "platforms": SUPPORTED_TARGETS,
        }, indent=2) + "\n", encoding="utf-8")
        (devkit_stage / "TARGET").write_text("devkit-all\n", encoding="utf-8")

        devkit_archive = out_dir / f"xu-v{version}-devkit-all.tar.gz"
        print(f"  [archive] Creating TAR.GZ: {devkit_archive.name}...")
        package_tar_gz(devkit_stage, devkit_archive, f"xu-v{version}-devkit")
        size_mb = devkit_archive.stat().st_size / (1024 * 1024)
        sha256 = compute_sha256(devkit_archive)
        print(f"  [ok] {devkit_archive.name} ({size_mb:.2f} MB)")
        generated_archives.append((devkit_archive, "universal-devkit", size_mb, sha256))

    # Write SHA256SUMS
    sha_file = out_dir / "SHA256SUMS"
    with open(sha_file, "w", encoding="utf-8") as f:
        for archive, _, _, sha in generated_archives:
            f.write(f"{sha}  {archive.name}\n")
    print(f"\n[OK] Checksums saved to: {sha_file}")

    # Generate RELEASE_MANIFEST.md
    manifest_file = out_dir / "RELEASE_MANIFEST.md"
    with open(manifest_file, "w", encoding="utf-8") as f:
        f.write(f"# Xu v{version} 跨平台开发环境安装包发布清单\n\n")
        f.write(f"> 编译器版本: v{version}\n\n")
        f.write("## 📦 发行包列表\n\n")
        f.write("| 文件名 | 适用平台 / 架构 | 体积 | SHA-256 校验和 |\n")
        f.write("|--------|----------------|------|----------------|\n")
        for archive, target, size_mb, sha in generated_archives:
            f.write(f"| `{archive.name}` | `{target}` | {size_mb:.2f} MB | `{sha[:16]}...` |\n")
        f.write("\n## 🚀 包含核心组件\n\n")
        f.write("- **核心编译器与工具链 (`bin/`)**: `xu`, `xu-doctor`, `xu-fmt`, `xu-doc`, `xu-map`, `xu-desktop`\n")
        f.write("- **官方标准库源码 (`src/`)**: 包含 `os`, `io`, `net`, `sync`, `crypto`, `database/sql`, `ui` 等完整源码\n")
        f.write("- **独立 packages 仓库的扩展模块（选装） (`packages/`)**: `redis`, `mysql`, `postgres`, `sqlite`, `clickhouse`, `mongodb`, `nats`, `mqtt`, `etcd`, `elasticsearch`, `influxdb`, `memcached`, `s3`\n")
        f.write("- **C/C++ 原生交互头文件 (`include/`)**: `xu_native.h`\n")
        f.write("- **官方 IDE 插件 (`editors/`)**: VS Code 语法高亮与语言服务扩展 (`xu-language-*.vsix`)\n")
        f.write("- **开箱即用上手示例 (`examples/`)**: 官方示例集合\n")
        f.write("- **跨平台安装与卸载脚本**: `install.sh`, `install.ps1`, `uninstall.sh`, `uninstall.ps1`, `env.sh`, `env.ps1`\n\n")
        f.write("## 💡 一键安装指南\n\n")
        f.write(f"### macOS / Linux 离线安装\n```bash\ntar -xzf xu-v{version}-<target>.tar.gz\ncd xu-v{version}\n./install.sh\n```\n\n")
        f.write(f"### Windows 离线安装 (PowerShell)\n```powershell\nExpand-Archive xu-v{version}-windows-x64.zip\ncd xu-v{version}\n.\\install.ps1\n```\n\n")
        f.write("### 在线一键安装\n- **macOS / Linux**:\n  ```bash\n  curl -fsSL https://xulang.org/install.sh | bash\n  ```\n- **Windows (PowerShell)**:\n  ```powershell\n  irm https://xulang.org/install.ps1 | iex\n  ```\n")

    print(f"[OK] Release manifest saved to: {manifest_file}")
    print("\nAll packaging tasks completed successfully!")


if __name__ == "__main__":
    main()
