<p align="center">
  <a href="https://xulang.org"><img src="brand/xu_classic.svg" alt="Xu Logo" width="100" height="100"></a>
</p>

<h1 align="center">The Xu Programming Language</h1>

<p align="center">
  <b>Go-like Concurrency Meets C/Rust Zero-GC Performance</b><br>
  <sub>A compile-time memory-safe systems language engineered for high-throughput, low-latency, and modern applications.</sub>
</p>

<p align="center">
  <b>English</b> | <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <a href="https://github.com/xulang-org/xu/releases"><img src="https://img.shields.io/github/v/release/xulang-org/xu?label=Release&color=0284c7" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-emerald.svg" alt="License"></a>
  <a href="https://xulang.org"><img src="https://img.shields.io/badge/Docs-xulang.org-rose" alt="Docs"></a>
  <a href="https://xulang.org/benchmarks"><img src="https://img.shields.io/badge/Benchmarks-72%20Workloads-amber" alt="Benchmarks"></a>
  <a href="https://github.com/xulang-org/xu/actions/workflows/sdk.yml"><img src="https://github.com/xulang-org/xu/actions/workflows/sdk.yml/badge.svg" alt="SDK CI"></a>
</p>

<p align="center">
  <a href="https://xulang.org">🌐 <b>Online Playground (No Install)</b></a> &nbsp;•&nbsp;
  <a href="https://xulang.org/benchmarks">⚡ <b>72-Workload Benchmark Dashboard</b></a> &nbsp;•&nbsp;
  <a href="#-zero-friction-quick-start">🚀 <b>30s Quick Start</b></a> &nbsp;•&nbsp;
  <a href="RELEASES.md">📋 <b>Release Notes</b></a> &nbsp;•&nbsp;
  <a href="https://github.com/xulang-org/xu/releases">📦 <b>Download Installers</b></a>
</p>

---

