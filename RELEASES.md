# Xu Release Notes

<p align="center">
  <b>English</b> | <a href="RELEASES.zh-CN.md">简体中文</a> &nbsp;•&nbsp; <a href="README.md">← Back to README</a>
</p>

---

## Xu 0.10.6 release

This patch release completes the imported-constant migration in the bundled examples. UI, WebSocket and DNS examples now use the uppercase constants exported by the compiler and bundled packages. The release, SDK and core CI workflows pin the corrected examples at `854c7c3`. Installed-SDK validation checks real UI and service examples, so a working compiler alone cannot hide this packaging regression.

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
