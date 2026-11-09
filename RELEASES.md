# Xu Release Notes

<p align="center">
  <b>English</b> | <a href="RELEASES.zh-CN.md">简体中文</a> &nbsp;•&nbsp; <a href="README.md">← Back to README</a>
</p>

---

## Xu 0.12.2-dev.1 (development)

Restores the self-hosting product compiler (`src/cmd/compile`, `src/xu`) from `0.12.0-dev.1`. The clean-architecture compiler shipped in 0.12.1 miscompiles common programs (`for` range loops, slice fields, string concatenation and comparison, struct returns) and cannot build itself, so the hosted seed → Gen1 → Gen2 → Gen3 chain is blocked. With the restored compiler the chain reaches a byte-identical Gen2/Gen3 fixed point again. Development of the clean-architecture compiler continues on its own branch and is not part of the product chain until it can self-host. `internal/modulepath` prefix matching is restored for every prefix.

## Xu 0.12.1

- Compiler Clean Architecture: fully eliminated legacy monolith compiler code (-125k lines), establishing a strictly layered, acyclic modular compiler (L0 Span/Token/Lexer/AST/Parser -> L3 MIR -> L4 MC/Target/Codegen/Obj -> L5 Driver -> L6 CLI).
- Microarchitecture & Chip-Aware Optimization:
  - Per-chip modular package architecture (`@xu/target/chips/*`) supporting Apple Silicon (M1/M2/M3/M4), ARM Cortex-A76, Cortex-A53, Cortex-M4, x86-64-v3, ESP32-C3 (RV32IMC), ESP32-LX6, and generic fallbacks.
  - Hardware cryptographic instruction sets integration for Apple Silicon (AES, SHA-256, SHA-512, SHA-3, SM3, SM4, scalar CRC32, LSE atomics).
  - Pre-emission instruction-level fusion (`opt_fuse`): automatic detection and emission of hardware single-cycle Fused Multiply-Add (`madd`) and Fused Multiply-Sub (`msub`), eliminating temporary register spills.
  - Target-directed optimization pipeline: automatic host chip detection and manual `--chip`/`-march` flags driving cost models for If-Conversion (`MI_SELECT`), loop unrolling, and loop rotation (Loop Inversion).
- Performance & Correctness:
  - 13/13 benchmark suites pass with 100% bit-exact output match against Clang -O3, delivering substantial latency improvements (e.g. `gcd_sum` within 1.06x of Clang, `nested_loop` eliminating 64 million branch jumps).
  - 8/8 cross-platform execution tests pass across native ARM64 Mach-O and x64 ELF.

## Xu 0.11.4

- Compiler: eligible ARM64 integer/bool sibling tail calls restore the caller frame before jumping. Pure scalar additive self recursion can use an accumulator loop; checked arithmetic, bounded readonly byte scans, string operations and proved eight-round CRC loops retain their specialized paths. Ownership, address, ABI, debugging and instrumentation exclusions keep their ordinary fallback. No general performance improvement is claimed.
- XUN & standard library: XUN duration validation advances through its input, collection nesting is bounded by `MAX_DEPTH` (64), multiline payload indentation is preserved, and typed-list parsing/serialization retains its tag and validates inherited scalar types (typed-list output spelling changes; legacy nonempty `!s[...]` scalar input remains accepted). Standard library adds `sys_setsockopt` / `os.setsockopt` and IPv4 UDP multicast (`net.listen_multicast_udp`, `join_group`, `leave_group`), TOML `[[array]]` table-of-tables parsing, and resumable `crypto/cipher` CTR keystreams.
- Desktop & UI: `ui.App.with_content` adds host-side content windows across macOS, Windows and Linux; `xu desktop` supports native app content plugins and macOS `Info.plist.fragment` / resource bundle merging.
- ESP32: adds portable display surfaces (`embedded/display`), MQTT/BLE remote control (`embedded/mqtt`, `embedded/wifi/tcp`), 16-bit absolute HID pointer reports (`0..32767`, 5-byte control payload), and Xtensa relocatable ELF object emission (`--emit-obj`) with `c_call6` external C symbol bridging for linking against official ESP-IDF static libraries (`examples/esp32/idf_cyd`, `0.5.0`). The fixed-profile pure Xu Wi-Fi/BLE coexistence and CYD status application remain experimental source with documented WPA2-PSK/CCMP and single-peer legacy SMP Just Works limits.
- Brand assets: retain the original 0.11.2 UI morph source snapshot with its provenance, credits and external rendering requirements. The historical creative copy does not identify the current SDK.

Upgrade the compiler, standard library and product tools together. Desktop is `1.3.57`, setup is `1.2.48`, and the native tool remains `0.1.3`. No firmware is flashed or distributed by this SDK release. Native acceptance covers macOS, Linux and Windows on ARM64/x64; LoongArch64 and RISC-V packages are cross-built. Benchmark results retain their own measured compiler version and source commit.

## Xu 0.11.4-dev.5 (development)

## Xu 0.11.4-dev.4 (development)

