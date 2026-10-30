# Xu Release Notes

<p align="center">
  <b>English</b> | <a href="RELEASES.zh-CN.md">简体中文</a> &nbsp;•&nbsp; <a href="README.md">← Back to README</a>
</p>

---

## Xu 0.10.13-dev.4 (development)

HTTP/2 TCP and TLS clients only report success after the current stream ends with complete frames and header blocks. Truncation, resets, GOAWAY, malformed frames and resource limits now return errors and retire the connection while preserving the received response prefix. Reads and writes check progress; SETTINGS and PING are acknowledged, header continuations and padding are handled, and HPACK static status indexes are corrected. Unsupported HPACK encodings and oversized single-frame requests fail explicitly. Full HPACK and flow control remain outside this subset. This is a development build.

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
