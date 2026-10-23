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
  <a href="https://xulang.org/benchmarks"><img src="https://img.shields.io/badge/Benchmarks-47%20Tasks-amber" alt="Benchmarks"></a>
  <a href="https://github.com/xulang-org/xu/actions/workflows/sdk.yml"><img src="https://github.com/xulang-org/xu/actions/workflows/sdk.yml/badge.svg" alt="SDK CI"></a>
</p>

<p align="center">
  <a href="https://xulang.org">🌐 <b>Online Playground (No Install)</b></a> &nbsp;•&nbsp;
  <a href="https://xulang.org/benchmarks">⚡ <b>47-Task Benchmark Dashboard</b></a> &nbsp;•&nbsp;
  <a href="#-zero-friction-quick-start">🚀 <b>30s Quick Start</b></a> &nbsp;•&nbsp;
  <a href="https://github.com/xulang-org/xu/releases">📦 <b>Download Installers</b></a>
</p>

---

## Xu 0.11.0-dev.1 development update

This development branch integrates the latest `main` and `arm32` work, then fixes standard library correctness and concurrency issues:

- HTTP servers dispatch complete requests concurrently. Idle and partial requests are polled with bounded connection, buffer and timeout limits. Handlers may now overlap; synchronize shared mutable state. `server_options()` supplies defaults for `serve_with_options`.
- Regexp matching uses explicit heap stacks and a work budget. **Migration:** matching, finding, splitting and replacement calls now require error handling, for example `matched := re.match_string(&text) or (err) { << 1 }`. Budget exhaustion reports an error; valid nonmatches retain their usual empty/false results. Expressions are limited to 65,536 bytes and 64 nested groups.
- DEFLATE writers now use bounded LZ77 matches with fixed Huffman codes and a stored-block fallback for incompressible data.
- JSON `as_int` and `as_f64` propagate conversion errors. Legacy `number_int` and `number_f64` retain their zero fallback; use the checked accessors when conversion must succeed.

This is a development source version; published installers remain on the releases page.

## Xu 0.10.1-dev.3

UI controls add a compatible `Styles` API while retaining the existing `Theme` and painting APIs.

- Dark, light and high-contrast palettes; global font family, weight, line height, text scale and control density; per-control font and palette overrides.
- Button radius, borders, padding, alignment, layered shadows and image icon placement, size and opacity; checkbox mark size, gap and stroke; rounded progress with disabled and error states.
- Input/TextArea selection foreground/background, placeholder, caret, preedit underline, hover, error and read-only states. Read-only controls retain selection/copy and release the native edit session.
- Styled scrollbars share painting and hit-test geometry, with thumb dragging, page clicks, keyboard and wheel support.
- `View.set_styles`, `set_style_scope` and `clear_style_scope` invalidate affected descendant repaint boundaries automatically. Palette changes reuse shaped text; font and geometry changes also remeasure controls. Local scopes are complete theme snapshots preserving explicit overrides.

Use `StyledLabel`, `set_style_measure`, `layout_styled` / `present_styled` for retained scenes. Call `mark_measure` after changing label text and `place_editor` after layout to update native IME geometry. `StyledPainter.overlay_styled` paints scrollbars after children. Shadows use a bounded approximation of up to eight layers. Applications switch themes explicitly; system menus/dialogs and WebView content use platform appearance and CSS respectively.


`ControlStyle.states` supports ordered `StatePaint` overrides for combined hover/press/focus/selected/disabled/error/read-only states, including foreground, border, selection, focus and icon opacity. Each rule declares a `when` mask, optional `unless` exclusions and the paint fields to override.

UI object builds reserve a separate coroutine stack budget for native font-library calls. Styled painting borrows themes instead of copying them at every tree level; the gallery drains input bursts before submitting a frame. Ordinary CLI task stacks keep their existing size.

## Xu 0.10.1-dev.2

Draw canvases keep their position by default on macOS, Windows and Linux. Drag and wheel events still reach the application; built-in camera panning requires explicit opt-in with `draw.set_pan_enabled(1)` after the canvas is ready.

This development version also adds:

- Persistent `widgets.input` / `widgets.text_area` controls with native text sessions, shaped selection/caret geometry, keyboard focus, multiline scrolling and asynchronous clipboard edits. Place editors after retained layout with `widgets.place_editor` before presenting.
- Per-window `MenuEntry` trees with submenus, separators, checked/disabled items and shortcuts, plus asynchronous `screens_async` snapshots. Screen results explicitly report coordinate units and whether primary/work-area information is known.
- Bounded WebView requests with unique IDs, cancellation, deadlines, window-generation ownership and UI-thread completion. `__XU__.invoke` supports `timeoutMs`, `AbortSignal` and `.cancel()`; scoped Xu callbacks use `bind_ipc_requests_www`. Eval/find/cookie requests finish through `ev_request`.

WebView limits are 64 outstanding dispatch leases, 1 MiB per invoke body and an 8 MiB shared body/result budget. Cancelling a running callback discards its response; its lease remains occupied until user code returns. Native query results are limited to 64 KiB. Windows editor hit testing requires real DirectWrite; older Wine builds return `E_NOTIMPL`.