Integrates the reviewed ARM64 tail-call and byte-processing optimizations with XUN duration/depth bounds, multiline indentation and typed-list round trips. Adds the experimental fixed-profile ESP32 Wi-Fi/BLE status application and the original 0.11.2 UI morph source snapshot. Compiler, standard library and tools must be upgraded together. Desktop is `1.3.55` and setup is `1.2.46`.

ESP32 coexistence retains the documented WPA2-PSK/CCMP and single-peer Just Works limits. Final external full-MTU reply acceptance remains pending after a host LAN `EHOSTUNREACH`; previous gateway probes do not complete that acceptance. DHCP renewal, Group Rekey, DNS/TCP, SoftAP and WPA3/PMF remain unavailable. This development integration does not claim a completed hardware release.

## Xu 0.11.4-dev.3 (development)

Integrates safe framed ARM64 sibling tail calls with the scalar accumulator, checked-arithmetic register allocation, readonly byte-scan, string SIMD and CRC-loop optimizations. Restore saved registers and the current frame before an eligible in-unit integer/bool sibling jump; retain ordinary calls for frame addresses, owners, references, instrumentation, debug modes and coroutine stack checks. Both optimization groups are validated together. This is a development build; upgrade the compiler, standard library and tools together. Desktop is `1.3.54` and setup is `1.2.45`.

## Xu 0.11.4-dev.2 (development)

- Compiler: keep checked integer loops in registers across reserved arithmetic traps, and admit bounded, call-free byte scans of shared string parameters to ARM64 register allocation.
- Optimization: turn pure scalar self recursion with one wrapping integer addition per recursive result into an accumulator loop. Non-additive recursion, ownership, references and side effects retain their existing paths. Recognize the CRC bit loop after load commoning and preserve the exact eight-iteration proof.
- Strings: specialize empty and one-byte `contains`, use a borrowed prefix scan, and expose byte replacement invariants to the checked SIMD emitter. Preserve byte values, independent result ownership and scalar tails.

This is a development build. Performance measurements apply to their recorded workload, compiler and host; no general speedup or timing parity across targets is claimed. Upgrade the compiler, standard library and tools together. Desktop is `1.3.53` and setup is `1.2.44`.

## Xu 0.11.4-dev.1 (development)

ARM64 code generation can restore a caller's stack frame and saved registers before jumping to an eligible sibling function. This allows integer/bool mutual tail recursion to run with bounded stack usage even when parameters occupy frame slots. Admission is limited to in-unit direct calls with at most six register arguments and a matching scalar return; functions with non-scalar locals or temps, address formation, or drop operations retain ordinary calls. Debug, coverage, test, unoptimized, and coroutine-stack-check builds retain the existing framed call path. Other architectures and self calls keep their existing behavior.

## Xu 0.11.3

- Compiler: SSA reassociation and periodic-reduction proofs preserve the actual loop backedge; narrow integer normalization follows the physical register width; very small GEMM tiles retain the scalar path when kernel setup would dominate.
- Native interoperability: opt-in `xu-c-2` passes synchronous borrowed i64 spans through checked `&[]int` / `$&[]int` parameters. Call-scoped descriptors expose length and data only. Existing C1 libraries remain supported; older products explicitly reject C2 objects. C2 currently accepts 64-bit integer scalars and `int` / `void` results; use a Xu wrapper for native function values.
- Correctness: binary64 rounding preserves integral large values, signed zero and non-finite inputs; `log(±0)` returns negative infinity, and `log(+Inf)` / `frexp` special inputs terminate. Wide unsigned multiplication/division use all input lanes and diagnose quotient overflow. Owned string slices index complete descriptors and preserve independent ownership.
- ESP32: pure Xu Xtensa ELF/image generation, ROM calls/callbacks, BLE building blocks, and bounded WPA2/CCMP/DHCP/ARP/ICMP primitives. The supported board profile is ESP32-D0WD-V3 rev3.1, 40 MHz XTAL, 4 MiB flash. Standard `WifiDevice` APIs remain unavailable; persistent station operation, lease renewal, DNS/TCP, Internet access and BLE/Wi-Fi coexistence are not supplied by these primitives. Just Works and plaintext bond-storage limitations remain as documented in the packages.
- Windows SDK: installers carry an `asInvoker` application manifest for current-user startup. All-users installation still requires administrator privileges.

Upgrade the compiler, standard library and product tools together. Desktop is `1.3.52`, setup is `1.2.43`, and the native tool remains `0.1.3`. Release acceptance covers native SDK builds, runtime protocols and installation on macOS, Linux and Windows, each on ARM64/x64; LoongArch64 and RISC-V SDKs are cross-built. This release does not claim a general speedup. Cross-language measurements identify their own compiler commit and workload inputs.

## Xu 0.11.3-dev.15 (development)

Integrates binary64 special-value rounding, full-width unsigned arithmetic, correct owned string-slice indexing, Windows SDK current-user installer manifests, and ESP32 WPA2/CCMP/IPv4 protocol primitives. Retains the borrowed i64 native ABI and pure Xu ESP32 backend. Standard `WifiDevice` APIs remain unavailable until a persistent hardware driver is connected; protocol and board probes do not imply a complete Wi-Fi application. No general performance improvement is claimed for this integration.

