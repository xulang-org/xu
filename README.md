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
  <a href="https://xulang.org/benchmarks"><img src="https://img.shields.io/badge/Benchmarks-13%20Tasks-amber" alt="Benchmarks"></a>
  <a href="https://github.com/xulang-org/xu/actions/workflows/sdk.yml"><img src="https://github.com/xulang-org/xu/actions/workflows/sdk.yml/badge.svg" alt="SDK CI"></a>
</p>

<p align="center">
  <a href="https://xulang.org">🌐 <b>Online Playground (No Install)</b></a> &nbsp;•&nbsp;
  <a href="https://xulang.org/benchmarks">⚡ <b>13-Task Benchmark Dashboard</b></a> &nbsp;•&nbsp;
  <a href="#-zero-friction-quick-start">🚀 <b>30s Quick Start</b></a> &nbsp;•&nbsp;
  <a href="https://github.com/xulang-org/xu/releases">📦 <b>Download Installers</b></a>
</p>

---

## Xu 0.9.4

Xu 0.9.4 is a compiler consistency and optimizer release:

- **Borrow Checking Soundness**: The borrow checker now walks every expression kind (with a conservative fallback for unknown kinds), so aliasing such as `f(mut &v, &v)` is reported even when nested inside casts or arithmetic; borrows taken inside a loop now stay live across the back edge. Programs that previously compiled only because of these gaps now receive a diagnostic.
- **Generics and Type Table Limits**: Generic declarations are no longer limited to four type parameters, type-id range overflow is asserted instead of silently wrapping, and backends that do not support a requested target fail explicitly.
- **MIR Verification**: `XU_VERIFY=1` runs the full MIR verifier after every optimization pass; mismatches between the verifier, lowering and the backend were fixed. `XU_DUMP_MIR=<fn>` dumps a function's MIR.
- **SSA Loop Optimization**: Scalar SSA promotion no longer depends on a per-shape whitelist, and the ARM64 loop kernels (scan, saxpy, CRC, binary search, fill, stride, predicated scan) have SSA-based matchers. Loops bounded by an `[]int` length are rotated so they qualify. Measured speedups versus 0.9.3 include `bloom_filter` ~12%, `chase_index` 9-11%, `f64_sum` ~8% and `algorithm_search` ~9% at `-O3`, with no regressions and slightly faster self-compilation.
- **Pattern Diagnostics**: `--timings` reports `pattern-hits:` and per-function register-allocation mode; `XU_PATTERNS_OFF` disables named backend patterns for differential testing (`scripts/pattern_diff.sh`).

Download the [0.9.4 SDK and installers](https://github.com/xulang-org/xu/releases/tag/v0.9.4). The [benchmark dashboard](https://xulang.org/benchmarks) retains each measurement's actual compiler version and provenance.

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

Jump directly into the **[xulang.org Online Playground](https://xulang.org)**. Powered by a client-side WebAssembly build of Xu, you can test and experiment with full language features instantly.

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

### CLI Command Quick Reference

| Command | Description |
| :--- | :--- |
| `xu run <file.xu>` | Rapid compilation and in-memory execution |
| `xu build <file.xu> -o <bin>` | AOT compile to an optimized, standalone native binary |
| `xu build --target wasm32 <file.xu>` | Cross-compile directly to WebAssembly |
| `xu test <file.xu>` | Execute integrated unit tests and assertion suites |
| `xu get <module>@<version>` | Add or update a dependency, install it, and update `xu.lock` |
| `xu install [dir]` | Install the dependencies already declared in `xu.xun` |
| `xu fmt <file.xu> -w` | Automatically format code according to official guidelines |
| `xu doc <dir> --public` | Extract doc comments and generate clean API references |
| `xu doctor` | Diagnostics tool checking native C linkers and SDK health |

In a project with `xu.xun`, run `xu get github.com/xulang-org/packages@v0.1.1`
to add or update the root module under `require:` and install its dependency
graph into `vendor/`. An explicit version is required; `@latest`, version ranges,
and package subpath discovery are not supported. `--offline` uses verified local
cache/vendor data. Failed resolution or installation preserves the project's
manifest, lock file, and vendor directory. `--frozen` rejects dependency changes.

---

## 🗺️ Project Roadmap

Driven by continuous active iteration, Xu is rapidly evolving. Here is our current status and roadmap:

- [x] **Static Native AOT Compilation**: Direct emission of optimized machine code with fixed-point bootstrap verification (`Gen2 == Gen3`)
- [x] **Compile-Time Ownership & Borrow Inference**: Zero-GC runtime, deterministic deallocation, eliminating dangling pointers
- [x] **Native Coroutines & Channels**: `xu` keyword scheduling paired with typed `chan` communication
- [x] **Symbolic Flow & Error Handling**: `<<` return, `>>` throw, and mandatory local `or (err) { ... }` guards
- [x] **Universal Architecture Support**: Windows / macOS / Linux / LoongArch64 / RISC-V 64 / WebAssembly
- [x] **Standalone Native Setup Wizards**: Zero-dependency self-rendered GUI wizards for Windows / macOS PKG / Linux installers
- [x] **Production Infrastructure Packages**: Native drivers for MySQL, Postgres, Redis, ClickHouse, Kafka, SQLite, etc.
- [ ] **Language Server Protocol (LSP)**: Deep VS Code & Neovim integration with real-time diagnostics and autocompletion
- [ ] **Interactive Source Debugger**: Native breakpoint debugging, stack unwinding, and variable inspection
- [ ] **Deep Monomorphization & Inlining Optimizations**: Cross-module automatic inlining and enhanced escape analysis
- [ ] **Central Package Registry**: Cryptographically verified package distribution and automated dependency resolution

---

## 🌟 Join the Community & Support Xu

Xu is an open-source, forward-looking systems programming language. If you believe in **Zero-GC extreme performance combined with ergonomic modern syntax**, we invite you to join us!

- ⭐ **Star the Repo**: If Xu resonates with your engineering philosophy, give us a **Star** on [GitHub](https://github.com/xulang-org/xu)—it fuels our development!
- 💬 **Feedback & Discussions**: Have feature requests or suggestions? Open a discussion or ticket on [GitHub Issues](https://github.com/xulang-org/xu/issues).
- 📊 **Benchmark Insights**: Explore deep CPU and memory benchmarks across 13 tasks at [xulang.org/benchmarks](https://xulang.org/benchmarks).
- 📚 **Comprehensive Documentation**: Read guides, syntax specifications, and tutorials at [xulang.org](https://xulang.org).

---

## License

The Xu programming language is open source under the [MIT License](LICENSE).