## Xu 0.10.0 source update

This update adds the UI drawing and desktop foundations while retaining the compiler improvements from 0.9.4:

- Frame recording, reusable display lists, paths, image/text resources, layers, gradients and bounded caches.
- A retained layout tree with repaint boundaries, input routing, focus, scrolling and basic controls.
- Dynamic desktop windows and asynchronous clipboard, file-open, save-path and folder requests with cancellation and timeouts.
- Compiler-owned version identity for `xu env`, project initialization and update checks; downloaded compilers must match the requested version before installation.

These are source-development changes. Published installers remain available from the release link below.

## Xu 0.9.4

The source tree also retains the compiler consistency and optimizer work described below:

- **Borrow Checking Soundness**: The borrow checker now walks every expression kind (with a conservative fallback for unknown kinds), so aliasing such as `f(mut &v, &v)` is reported even when nested inside casts or arithmetic; borrows taken inside a loop now stay live across the back edge. Programs that previously compiled only because of these gaps now receive a diagnostic.
- **Generics and Type Table Limits**: Generic declarations are no longer limited to four type parameters, type-id range overflow is asserted instead of silently wrapping, and backends that do not support a requested target fail explicitly.
- **MIR Verification**: `XU_VERIFY=1` runs the full MIR verifier after every optimization pass; mismatches between the verifier, lowering and the backend were fixed. `XU_DUMP_MIR=<fn>` dumps a function's MIR.
- **SSA Loop Optimization**: Scalar SSA promotion no longer depends on a per-shape whitelist, and the ARM64 loop kernels (scan, saxpy, CRC, binary search, fill, stride, predicated scan) have SSA-based matchers. Loops bounded by an `[]int` length are rotated so they qualify. Measured speedups versus 0.9.3 include `bloom_filter` ~12%, `chase_index` 9-11%, `f64_sum` ~8% and `algorithm_search` ~9% at `-O3`, with no regressions and slightly faster self-compilation.
- **Pattern Diagnostics**: `--timings` reports `pattern-hits:` and per-function register-allocation mode; `XU_PATTERNS_OFF` disables named backend patterns for differential testing (`scripts/pattern_diff.sh`).