## Xu 0.11.3-dev.14 (development)

Fixes string-array slicing reading later elements at byte offsets instead of descriptor offsets. Source and destination indexing now share the existing scaled element offset, preserving the 24-byte descriptor layout, independent slice ownership and bounds traps without adding another per-element multiplication. This is a development build.

## Xu 0.11.3-dev.13 (development)

Fixes unsigned full-width integer arithmetic in math/bits: mul64 now masks logical high-lane shifts, and div64 divides the complete 128-bit dividend, reports quotient overflow and preserves unsigned quotient/remainder bit patterns. A zero high lane uses bounded unsigned 64/64 shortcuts instead of the general 64-step division. Only ARM64 and x64 calls use the existing native high-multiply helper; other targets retain the semantic implementation. No new ISA or constant-time guarantee is introduced. This is a development build.

## Xu 0.11.3-dev.12 (development)

Windows SDK installers now embed an `asInvoker` application manifest, so current-user installation can start from a normal terminal on ARM64 and on x64 builds using the native PE fallback. Existing GUI installer resources remain intact. SDK installation checks verify the embedded policy through the Windows loader, including on administrator CI runners. This is a development build.

Fixes software binary64 floor, ceil, truncation and rounding for non-finite values, signed zero and large integral inputs. Round compares the fractional part instead of adding 0.5, avoiding incorrect results near half-integers and the 2^52 boundary. Log now returns negative infinity for either zero and terminates for positive infinity; Frexp preserves zero, infinity and NaN with exponent zero. Hardware rounding paths remain available. This does not change finite Log approximation or provide a new FMA accuracy guarantee. This is a development build.

## Xu 0.11.3-dev.10 (development)

Adds the opt-in `xu-c-2` native ABI for synchronous borrowed i64 spans. `i64_span` and `i64_span_mut` parameters become Xu `&[]int` and `$&[]int`; a call-scoped C view exposes length and contiguous data without transferring array ownership or capacity. The platform adapter handles integer register and stack arguments, including Win64 shadow space. Both native pack tools accept the versioned format; older products reject it instead of interpreting a borrow as an integer. Existing `xu-c-1` archives remain supported. This ABI currently accepts 64-bit `int` scalars and `void`/`int` results; native function values require a Xu wrapper. This is a development build.

## Xu 0.11.3-dev.9 (development)

Integrates SSA integer/mask reassociation with SCCP, periodic reductions, floating-point negation correctness, and guarded Tile cost selection from the reviewed development stack. Preserve all prior optimization and module versions during integration. Periodic-reduction proofs now follow the additive bias on the actual backedge value, including the reassociated (sum + masked) + bias form, without inferring it from an unused sibling expression. The shared narrow-result normalization now uses the physical GPR width: i32 is already a full register on RV32 and Thumb, so it no longer executes the 64-bit shift/sign-extension idiom there. Native macOS ARM64 SDK checks use the supported macos-15 ARM64 runner after macos-26 jobs repeatedly ended before runner assignment; the same build, installation and runtime checks remain enabled. This is a development build.

## Xu 0.11.3-dev.8 (development)

Integer GEMM Tile lowering now keeps tiny positive nests with M+N+K below five on ARM64 or four on x64 on the original scalar path, avoiding the micro-kernel's full entry guards and register saves. Known tiny bounds omit the guarded micro-kernel entirely; bounds that already prove the minimum size need no runtime cost check. Bounds, alias checks and scalar trap behavior remain intact. This is a development build.

## Xu 0.11.3-dev.7 (development)

Integer GEMM Tile recognition now accepts a proven inner backedge copy at the end of a merged self-loop as well as a separate copy latch. It preserves B's element count across descriptor reloads in the alias guard, retains bounds and dependence proofs, and writes the correct final induction value for each representation. Unsafe early copies, side effects and ambiguous entries retain scalar lowering. This is a development build.

## Xu 0.11.3-dev.6 (development)

Constant unary negation now distinguishes integer arithmetic from f64 bit patterns. Floating constants flip only their sign bit, preserving signed zero, infinities and NaN payloads instead of negating their encoded integer value. This fixes optimized negative floating literals in matrix, norm and reduction code without changing the integer wrapping contract. This is a development build.

## Xu 0.11.3-dev.5 (development)

The verified SSA window now performs bounded sparse conditional constant propagation before Phi destruction. A monotone constant lattice and executable-edge worklist jointly simplify integer/boolean values, branches and Phi inputs, then remove proved unreachable blocks. Loads, calls, floating-point values, exposed storage and exceptional arithmetic remain conservative. Analysis-budget rejection leaves the original function intact. This is a development build.

## Xu 0.11.3-dev.4 (development)

ARM64 periodic integer reductions with the same proved constant induction at every entry now fold in MIR before register and frame planning. The rewrite preserves the incoming accumulator and final induction, then reuses CFG and dead-code cleanup to remove the loop's temporary storage. Dynamic, differing and width-converting entries keep their existing paths. This is a development build.