> **Official SDK Downloads**: [GitHub Releases](https://github.com/xulang-org/xu/releases) — See [Release Notes](RELEASES.md) for full changelog, breaking changes, and migration details.

## ⚡ Xu at a Glance (Show, Don't Tell)

No complex boilerplate. No convoluted lifetime annotation gymnastics. Experience Xu's clean modern syntax in 15 lines of code:

```xu
@main
#errors

// Symbolic flow control: `<<` returns, `>>` throws; no nested Result/unwrap boilerplate
fn fetch_metric(task string) int {
    if task.len == 0 { >> errors.new("empty task name") }
    << task.len * 42
}

fn worker(task string, ch chan int) {
    val := fetch_metric(task) or (err) { << } // Mandatory safe local handling without `if err != nil`
    ch <- val                                 // Type-safe channel messaging
}

fn main() int {
    ch := chan int{cap: 2}
    xu worker("latency", ch) // Native `xu` keyword spawns lightweight coroutine
    xu worker("memory", ch)
    println(<-ch + <-ch)     // Fan-in channel aggregation
    << 0                     // Deterministic teardown, zero GC pauses, static AOT native build
}
```

> **Why Developers Love It**:
> 1. **Symbolic Flow Control**: `<<` returns, `>>` throws, `<<<` exits. Goodbye verbose legacy keywords.
> 2. **Ergonomic Error Flow**: Handled at the call site with `or (err) { ... }`. Eliminates screen-cluttering `if err != nil` and catastrophic runtime `unwrap()` panics.
> 3. **Native Lightweight Concurrency**: `xu worker()` coroutines + `chan` channels provide effortless Go-like concurrency.
> 4. **Compile-time Static Safety**: Tracked via ownership & borrow inference. **Zero garbage collection (Zero-GC)**, zero pauses, and ultra-lean deterministic memory consumption.

A writable reference name `r: $&T` can satisfy an `&T` expectation: write
`read(r)` or `let view: &T = r`. The shared view keeps the parent frozen against
conflicting writes and moves through its last use, including stored views and
call results. Conflicting shared and writable arguments in one call are rejected.
Implicit downgrade currently requires a local reference name and the identical
direct pointee type. Declare a mutable binding once with `$x := value` (or
`let $x: T = value`); use plain `x` afterward. Ordinary values need `&x` for a
shared borrow or `$&x` for a writable borrow, whose reference type is `$&T`.
Reuse reference names as `r`, or write `&*r` for an explicit reborrow.
Automatic borrowing from ordinary values is not implemented.

See [Borrowing and mutable bindings](https://xulang.org/docs/lang/memory/) for the current rules.

---

## 🎯 Pain Points & "Why Xu?"

As software engineers building high-performance systems and services, we are constantly forced to choose between flawed trade-offs:

### 1. The Dilemmas We Solve

- **Pain Point 1: Garbage Collection Latency Spikes & Memory Bloat**
  - *Status Quo*: Go and Java are productive, but GC pauses (STW) and unpredictable latency jitter are deal-breakers in low-latency gateways, trading engines, and embedded targets.
  - *The Xu Fix*: **Zero GC Runtime**. Pure AOT compilation. Ownership tracks memory at compile time and frees it deterministically on scope exit. Zero pauses, zero GC spikes.
- **Pain Point 2: The Battle with "Explicit Lifetime Annotation Hell"**
  - *Status Quo*: C/C++ leaves you vulnerable to dangling pointers, memory corruption, and UAF bugs. Rust is safe, but explicit lifetime parameters (`'a`, `'b`) and complex type gymnastics drastically slow down development speed.
  - *The Xu Fix*: **Implicit Ownership Inference & Borrow Checking**. No explicit lifetime annotations in application code. Natural value semantics for slices give you both safety and velocity.
- **Pain Point 3: Screen-Filling Boilerplate & Nested Error Wrappers**
  - *Status Quo*: Go codebases are flooded with repetitive `if err != nil`. Rust wraps types inside multiple `Result<T, E>` / `Option` layers.
  - *The Xu Fix*: **Symbolic `>>` combined with mandatory `or (err) { ... }`**, providing lightweight, clean, and safe error propagation.
- **Pain Point 4: Fragmented Toolchains & Setup Friction**
  - *Status Quo*: Stitching together CMake, Make, package managers, and platform linkers is notoriously fragile.
  - *The Xu Fix*: **Single-Binary Closed Loop**. Everything—compiler, test runner, formatter (`xu fmt`), documentation generator (`xu doc`), and self-rendered GUI setup wizards—is built right in.

### 2. Hardcore Technical Comparison

| Key Dimension | C / C++ | Go | Rust | **Xu** |
| :--- | :--- | :--- | :--- | :--- |
| **Memory Management** | Manual malloc/free<br>*(Leaks & dangling pointers)* | Runtime GC<br>*(STW latency pauses & memory bloat)* | Compile-time ownership<br>*(Explicit lifetime `'a` annotations)* | **Compile-time ownership<br>(Zero-GC / Deterministic drops)** |
| **Runtime Overhead** | Zero-cost abstractions | Heavy (GC engine + scheduler runtime) | Zero-cost abstractions | **Zero-cost (No GC engine / Pure native machine code)** |
| **Cognitive Load** | Vulnerable to UB & race conditions | Simple, but `nil` panics persist | Steep learning curve (Borrow checker fights) | **Minimal (No lifetime annotations / Clean symbolic flow)** |
| **Concurrency Model** | OS threads / External libraries | CSP coroutines (`go`) + channels (`chan`) | Threads / Async runtimes (Function coloring) | **Native lightweight coroutines (`xu`) + typed `chan`** |
| **Error Handling** | Error codes / Exceptions *(Implicit)* | `if err != nil` *(Cluttered boilerplate)* | `Result<T, E>` + `?` operator | **Symbolic flow: `>>` throw + `or` mandatory handling** |
| **Flow Control** | `return` / `break` / `continue` | `return` / `break` / `continue` | `return` / Tail expressions | **Symbolic flow: `<<` return / `>>` throw / `<-` break** |
| **Toolchain Cohesion**| Fragmented (CMake/Make/Conan) | Integrated out-of-the-box | Integrated (Cargo) | **Single-binary loop (Built-in build/test/fmt/doc)** |
| **Cross-Platform Setup**| Complex toolchain & linker dependencies | Official installer / manual PATH config | Requires rustup & external network scripts | **Standalone GUI Setup wizards / One-click setup** |

---

## 🚀 Zero-Friction Quick Start

### Option 1: Instant Browser Sandbox (Zero Install)

Jump directly into the **[xulang.org Online Playground](https://xulang.org/playground/)**. The client-side WebAssembly sandbox supports a subset of Xu, including basic types, control flow, structs, borrow diagnostics, and cooperative channel scheduling. See the playground's capability guide for its scope; real multithreading, network I/O, native C FFI, and desktop UI require the native SDK.

### Option 2: One-Liner Fast Install (Recommended)

Xu provides standalone installers with embedded compilers and standard library sources that automatically register persistent system environment variables:

- **macOS / Linux** (One command in terminal):
  ```bash
  # Detects architecture, downloads, and configures environment automatically
  curl -fsSL https://xulang.org/install.sh | bash
  ```
  *Or download standalone binaries from [Releases](https://github.com/xulang-org/xu/releases):*
  ```bash
  chmod +x xu-setup-linux-x64 && ./xu-setup-linux-x64 -y
  ```

- **Windows** (GUI Wizard or PowerShell):
  - **GUI Wizard**: Download `xu-setup-windows-x64.exe` from [Releases](https://github.com/xulang-org/xu/releases) and double-click to run the zero-dependency self-rendered wizard.
  - **ARM64 console installer**: Download `xu-setup-windows-arm64.exe` from [Releases](https://github.com/xulang-org/xu/releases) and run `.\xu-setup-windows-arm64.exe --yes` in PowerShell.
  - SDK installers declare current-user execution and can start from a normal terminal. Installing for all users still requires administrator privileges.
  - **PowerShell One-Liner**:
    ```powershell
    irm https://xulang.org/install.ps1 | iex
    ```

> Open a new terminal and type `xu --version` to run from anywhere.

### Option 3: 30-Second Hello World

```bash
# 1. Create source file
cat << 'EOF' > main.xu
@main

fn main() int {
    println("Hello, World! Welcome to Xu.")
    << 0
}
EOF

# 2. Run immediately
xu run main.xu

# 3. Compile ahead-of-time to an optimized native binary
xu build main.xu -o myapp
./myapp
```

### Documentation

- [Getting started](https://xulang.org/docs/start/)
- [CLI reference](https://xulang.org/docs/cli/), including optimization, testing, and XACP
- [Standard library and package API](https://xulang.org/api/)
- [Native modules and borrowed spans](https://xulang.org/docs/native/)

The documentation and API source live in [xulang-org/xulang-org](https://github.com/xulang-org/xulang-org).

---

## Phone applications (development)

Based on Xu 0.12.3, the Phone development toolchain adds native ARM64 iOS,
iOS Simulator and Android application generation:

```sh
xu build app/ --phone --target ios-simulator-arm64 --bundle-id org.example.app -o build/ios
xu build app/ --phone --target android-arm64 --bundle-id org.example.app -o build/android
```

Each output contains a platform build script and a compiled Xu application object.
The `#ui/phone` design layer includes touch targets, bottom navigation, adaptive
scaffolds, cards, grouped rows and bottom sheets. The UI profile renders Draw frames in a local system WebView Canvas;
full native IME and desktop service parity remain outside this profile.
See [Phone prerequisites and boundaries](src/ui/host/phone/README.md) and the
[mobile design gallery](examples/phone_gallery/README.md). This feature is not in the
original 0.12.3 release binary.

---

## 🗺️ Project Roadmap

The published SDK is the baseline for this roadmap. See [Status & Limitations](https://xulang.org/docs/status/) for target-specific runtime boundaries.

- [x] **Pure Xu Self-Hosting and Native AOT**: Bootstrap from a published Xu SDK, verify a fixed point, and directly emit native machine code and WebAssembly
- [x] **Compile-Time Ownership and Borrow Inference**: Deterministic resource cleanup; 0.9.4 completes checking for nested expressions and loop back edges
- [x] **Native Coroutines & Channels**: `xu` keyword scheduling paired with typed `chan` communication; 100/100 multi-task select concurrency gate closed
- [x] **Cryptographic Suite Completeness**: SM2/SM3/SM4/SM9 full-suite conformance; SM9 pairing stack frame reduced by 71.5% with zero compile warnings
- [x] **Symbolic Flow & Error Handling**: `<<` return, `>>` throw, and mandatory local `or (err) { ... }` guards
- [x] **Multi-Platform Code Generation**: Windows / macOS / Linux, ARM64 / x64 / LoongArch64 / RISC-V, WASM, and bare-metal targets
- [x] **SDK Installation and Self-Updates**: Windows wizard, macOS PKG, cross-platform single-file Setup, and `xu up/update`
- [x] **Reproducible Module Dependencies**: `init/get/install`, MVS, locks/vendor, proxies, offline/frozen builds, and a trusted-key checksum client
- [x] **LSP and Editor Integration**: `xu-lsp` and VS Code/Cursor extensions; diagnostics, completion, definitions, hover, symbols, references, rename, and formatting
- [x] **Generics and SSA Optimization Foundations**: Monomorphization without the four-type-parameter cap, scalar SSA promotion, ARM64 SSA loop kernels, and loop rotation
- [x] **Compiler Diagnostics and Verification**: Per-pass MIR verification, MIR dumps, pattern-hit counters, and named-pattern controls
- [x] **Infrastructure Packages**: The separate packages module provides 29 extensions including MySQL, Postgres, Redis, ClickHouse, Kafka, and SQLite
- [x] **Traceable Cross-Language Benchmarks**: 72 workloads on six ARM64/x86-64 platforms, retaining measured compiler versions, provenance, and output verification
- [x] **Integrated Interactive Source Debugger**: `xu debug` drives DWARF source breakpoints, call stacks, and typed local variable inspection via LLDB/GDB with non-interactive batch mode
- [x] **Further Optimizer Expansion**: Deeper SSA scalar promotion with struct-record admission proofs, TVM-inspired tile planning, low-bit LUT-GEMM, and pipelined operator fusion
- [ ] **Complete Target-Machine Runtime Validation**: Native SDK installation gates cover macOS ARM64/x64, Linux ARM64/x64, and Windows x64/ARM64. Extend library, networking, concurrency, and desktop runtime checks on each target; LoongArch64 and RISC-V SDKs are cross-built.
- [ ] **Public Package Infrastructure**: Trusted-key checksum verification, MVS, and proxy/vendor clients are implemented. Public proxy/checksum services and independent witnesses require separate deployment and availability validation.

---

## 🌟 Join the Community & Support Xu

Xu is an open-source, forward-looking systems programming language. If you believe in **Zero-GC extreme performance combined with ergonomic modern syntax**, we invite you to join us!

- ⭐ **Star the Repo**: If Xu resonates with your engineering philosophy, give us a **Star** on [GitHub](https://github.com/xulang-org/xu)—it fuels our development!
- 💬 **Feedback & Discussions**: Have feature requests or suggestions? Open a discussion or ticket on [GitHub Issues](https://github.com/xulang-org/xu/issues).
- 📊 **Benchmark Insights**: Explore deep CPU and memory benchmarks across 72 workloads at [xulang.org/benchmarks](https://xulang.org/benchmarks).
- 📚 **Comprehensive Documentation**: Read guides, syntax specifications, and tutorials at [xulang.org](https://xulang.org).

---

## License

The Xu programming language is open source under the [MIT License](LICENSE).