Published SDKs and installers are listed on the [releases page](https://github.com/xulang-org/xu/releases). The [benchmark dashboard](https://xulang.org/benchmarks) retains each measurement's actual compiler version and provenance.

The product self-host chain uses a verified hosted seed, hashes the source manifest,
and requires a fixed point between adjacent generations. The repository does not
claim a seed-free bootstrap from only the checked-in sources.

Coroutine calls are ownership boundaries: `xu` transfers owned values or uses
channels, while borrowed `&T` and `&mut T` values do not cross into another
coroutine. The `<-` token is context-sensitive by design: a statement form is
`break`, while an expression such as `<-ch` receives from a channel.

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

#### Projects and Dependencies

| Command | Description |
| :--- | :--- |
| `xu init [module]` | Create `xu.xun` in the current directory and a starter `main.xu` when missing |
| `xu get <module>@<version>` | Add or upgrade an exact dependency, install into `vendor/`, and update `xu.lock` |
| `xu install [dir]` | Install dependencies already declared in the project's `xu.xun` |
| `xu build . --frozen -o myapp` | Build offline using the existing lockfile and local dependencies |
| `xu env [var...]` | Inspect effective toolchain, standard-library, cache, and target settings |

In a project with `xu.xun`, run `xu get github.com/xulang-org/packages@v0.1.1`
to add or update the root module under `require:` and install its dependency
graph into `vendor/`. An explicit version is required; `@latest`, version ranges,
and package subpath discovery are not supported. `--offline` uses verified local
cache/vendor data. Failed resolution or installation preserves the project's
manifest, lock file, and vendor directory. `--frozen` rejects dependency changes.

#### Building, Running, and Verification

| Command | Description |
| :--- | :--- |
| `xu run <file.xu> -- <args...>` | Compile and launch a native program, forwarding arguments after `--` |
| `xu build <file.xu> -o <bin>` | AOT compile a native executable; project directories are also accepted |
| `xu check <file.xu>` | Parse and check types, ownership, and borrows without emitting machine code |
| `xu parse <file.xu>` | Parse source and print file, function, and declaration statistics |
| `xu test <file.xu> -v` | Run `fn test_*` tests with detailed results; filter with `-run <REGEXP>` |
| `xu test <file.xu> -bench <REGEXP>` | Run matching `fn bench_*` benchmark functions |
| `xu build <file.xu> --target linux-x64 -o app` | Cross-compile for an explicit target, such as Linux x64 |
| `xu build <file.xu> --target wasm32 -o app.wasm` | Emit a WebAssembly module |
| `xu build <AppDir> --desktop` | Package a desktop application using the required host UI SDK and tools |
| `xu build <file.xu> --debug -o app` | Emit DWARF line information; `--debug-build` also disables optimization |
| `xu build <file.xu> --timings -o app` | Report phase timings, optimization counters, pattern hits, and register-allocation modes |

0.9.4 also provides per-pass MIR verification with `XU_VERIFY=1`,
`XU_DUMP_MIR=<function>`, and differential pattern diagnostics with
`XU_PATTERNS_OFF=all`. See the [CLI reference](https://xulang.org/docs/cli/) for full options.

#### Development Tools and Toolchain Management

| Command | Description |
| :--- | :--- |
| `xu fmt <file.xu> -w` | Format source in place; omit `-w` to print to stdout |
| `xu doc <dir> --public` | Generate Markdown for public declarations; `--serve` starts a local documentation server |
| `xu map <dir> -o flow.md` | Generate a Mermaid source flowchart; `--graph` emits structured graph data |
| `xu doctor` | Check host tools; `--desktop --webview` checks desktop and WebView dependencies |
| `xu native <command> [options]` | Compile/archive C modules and pack, inspect, or extract `.xulib` slices |
| `xu lsp` | Start the stdio LSP server for VS Code, Cursor, Neovim, and other editors |
| `xu setup -y` | Install and configure the toolchain without interactive prompts |
| `xu up --check` | Check official releases; `xu up` and `xu update` are aliases |
| `xu update --version 0.9.4` | Install a specific official toolchain release |
| `xu --version` | Show the actual compiler version and host target |
| `xu help <command>` | Show subcommand help; `<command> --help` also works |

---

## 🗺️ Project Roadmap

This roadmap uses the **official 0.9.4 SDK** as its baseline. See [Status & Limitations](https://xulang.org/docs/status/) for target-specific runtime boundaries.

- [x] **Pure Xu Self-Hosting and Native AOT**: Bootstrap from a published Xu SDK, verify a fixed point, and directly emit native machine code and WebAssembly
- [x] **Compile-Time Ownership and Borrow Inference**: Deterministic resource cleanup; 0.9.4 completes checking for nested expressions and loop back edges
- [x] **Native Coroutines & Channels**: `xu` keyword scheduling paired with typed `chan` communication
- [x] **Symbolic Flow & Error Handling**: `<<` return, `>>` throw, and mandatory local `or (err) { ... }` guards
- [x] **Multi-Platform Code Generation**: Windows / macOS / Linux, ARM64 / x64 / LoongArch64 / RISC-V / ARM32, WASM, and bare-metal targets
- [x] **SDK Installation and Self-Updates**: Windows wizard, macOS PKG, cross-platform single-file Setup, and `xu up/update`
- [x] **Reproducible Module Dependencies**: `init/get/install`, MVS, locks/vendor, proxies, offline/frozen builds, and a trusted-key checksum client
- [x] **LSP and Editor Integration**: `xu-lsp` and VS Code/Cursor extensions; diagnostics, completion, definitions, hover, symbols, references, rename, and formatting
- [x] **Generics and SSA Optimization Foundations**: Monomorphization without the four-type-parameter cap, scalar SSA promotion, ARM64 SSA loop kernels, and loop rotation
- [x] **Compiler Diagnostics and Verification**: Per-pass MIR verification, MIR dumps, pattern-hit counters, and named-pattern controls
- [x] **Infrastructure Packages**: The separate packages module provides 29 extensions including MySQL, Postgres, Redis, ClickHouse, Kafka, and SQLite
- [x] **Traceable Cross-Language Benchmarks**: 47 workloads on six ARM64/x86-64 platforms, retaining measured compiler versions, provenance, and output verification
- [ ] **Integrated Interactive Source Debugger**: DWARF line output is available; continue the interactive breakpoint, call-stack, and variable-inspection workflow
- [ ] **Further Optimizer Expansion**: Deeper cross-module inlining, generic specialization, escape analysis, and loop/vector optimizations across more backends
- [ ] **Complete Target-Machine Runtime Validation**: Expand end-to-end coverage of standard libraries, networking, concurrency, and desktop UI on each platform
- [ ] **Public Package Infrastructure**: Central registry, public proxy/checksum-log services, independent witnesses, and version hosting

---

## 🌟 Join the Community & Support Xu

Xu is an open-source, forward-looking systems programming language. If you believe in **Zero-GC extreme performance combined with ergonomic modern syntax**, we invite you to join us!

- ⭐ **Star the Repo**: If Xu resonates with your engineering philosophy, give us a **Star** on [GitHub](https://github.com/xulang-org/xu)—it fuels our development!
- 💬 **Feedback & Discussions**: Have feature requests or suggestions? Open a discussion or ticket on [GitHub Issues](https://github.com/xulang-org/xu/issues).
- 📊 **Benchmark Insights**: Explore deep CPU and memory benchmarks across 47 tasks at [xulang.org/benchmarks](https://xulang.org/benchmarks).
- 📚 **Comprehensive Documentation**: Read guides, syntax specifications, and tutorials at [xulang.org](https://xulang.org).

---

## License

The Xu programming language is open source under the [MIT License](LICENSE).
