# XU UI Morph (1440×1440)

One shape, never cut. Cursor-driven morph with **deepened** copy from [xulang.org](https://xulang.org/):

| Beat states | Content depth |
|---|---|
| Logo | Tagline: Zero GC · Inferred Ownership · Native & WASM AOT |
| Install XU | `curl -fsSL xulang.org/install.sh` |
| Loader | Detect arch → fetch SDK 0.11.2 → register PATH |
| Check | Ownership checked · deterministic cleanup · no GC |
| Island | AOT · macos-arm64 · `xu build` |
| Player | Clear intent. + `xu worker` / `or (err)` snippet |
| Peak load | EventSet ceiling · conn count · no GC at peak |
| Toggle | Garbage collector Off · compile-time ownership |
| Tabs | CLI / HTTP / UI panes with APIs from the site |
| Chart | 60 groups · 72 workloads · XU vs Go/Rust |
| ⌘K | Topic + one-line technical description |
| Toast | SDK 0.11.2 · PATH · stdlib · full toolchain |

Pure `seek(t)`. Mixkit *Slow Trance Morning* @ ~123 BPM, 7 bars.
Artifact: `/opt/cursor/artifacts/xu-ui-morph.mp4`

## Source snapshot

The on-screen SDK version and benchmark counts describe the original 0.11.2
promo. They are historical creative content, not current release or performance
claims. Open `index.html` directly to inspect the self-contained animation;
`window.seek(seconds)` selects a deterministic frame.

The Python scripts preserve the original rendering setup. Rebuilding requires
its external `/tmp/xu-ui/embed.json`, font/audio inputs, Python dependencies
(NumPy, Pillow and Playwright), Chromium and ffmpeg. Those production inputs
and the rendered video are not included in this source snapshot. The artifact
path above belongs to that original environment.
