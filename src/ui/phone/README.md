# Phone UI design

`#ui/phone` provides a mobile layout and interaction layer over the existing
`#ui/draw` frame/resource protocol. It does not replace `#ui/widgets` or add a
second application runtime. Start with `examples/phone_gallery`: a small counter
application with Today, History and Settings pages, category selection, goals,
light/dark appearance and destructive-action confirmation.

## Design rules

- Hosts run **edge-to-edge** (covering system status bars and home-indicator
  areas) and report `CanvasMetrics` plus `host_insets()` (`top`, `bottom`,
  `left`, `right`, `ime_bottom` in logical points/DIP, mirroring Flutter's
  `MediaQuery` split). Use `scaffold_with(width, height, safe)` so surfaces
  bleed edge-to-edge while interactive controls clear cutouts and active IME.
- Use a 20-point page inset, 48-point minimum touch targets, 56-point primary
  actions and 72-point list rows. Decorative icons may be smaller than their hit
  area. The body scrolls independently of persistent navigation and actions.
- Keep primary actions near the bottom in portrait. Short viewports at least
  640 points wide use a navigation rail and two body panes, preserving vertical
  space. `scaffold_with()` assigns geometry; it does not stretch a desktop toolbar.
- Use Paper / Obsidian / Cinnabar tokens (`background`, `surface`, `elevated`,
  `subtle`, `border`, `ink`, `muted`, `accent`, `accent_pressed`, `subtle_pressed`,
  `accent_tint`, `on_accent`, `positive`, `danger`, `danger_soft`, `focus`, `scrim`)
  from `light_theme()` or `dark_theme()`. Weight, alignment and single-line
  ellipsis work for Canvas text; layout does not depend on estimated shaping metrics.
- A press is visible before activation. Release must match its initial target.
  Movement over 8 points cancels activation; vertical dragging scrolls with
  axis lock and inertial fling (`Touch.step_at()`, iOS bouncy overscroll vs
  Android clamping). Tapping a moving scroll halts momentum without triggering
  the item beneath the finger. Focus loss and rotation cancel active presses.
- `RouteStack` manages push/pop depth and left-edge `Touch.swipe_back()`.
  `Snackbar` provides auto-dismissing feedback (`snackbar_bounds()`).
  A bottom sheet blocks background targets, lifts above `ime_bottom`, accepts
  downward header swipes (`Touch.swipe_down()`), and honors Android Back.
- Respect `reduced_motion()` (forwarded from OS Accessibility settings) by
  skipping scroll fling momentum and non-essential motion.

## Building blocks

| API | Purpose |
| --- | --- |
| `host_insets()`, `reduced_motion()` | OS safe-area/IME insets and accessibility reduced-motion state |
| `scaffold(w, h)`, `scaffold_with(w, h, safe)` | Edge-to-edge header, body, navigation and primary-action rectangles |
| `tab_bounds`, `sheet_bounds_with`, `snackbar_bounds`, `intersection` | Shared paint/hit geometry |
| `RouteStack`, `Snackbar` | Single-source detail stack (`push`/`pop`/`can_pop`) and transient feedback strip |
| `Canvas` / `canvas(context)` | Frame recording plus temporary text-layout ownership |
| `Canvas.label`, `card`, `button`, `button_tone`, `chip`, `row`, `icon` | Mobile typography, danger tone and component appearance |
| `Canvas.navigation`, `sheet`, `scrollbar`, `snackbar` | Bottom navigation / rail, modal sheets, edge indicator and toast |
| `Touch` / `touch(identity)` | Canvas-generation-scoped press, kinetic fling, overscroll and edge swipe state |
| `Touch.begin`, `target`, `event`, `pressed`, `step_at`, `animating` | Register in paint order, dispatch actions and step momentum |
| `Touch.scroll_region`, `offset`, `block_scroll`, `set_edge_back` | Bounded scrolling, modal suspension and left-edge swipe back |
| `Touch.swipe_down`, `swipe_back` | Sheet header dismissal and left-edge back navigation before pointer-up |
| `set_back_enabled`, `set_dark_appearance`, `set_overlay` | Native Back ownership and system-bar appearance |

Record one complete frame with `Canvas.begin()` and `Canvas.present()`. Labels
remain alive until the frame is admitted; then its lease retains them. Dispose
the canvas on window close. Custom drawing can use Canvas's Draw forwarding
methods or a short exclusive borrow of its public `frame` field.

Register targets using the same rectangles that are painted. Clip scrollable
row/button targets with `intersection()` so scrolled content cannot intercept a
header or navigation tap. Use target id 0 to block a modal's non-action surface,
then register modal actions above it. Preserve the underlying offset with
`block_scroll()` and reapply `scroll_region()` after dismissing the sheet.

The native host extends theme backgrounds, modal scrims and sheet surfaces
through safe areas and updates system-bar contrast. Capture Android Back only
while a sheet/detail can handle it. At the root, Back backgrounds the task.

## Run the example

```sh
bin/xu build examples/phone_gallery --phone --target ios-simulator-arm64 \
  --bundle-id org.xulang.phonedesign -o build/phone-design
build/phone-design/build.sh
xcrun simctl install booted build/phone-design/build/XuPhone.app
xcrun simctl launch booted org.xulang.phonedesign
```

Use `--target android-arm64` for the Android project. Build prerequisites and
signing are in `../host/phone/README.md`. The example's records live only in the
current process; this is stated in Settings and Detail view. Full native soft-keyboard
input (`TextInput`), per-control screen reader semantics and exact native glyph shaping
are not provided by this Canvas profile. Components require a viewport of at least
240 by 240 logical pixels.