## Xu 0.11.3-dev.3 (development)

Proved ARM64 integer reductions of `(i & mask) + bias` use a constant-step periodic sum when the mask is `2^k - 1` through 65535. The slot and SSA paths share the same lowering, preserving signed starting indices, wrapping accumulation, zero-trip guards and the final induction value. Other masks keep the existing SIMD path. This is a development build.

## Xu 0.11.3-dev.2 (development)

ARM64 shift/add and shift/sub fusion now proves that the shift result and any skipped local load have only one use across the whole function. This preserves values shared across basic blocks by CSE instead of leaving later reads uninitialized. It fixes optimized compilation failures in mutable-method and named-function-value reduction loops while keeping their SIMD lowering available. No API or ABI changes. This is a development build.

## Xu 0.11.3-dev.1 (development)

The SSA simplifier linearizes bounded, same-block word-integer addition/subtraction and AND/OR/XOR trees before common-subexpression elimination. It combines separated constants and masks, cancels opposite arithmetic terms and duplicate XOR terms, and removes repeated AND/OR operands. Shared intermediate values remain intact; floating-point, narrow integers, address-exposed storage and Phi edges retain their existing semantics. No API or ABI changes. This is a development build.

## Xu 0.11.2

- **Event-driven HTTP server**: Linux epoll/eventfd and macOS kqueue manage persistent connections with bounded accept and handler scheduling. The EventSet backend has a configurable 110,000-connection ceiling; actual capacity depends on OS limits and resources. Optional `sync_handlers` runs short, nonblocking handlers on the event-loop thread; other platforms retain the legacy backend.
- **Explicit desktop builds**: UI imports and a `www/` directory no longer enable desktop packaging or WebView during `xu build`. Use `xu build App/ --desktop` for the Draw host, and add `--webview` explicitly for WebView applications.

- Route hosted security-store and socket-readiness calls to their dedicated emitters; reject unknown MIR calls explicitly. Darwin socket readiness now builds and decodes kevent fields using the correct register operands, widths and flags.
- Wake SQL pool waiters when capacity changes or the database closes, including discarded/expired connections and increased connection limits. Publish returned idle connections under the pool state lock.
- Enforce HTTP request-body limits at zero and other decimal boundaries. In-memory pipes notify both endpoints of closure, interrupt blocked operations and retain already-buffered reads before peer EOF.

Stable release integrating architectural modularization, self-hosting reproducibility, scale stability governance, and unified target constraints since 0.11.1. Upgrade the compiler, standard library, and product tools together. Platform binaries and checksums are listed with the release assets.

- **Modular UI Architecture**: Chart components are fully decoupled into an independent `@ui/chart` package, featuring 30 chart series types, animation state management, and high-level drawing, decoupling from `@ui/widgets` and sample applications like `component_workshop`.
- **Compiler Robustness and Self-Hosting**: Fixed XUN configuration infinite loops on empty keys and block body parsing; added regression tests for invalid inputs and empty-type arrays; restored reproducible three-generation self-hosting (`Gen2 == Gen3` fixed point) across supported seeds.
- **Optimization Scale Stability**: Established a stability testing harness across varying translation unit sizes, ensuring consistent optimization admission and transformation invariants without threshold-induced divergences.
- **Unified Register Constraints and Function Analysis Summaries**: Standardized target machine register footprint constraints (`td_extra_gpr_home`) and introduced read-only function analysis summary abstractions (`mir_fn_summary_ro` / `MFn.summary()`).
- **Runtime and Linker Integrity**: Preserved subprocess interrupt symbol `___error` on macOS native static linking, with full cross-platform deadline and cancellation cleanup in `os/exec.command_context`.
- **Compiler Warning Elimination**: Resolved all compilation and link diagnostics across self-hosted and native product tool builds, including zero-division guard paths, Clang tautological comparisons, Swift UTType migration, and layout modularization for composite desktop UI setup models.

## Xu 0.11.2-dev.3 (development)

Native macOS static linking preserves the `___error` symbol used when subprocess waits are interrupted. The compiler-owned Mach-O object converter now matches the UI packaging converter, so programs using `os/exec` can link native archives without an undefined `__error` symbol. This is a development build.

## Xu 0.11.2-dev.2 (development)

Remove duplicate empty-block, operand-freshness and shift-chain helper declarations introduced when optimizer changes were combined in dev. The existing CFG and conservative shift-chain implementations remain authoritative. Conditional branches use the established two-path emission again while the new fallthrough optimization is reworked; this preserves compiler argument parsing and register-cache edge state during self-hosting. This is a development build.

## Xu 0.11.2-dev.1 (development)

Commands created with `os/exec.command_context` now observe cancellation and monotonic deadlines while running. `run`, output capture and `start`/`wait` terminate and wait for the direct child before reporting the context error. Unix waits retain the exact child PID across pipe descriptor cleanup and retry interrupted waits; Windows retains process handles until termination completes. Normal exit status and the public command API remain compatible. Descendant process trees are outside this contract. This is a development build.

