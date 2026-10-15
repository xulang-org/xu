<p align="center">
  <a href="https://xulang.org"><img src="brand/xu_classic.svg" alt="Xu Logo" width="100" height="100"></a>
</p>

<h1 align="center">The Xu Programming Language</h1>

<p align="center">
  <b>English</b> | <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <a href="https://github.com/xulang-org/xu/releases"><img src="https://img.shields.io/github/v/release/xulang-org/xu?include_prereleases&label=release" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
  <a href="https://xulang.org"><img src="https://img.shields.io/badge/docs-xulang.org-rose" alt="Docs"></a>
</p>

Xu is a statically-typed, native AOT-compiled, GC-free modern systems programming language that manages memory through compile-time ownership and borrow checking. The SDK provides the compiler, developer toolchain, standard library, and official examples. You can extract and run immediately or install globally via standalone native Setup installers.

For current source version, see [VERSION](VERSION). Published releases are determined by [GitHub Releases](https://github.com/xulang-org/xu/releases) and the in-bundle `VERSION`; `TARGET` records the target platform, and `bundle.json` records provenance and SHA-256 binary digests.

- [Official Website & WebAssembly Playground](https://xulang.org)
- [47 Cross-Language Benchmarks Across Dual Architectures](https://xulang.org/benchmarks)
- [Installed SDK CI Workflows](https://github.com/xulang-org/xu/actions/workflows/sdk.yml)
- [Issues & Discussions](https://github.com/xulang-org/xu/issues)

## Releases and Channels

Xu and its compiler share a unified semantic version number: debug development builds use `0.8.8-dev.1`, `0.8.8-dev.2`; release candidates use `0.8.8-rc.1`; and verified general-availability releases use `0.8.8`. Pre-release versions advance the suffix counter until the next stable release cycle.

On GitHub, dev and rc builds are marked as **Pre-release**. By default, `xu update` tracks stable releases; pass `--version 0.8.8-dev.1` to install a specific development build. Existing tags and releases are immutable. Note that current stable releases belong to the `0.8.x` series and do not imply language `1.0` stability.

Version maintenance scripts:

```bash
# Start a new dev cycle from stable, e.g. 0.8.8 → 0.8.8-dev.1
python3 scripts/module_versions.py --release-bump patch --channel dev
# Advance counter within the same channel: dev.1 → dev.2, or rc.1 → rc.2
python3 scripts/module_versions.py --next-prerelease
# dev.N → rc.1
python3 scripts/module_versions.py --promote rc
# rc.N → matching stable release, executed only after full validation
python3 scripts/module_versions.py --promote stable
```

## Download SDK & Setup Installers

Download native Setup installers, SDK archives, and `SHA256SUMS` from [GitHub Releases](https://github.com/xulang-org/xu/releases). All releases provide standalone offline Setup packages with embedded compiler, tools, and standard library sources that automatically register persistent system environment variables.

| Operating System / CPU | Platform Target | Recommended Setup Installer (Self-contained) | Full SDK Source Archive |
| --- | --- | --- | --- |
| Windows / x86-64 | `windows-x64` | `xu-v<version>-windows-x64-setup.exe` (Double-click GUI wizard) | `xu-v<version>-windows-x64.zip` |
| Windows / ARM64 | `windows-arm64` | `xu-v<version>-windows-arm64-setup.exe` | `xu-v<version>-windows-arm64.zip` |
| macOS / Apple Silicon | `macos-arm64` | `xu-v<version>-macos-arm64.pkg` (Double-click GUI wizard) or `xu-setup-macos-arm64` | `xu-v<version>-macos-arm64.tar.gz` |
| macOS / Intel | `macos-x64` | `xu-setup-macos-x64` | `xu-v<version>-macos-x64.tar.gz` |
| Linux / x86-64 | `linux-x64` | `xu-setup-linux-x64` (Run `chmod +x xu-setup-linux-x64 && ./xu-setup-linux-x64 -y`) | `xu-v<version>-linux-x64.tar.gz` |
| Linux / ARM64 | `linux-arm64` | `xu-setup-linux-arm64` | `xu-v<version>-linux-arm64.tar.gz` |
| Linux / LoongArch64 | `linux-loongarch64` | `xu-setup-linux-loongarch64` | `xu-v<version>-linux-loongarch64.tar.gz` |
| Linux / RISC-V 64 | `linux-riscv64` | `xu-setup-linux-riscv64` | `xu-v<version>-linux-riscv64.tar.gz` |
| WebAssembly | `wasm32` | Built-in AOT target (`xu build --target wasm32 app.xu`) | No external packages required |

Releases also provide canonical alias binaries (e.g. `xu-setup-windows-x64.exe`).

## Verification & Extraction

Run in the directory containing the download archive and `SHA256SUMS`.

macOS:

```bash
shasum -a 256 -c SHA256SUMS
tar -xzf xu-v0.8.8-macos-arm64.tar.gz
cd xu-v0.8.8
```

Linux (x86-64):

```bash
sha256sum -c SHA256SUMS
tar -xzf xu-v0.8.8-linux-x64.tar.gz
cd xu-v0.8.8
```

Windows (PowerShell, x64):

```powershell
Get-FileHash .\xu-v0.8.8-windows-x64.zip -Algorithm SHA256
Expand-Archive .\xu-v0.8.8-windows-x64.zip -DestinationPath .
Set-Location .\xu-v0.8.8
```

## SDK Structure

| Path | Description |
| --- | --- |
| `bin/` | `xu`, `xu-doctor`, `xu-fmt`, `xu-doc`, `xu-map`, `xu-desktop` (`.exe` on Windows) |
| `src/` | Standard library and runtime sources (required input for compilation) |
| `packages/` | Optional external packages from the [packages repository](https://github.com/xulang-org/packages) |
| `examples/` | Official tutorials and examples from the [examples repository](https://github.com/xulang-org/examples) |
| `include/` | Native C interface header `xu_native.h` |
| `xu-setup` / `xu-setup.exe` | Native standalone installer (zero-dependency, auto environment config) |
| `editors/` | Editor syntax highlighting and configuration assets |
| `install.sh` / `install.ps1` | Compatibility CI installation scripts |
| `env.sh` / `env.ps1` | Temporary shell environment activation scripts |
| `uninstall.sh` / `uninstall.ps1` | Uninstallation scripts |
| `LICENSE`, `README.md`, `VERSION`, `TARGET`, `bundle.json` | License, documentation, version, target, and checksum metadata |

VS Code extension is published separately at [vscode repository](https://github.com/xulang-org/vscode).

## Instant Evaluation (Without Global Install)

Activate the current shell within the extracted SDK directory:

macOS / Linux (Bash):

```bash
source ./env.sh
xu --version
xu run "$XU_ROOT/examples/01_hello/main.xu"
```

Windows (PowerShell):

```powershell
. .\env.ps1
xu --version
xu run "$env:XU_ROOT\examples\01_hello\main.xu"
```

The activation script configures `PATH`, `XU_ROOT`, `XU_STDLIB_ROOT`, and `XUPATH`.

## Native Setup Installers (Recommended for Global Use)

Xu provides standalone native Setup installers requiring zero Python, bash, or PowerShell execution policy changes.

### Windows

Download `xu-v<version>-windows-x64-setup.exe` or `xu-setup-windows-x64.exe`:
- **GUI Wizard**: Double-click to launch the native self-rendered wizard and complete setup with one click.
- **Silent CLI Install**:
  ```cmd
  xu-setup-windows-x64.exe -y
  ```

Automatically registers `bin` to `HKCU\Environment\Path` and sets `XU_ROOT`. Open a new terminal (CMD, PowerShell, or VS Code) to use `xu` globally.

### macOS

- **Official PKG**: Download `xu-v<version>-macos-arm64.pkg` and double-click to install into `/usr/local/xu` with `/etc/paths.d/xu` configured.
- **Unprivileged CLI**: Download `xu-setup-macos-arm64` (or run `./xu-setup` in SDK folder):
  ```bash
  chmod +x xu-setup-macos-arm64
  ./xu-setup-macos-arm64 -y
  ```

### Linux

Download matching binary `xu-setup-linux-x64` (or `xu-setup-linux-arm64`) and run:

```bash
chmod +x xu-setup-linux-x64
./xu-setup-linux-x64 -y
```

Automatically unpacks and updates user shell profiles (`~/.bashrc` / `~/.zshrc`).

### Common Options

All native Setup installers support these flags:

```bash
# Custom prefix (default: ~/.xu or %USERPROFILE%\.xu)
./xu-setup --prefix "$HOME/my-xu" -y

# Force terminal CLI interactive mode (skips GUI wizard on Windows)
.\xu-setup.exe --cli

# Help
./xu-setup --help
```

## First Program

Create a UTF-8 encoded `main.xu` in your workspace:

```xu
@main

fn main() int {
    println("Hello, Xu!")
    << 0
}
```

```bash
xu check main.xu
xu run main.xu
xu build main.xu -o hello
```

On macOS / Linux run `./hello`; on Windows run `.\hello.exe`. Other commands:

```bash
xu fmt main.xu -w
xu test test_main.xu
xu doc . --public
xu map .
xu build --target wasm32 main.xu -o hello.wasm
xu build --debug-build main.xu
xu --help
```

Keep the full SDK folder structure intact so the compiler resolves standard library imports from `src/` beside `bin/`. Declare external packages in `xu.xun` under `github.com/xulang-org/packages`.

## License

The Xu project is open-source under the [MIT License](LICENSE).
