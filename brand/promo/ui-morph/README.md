# XU UI Morph (1440×1440)

One shape, never cut. Cursor-driven morph through logo → button → loader → check → island → player → volume → toggle → tabs → chart → ⌘K → toast → logo. Pure `seek(t)` (no CSS transitions / timers).

## Render
1. Rebuild HTML embeds: `python3 build_html.py` (needs `/tmp/xu-ui/embed.json` from local asset prep)
2. Beat stills: Playwright `seek(BEAT(i))`
3. Full: `python3 render.py` → 60fps, 4 subframes averaged, ffmpeg `tmix`, bed+SFX mux

Output artifact: `/opt/cursor/artifacts/xu-ui-morph.mp4`