## Xu 0.11.1

Stable release integrating the changes since 0.10.12. Upgrade the compiler, standard library and product tools together. Platform binaries and checksums are listed with the release assets.

**Source migration:** legacy `mut name :=`, `let mut name: T = ...`, `mut &value` and `&mut T` syntax is removed. The parser rejects these spellings with H38 diagnostics. Use `$name :=` or `let $name: T = ...` for mutable bindings, `$&value` for writable borrows and `$&T` for writable reference types. LSP completions and highlighting follow the current syntax.

- Compiler performance work ([#84](https://github.com/xulang-org/xu/pull/84)) improves scan/carry vector pattern recognition, small-unit CFG inlining and single-byte string replacement.
- Constant array literals receive independent owned storage, fixing shared SHA-256 workspace races that corrupted RSA-PSS and TLS verification on macOS x64 ([#78](https://github.com/xulang-org/xu/pull/78)). Optimized interface calls also preserve coroutine context and live ARM64 scalar values, fixing SQL pool crashes.
- UI adds typed action dispatch by control ID, separates Screen appearance from event handling and includes split project sources in desktop builds. Chart expands to 30 series types; drawing gains affine transforms, geometry and path helpers, hit testing, text/image fitting and palettes. Menu hover and active items use contrasting accent colors across dark, light and high-contrast themes.
- HTTP/2 TCP and TLS clients require complete responses and report truncation, resets, GOAWAY, malformed frames and resource limits as errors while preserving the received prefix. Frame handling, SETTINGS/PING acknowledgments and HPACK static status indexes are corrected; full HPACK and flow control remain outside the supported subset. HTTP adds ServeMux and reverse-proxy/dump helpers; WebSocket and HTTP upgrade support are expanded, with fallible errors propagated.
- Standard library additions include HKDF, X25519 ECDH, PBKDF2, ChaCha20-Poly1305, CFB/OFB modes, `sync.Map`, `sync.Pool`, parallel-reader RWMutex, timezone/DST fallback, JSON `parse_max`, regexp character classes and subprocess stderr pipes. Basic TOML parsing and Zstandard raw/RLE block support are added, alongside tar and signal handling improvements.
- XACP `ui.record` samples registered Screens into bounded XAR1 segments with byte, record, duration and frame limits. Frame mode captures screenshots; event mode reports current-state observations rather than input history. Control transport applies a monotonic per-frame write deadline through `XU_XACP_WRITE_TIMEOUT_MS`, closing stalled sessions on expiry.

## Xu 0.10.13-dev.4 (development)

HTTP/2 TCP and TLS clients only report success after the current stream ends with complete frames and header blocks. Truncation, resets, GOAWAY, malformed frames and resource limits now return errors and retire the connection while preserving the received response prefix. Reads and writes check progress; SETTINGS and PING are acknowledged, header continuations and padding are handled, and HPACK static status indexes are corrected. Unsupported HPACK encodings and oversized single-frame requests fail explicitly. Full HPACK and flow control remain outside this subset.

XACP control sessions now bound each outgoing frame with a monotonic write deadline (`XU_XACP_WRITE_TIMEOUT_MS`, default 10000 ms, range 1..600000). POSIX stdio and TCP wait for write readiness and write bounded chunks; expiry closes the session as a transport failure.

`@ui/widgets` improves `Menu` item hover and active styling with `styles.menu_style()`, providing high-contrast `palette.accent` background and `palette.on_accent` text, indicators, and shortcuts across dark, light, and high-contrast themes. This is a development build.

## Xu 0.10.13-dev.3 (development)

`@ui/widgets` expands `Chart` from 5 to 30 series types (`CHART_STEP_LINE`, `CHART_STACKED_AREA`, `CHART_STACKED_BAR`, `CHART_HORIZONTAL_BAR`, `CHART_PIE`, `CHART_ROSE`, `CHART_RADAR`, `CHART_GAUGE`, `CHART_BUBBLE`, `CHART_HISTOGRAM`, `CHART_BOXPLOT`, `CHART_HEATMAP`, `CHART_CANDLESTICK`, `CHART_WATERFALL`, `CHART_FUNNEL`, `CHART_SMOOTH_LINE`, `CHART_SMOOTH_AREA`, `CHART_POLAR_BAR`, `CHART_TREEMAP`, `CHART_SANKEY`, `CHART_VIOLIN`, `CHART_BULLET`, `CHART_LOLLIPOP`, `CHART_DUMBBELL`, and `CHART_PARETO`) with `chart_bubble_point` and `chart_range_point` constructors, hit testing, and animated transitions. `@ui/draw` adds 2D affine transforms (`Matrix2D`, `rotate_around`, `scale_around`, `Path.transform`, `Path.append`, `Path.bounds`), geometric hit-testing and flattening (`point_in_rect`, `point_in_circle`, `point_in_ellipse`, `point_in_round_rect`, `point_in_triangle`, `point_in_polygon`, `point_in_sector`, `distance_to_segment`, `point_near_polyline`, `Path.flatten`, `Path.contains`, `Path.hit_stroke`), high-level `Path` and `Frame` geometry/curve/pattern builders (`rect`, `round_rect`, `round_rect_corners`, `capsule`, `circle`, `ellipse`, `diamond`, `arc`, `ellipse_arc`, `sector`, `ring_sector`, `ring`, `polyline`, `polygon`, `rounded_polyline`, `rounded_polygon`, `regular_polygon`, `star`, `smooth_spline`, `smooth_curve`, `wave`, `cross`, `checkmark`, `chevron`, `callout`, `ribbon`, `heart`, `shield`, `gear`, `spiral`, `hatch_rect`, `cross_hatch_rect`, `dot_grid`, `quad_curve`, `cubic_curve`, `dashed_line`, `dashed_rect`, `arrow`, `double_arrow`, `grid`, `box_shadow`, and gradient shape fills), text/image helpers (`measure_text`, `text_aligned`, `text_pill`, `image_fit`), and color/palette/stroke utilities (`hex`, `hsl`, `hsla`, `lerp_color`, `with_opacity`, `opacity`, `lighten`, `darken`, `invert`, `grayscale`, `luminance`, `contrast_ratio`, `contrasting_ink`, `mix_palette`, `palette_colors`, `sample_palette`, `multi_stop_linear`, `multi_stop_radial`, `round_stroke`, `dashed_stroke`, `two_stop_linear`, `two_stop_radial`).

Interface method calls now restore the coroutine stack-check marker before entering user code. The ARM64 register cache reserves that marker home for pinned locals and call results, preventing optimized SQL pool operations from crashing or replacing live scalar values. This is a development build; no stable release is published.

## Xu 0.10.12

Stable release of the 0.10.12 line. Phase C markers are now the documented spelling: `$name :=` declares a mutable binding, `$&value` takes a writable borrow and `$&T` names its type. Product sources, examples (including `examples/xacp`) and compiler diagnostics use these markers; diagnostics for immutable assignment and mutable borrows now suggest `$x := value` and `$&owner`. Upgrade the compiler, standard library and product tools together. Published binaries and checksums are listed with the release assets.

Also includes the fixes from 0.10.12-rc.2 and rc.3:


Windows socket readiness fully initializes the `WSAPOLLFD` event fields and rejects zero-extended `SOCKET_ERROR` results. Previously stale stack flags could make a nonblocking readiness check report a large positive count, causing the HTTP intake loop to block in `accept` before processing connected clients. No public API or ABI changes.

Winsock adapters sign-extend 32-bit status and byte-count results, including TCP/UDP send and receive errors, while preserving pointer-width SOCKET handles. Invalid I/O can no longer become a positive byte count or an oversized received string.

## Xu 0.10.12-rc.1 (prerelease)

This release candidate promotes the validated development branch for wider testing. It adds the Phase C markers: `$name :=` for mutable bindings and `$&` for writable borrow expressions and reference types. The legacy `mut name :=`, `mut &value` and `&mut T` spellings remain compatible. A name of type `$&T` is accepted where a shared `&T` is expected. XACP smoke tests pin the companion examples to the current XACP API and tolerate stdin closing at the hello deadline on slow runners.

This is a prerelease; APIs and syntax may still change before 0.10.12. Upgrade the compiler, standard library and product tools together. Published binaries and checksums are listed with the release assets.

## Xu 0.10.11

This release integrates the validated development branch with the 0.10.10 native widget baseline. It includes the Phase B shared-reborrow checks, framed XACP transport and Screen marshalling, Windows UI boundary fixes, WASM smoke coverage, and terminal progress for SDK installation and updates. The native password input and monotonic pointer-clock fixes from main are retained.

**Source migration:** a writable local reference can be passed where the same direct pointee is expected through a shared reference. Aliasing a shared reborrow and a writable parent in one call is rejected in either argument order; split the operations or end the shared loan before mutating. This does not introduce recursive container conversions or automatic reborrows of arbitrary values. Upgrade the compiler, standard library and product tools together.

XACP clients must use the framed control transport and the matching companion examples. SDK bundle inputs are pinned to complete companion commits. The stricter compiler, native UI, WASM and installed-SDK checks are run on the combined release source; platform-specific binary availability and checksums are listed with the release assets. Cross-built targets are not claimed as native GUI acceptance.

## Xu 0.10.10

This version brings the public native widget APIs needed by the 46-entry component workshop, including Chart, RangeSlider, SplitView and structured menus. The bundled workshop keeps WebView support, and its action toolbar wraps and scrolls with large text instead of clipping labels at 200%. Native WebView content retains its own CSS and system child surface.

Native map adapters now restore the current coroutine context before calling ordinary Xu hashing and growth-policy functions. Without that context, function entry stack guards could interpret map storage as a coroutine and crash a desktop worker during startup. Installed-SDK validation exercises integer and string maps inside a coroutine at `-O0`, `-O2` and `-O3`.

Aggregate borrows from dynamic arrays and maps are converted to the ordinary reference-call layout; mutable calls write changes back before handling success or errors. Packed array copies preserve their final bytes. Returning a reference through an adapted aggregate call is rejected instead of exposing a temporary view; copy the element to a local before such a call. `Screen.button_with_icon()` adds visible text and supports leading, trailing, above and below icon placement, separately from icon-only buttons. `Screen.measure_button()` returns the intrinsic size for the current text, icon placement, style and scale, allowing content-sized buttons and wrapping layouts.

Tooltips distinguish delayed pointer hover from immediate keyboard/programmatic focus, dismiss during pointer interaction, and position against the visible anchor inside scroll clips. Top/center is the default; `Tooltip.set_placement()` and `Screen.set_tooltip_placement()` configure all four sides with edge flipping. Installed-SDK validation exercises delay, dismissal, refocus and placement without claiming native GUI coverage.

PasswordInput adds grapheme masking, reveal/hide, native editing and paste while blocking copy/cut and native surrounding-text disclosure. `Screen.password_input()`, `set_password_visible()` and `text_value()` keep display policy separate from the application value. Masked native layouts preserve the source UTF-8 positions for selection, caret and input bindings.

Native pointer timestamps now share the Xu monotonic clock. macOS previously used system uptime, which differed by about 4.29 seconds on the acceptance machine and delayed a 500ms tooltip to nearly five seconds. The SDK smoke invokes the actual native mouse callback and checks its timestamp against the runtime clock. Passive hover also works before the window is activated.

Compiler updates include borrow-flow join fixes, Thumb/freestanding concurrency checks, stack guards and a LoongArch far-branch correction. **Source migration:** moving an owned non-string field out of a borrowed struct is rejected. Borrow the field when its lifetime permits, or use the public widget `clone()` API for temporary measurement and painting snapshots. The bundled style gallery uses explicit clones; upgrade compiler, standard library and tools together. XACP control examples now live in the companion examples repository.

Desktop packing and Doctor locate host sources beside their own installed executables, including PATH/symlink launches, before considering environment or checkout fallbacks. This makes `xu build --desktop` work outside a source checkout without letting a stale `XU_ROOT` select another SDK. Linux and Windows host compilation also preserves SDK include paths containing spaces. Every desktop target selects the UI coroutine-stack profile while emitting its object.

Native Windows desktop packing explicitly launches the Git Bash/MSYS2 `sh` required by its recipes, resolves sibling `.exe` tools, and uses the native temporary directory with normalized paths. Doctor now checks that shell dependency. Installed-SDK validation also enters the desktop packer from an unrelated directory and verifies its sibling Doctor selects the installed SDK.

SDK workflows pin the corrected example sources and check the installed workshop alongside existing UI and service samples. Native installed-SDK checks cover macOS, Linux and Windows on ARM64/x64; these checks do not imply desktop GUI acceptance on every platform. Workshop GUI acceptance is on macOS ARM64. Canvas accessibility bridging, editor undo history and touch long-press remain documented limitations. LoongArch64 and RISC-V SDKs are cross-built.

Published binary availability, source revisions and SHA-256 checksums are recorded in [GitHub Releases](https://github.com/xulang-org/xu/releases).

## Xu 0.10.7 release

This patch repairs reinstalling over an existing SDK, including read-only standard-library files. Setup and `xu update` prepare a complete SDK beside the target, verify every recorded file and all ten tools, retain the old directory as a backup, then replace the target. Failed replacement or verification restores the original SDK. User data outside SDK-managed components is preserved; stale managed files are removed.

The online Bash and PowerShell installers delegate to this same native transaction. They select the existing SDK on PATH unless an explicit prefix is supplied, and support installation without modifying shell profiles. Reinstalling the same version repairs its full contents. The compiler also retains a separate legacy banner so older 0.10.2 updaters can recognize the release.

Release SDKs are built and verified in a read-only CI job. A separate publication job uploads those exact verified files using the short-lived GitHub Actions token; it does not run the packaged tools or dependencies. All published tags and assets remain immutable.

[Download Xu v0.10.7](https://github.com/xulang-org/xu/releases/tag/v0.10.7). For old or partially installed SDKs, rerun the installation command on the [download page](https://xulang.org/download/).

## Xu 0.10.6 release

This patch release completes the imported-constant migration in the bundled examples. UI, WebSocket and DNS examples now use the uppercase constants exported by the compiler and bundled packages. The release, SDK and core CI workflows pin the corrected examples at `854c7c3`. Installed-SDK validation checks real UI and service examples, so a working compiler alone cannot hide this packaging regression.

Offline extraction also reuses one DEFLATE history buffer and reads TAR headers without cloning the whole archive per entry. This removes repeated archive-sized copies that caused the Intel macOS standalone installer to exceed its installation timeout. Timeout diagnostics preserve the captured installer output.

The full release also builds and includes the pinned VS Code extension VSIX (extension version 0.3.0). An explicitly selected extension checkout without its built VSIX now fails packaging instead of silently shipping only metadata.

All 54 website-curated examples pass compilation with the corrected sources; SQLite examples require the native bridge described in their README. Compiler, tools and SDK manifests use 0.10.6. Install the full SDK to keep its components together.

[Download Xu v0.10.6](https://github.com/xulang-org/xu/releases/tag/v0.10.6). The original v0.10.5 tag and archives remain intact.

## Xu 0.10.5 release

Adds source debugging through `xu debug`, compiler/stdlib improvements, native Setup installation and standard-library update progress, uppercase constant naming, ARM32 integer/ABI support, LSP diagnostic URI preservation and a simplified version banner. The original bundles contain incomplete imported-constant migrations in some examples; use 0.10.6 for the corrected full SDK.

## Xu 0.10.2 release

This official release resolves ambient toolchain resolution issues, brings native non-blocking socket readiness across all supported operating systems, adds bounded LZ77 RFC1951 DEFLATE compression, and integrates ergonomic UI abstractions:

- **CLI / Toolchain Self-Perception**: `xu env` now resolves `XU_ROOT` and `XU_STDLIB_ROOT` relative to the running compiler executable (`argv[0]`) rather than letting ambient shell variables (`~/.xu`) hijack build lookups. Companion standard library directory detection validates readability and preserves strong consistency between toolchain root and standard library paths.
- **Native Socket Readiness (epoll / kqueue / IOCP)**: Added native non-blocking socket wait primitives (`sys_socket_wait` / `os.socket_wait`). Linux uses `epoll`, macOS/BSD uses `kqueue`, and Windows delegates to `IOCP` with overlapped I/O completion requests.
- **RFC1951 DEFLATE Compression**: Full fixed-Huffman LZ77 compression with bounded 32 KiB history ring buffers, fast 3-byte hashing, and stored-block fallback for incompressible data.
- **UI Screen Ergonomics**: Introduced high-level `Screen` abstraction and hardened styled widgets layout and slot layout.
- **ARM32 / Thumb-2 Codegen**: Merged Thumb-2 virtual register allocation, T16 narrow encoding, and branch relaxation.

Download from [Xu v0.10.2](https://github.com/xulang-org/xu/releases/tag/v0.10.2).

## Xu 0.10.1 release

This official release includes all development changes through `930f189`: styled UI controls and the unified style switcher, desktop request handling, Thumb-2 code generation, cryptography fixes, and HTTP, regexp, JSON and compression corrections.

**Migration:** regexp match/find/split/replace APIs now require error handling when their work budget is exhausted. HTTP handlers can run concurrently; synchronize shared mutable state. Draw camera panning requires `draw.set_pan_enabled(1)`. See the development entries below for API details and limits.

The earlier `0.11.0-dev.3` preview remains a separate historical release. This source and its SDK use the explicitly selected official version **0.10.1**. Download from [Xu v0.10.1](https://github.com/xulang-org/xu/releases/tag/v0.10.1).

## Xu 0.11.0-dev.2

This development update integrates the remote `arm32` compiler changes: Thumb-2 register allocation, compact 16-bit instruction encoding and branch relaxation. It retains the standard library changes and migration requirements below.

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

- **Borrow Checking Soundness**: The borrow checker now walks every expression kind (with a conservative fallback for unknown kinds), so aliasing such as `f($&v, &v)` is reported even when nested inside casts or arithmetic; borrows taken inside a loop now stay live across the back edge. Programs that previously compiled only because of these gaps now receive a diagnostic.
- **Generics and Type Table Limits**: Generic declarations are no longer limited to four type parameters, type-id range overflow is asserted instead of silently wrapping, and backends that do not support a requested target fail explicitly.
- **MIR Verification**: `XU_VERIFY=1` runs the full MIR verifier after every optimization pass; mismatches between the verifier, lowering and the backend were fixed. `XU_DUMP_MIR=<fn>` dumps a function's MIR.
- **SSA Loop Optimization**: Scalar SSA promotion no longer depends on a per-shape whitelist, and the ARM64 loop kernels (scan, saxpy, CRC, binary search, fill, stride, predicated scan) have SSA-based matchers. Loops bounded by an `[]int` length are rotated so they qualify. Measured speedups versus 0.9.3 include `bloom_filter` ~12%, `chase_index` 9-11%, `f64_sum` ~8% and `algorithm_search` ~9% at `-O3`, with no regressions and slightly faster self-compilation.
- **Pattern Diagnostics**: `--timings` reports `pattern-hits:` and per-function register-allocation mode; `XU_PATTERNS_OFF` disables named backend patterns for differential testing (`scripts/pattern_diff.sh`).

Published SDKs and installers are listed on the [releases page](https://github.com/xulang-org/xu/releases). The [benchmark dashboard](https://xulang.org/benchmarks) retains each measurement's actual compiler version and provenance.

The product self-host chain uses a verified hosted seed, hashes the source manifest,
and requires a fixed point between adjacent generations. The repository does not
claim a seed-free bootstrap from only the checked-in sources.

Coroutine calls are ownership boundaries: `xu` transfers owned values or uses
channels, while borrowed `&T` and `$&T` values do not cross into another
coroutine. The `<-` token is context-sensitive by design: a statement form is
`break`, while an expression such as `<-ch` receives from a channel.
