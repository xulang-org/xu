# Window and input service

SDK **0.12.3-dev.8** provides optional `#window` lifecycle/state and per-window
keyboard, pointer/wheel and text/IME queues. It creates no GPU device. `#gpu`
separately binds a typed window borrow to a presentation surface. Portable event
data lives in pure [`#window/events`](events/README.md); scenes, input actions,
GUI controls and rendering policy remain outside the service.

```xu
#window
#window/events

options := window.Options{title: "Example",width: 640,height: 360,
    resizable: true,high_pixel_density: true,hidden: false}
$target := window.open(&options) or >>
window.pump() or >>
for i in 0:events.QUEUE_CAPACITY {
    event := target.poll() or >>
    if event.kind == events.EVENT_NONE { <- }
    // Feed key events to application actions; release held actions on focus
    // loss, close or INPUT_RESET. Text/IME is independent of physical keys.
}
state := target.state() or >>
if state.close_requested { target.close() or >> }
```

Options are explicit: positive int32 logical dimensions and a title of
1...4096 UTF-8 bytes without NUL. Native creation may fail. `state()` snapshots
logical/pixel dimensions, close-request, minimized, visible and focused flags.
Resize/minimize/restore may complete asynchronously; pump and inspect state.
Pixel size need not equal logical size. A close request latches until actual
closure; it does not destroy the owner from inside event handling.

## Queue and input ownership

Call process-wide `pump()` once per update, then drain each window with `poll()`
until `EVENT_NONE`. Polling does not pump the OS. `pending_events()` reports the
copied queue length. SDL event/text pointers never escape the synchronous native
boundary; returned event strings remain valid after further pumping, queue
reuse and window closure. UTF-8 and IME codepoint selection ranges are validated
using the standard Xu UTF-8 library. Invalid input yields INPUT_RESET.

Each window holds at most 256 events, 65536 text bytes per event and 262144 queued
text bytes. Queue/text exhaustion, allocation failure or malformed data clears
the entire pending history and cached held input, leaving one INPUT_RESET with
a reason. Further events for that window drain without being recorded until
the reset is polled; the other windows remain independent. Close requests still
latch even while desynchronized. Check `state().close_requested` as well as events.
After reset/focus loss, repeats without a fresh non-repeat down cannot re-create
a held key. The application must release its own held actions/drags on reset,
focus loss and close; reset does not reconstruct discarded text or clicks.

`key_down(physical_key)` and `pointer_state()` snapshot accepted input after
pumping, not global physical hardware state or historical event state. Focus
loss, close and reset clear cached keys, modifiers, buttons and pointer position.
Pointer values retain fractions. Logical positions differ from surface pixels;
relative motion retains backend units. See the [event data contract](events/README.md)
for key namespaces, modifiers, wheel signs, button masks, timestamps and metadata.

`pump()` temporarily filters the current SDL queue without installing a permanent
watch/filter. Owned window/input events are copied and removed. Unsupported
owned events drain; touch, pen, gamepad, drag/drop and custom IME candidate-list
APIs are not provided. Foreign-window, user-defined and global quit events stay
for their external consumers. A global quit latches close and queues it at most
once per window. With no windows, pumping is a no-op that loads no SDL library.
Do not combine this loop with another consumer that drains the whole SDL queue.

## Text and pointer controls

Text delivery is opt-in through `start_text_input()` / `stop_text_input()`;
`text_input_active()` queries the backend flag. Text activation can open an OS
input method/screen keyboard and affect key delivery. Use text events for text,
not logical keycodes. `text_input_area(x,y,width,height,cursor)` sets the logical
caret area (positive width/height; cursor offset 0...width); clear it with
`clear_text_input_area()`. Selection offsets count codepoints, not bytes or
visual grapheme clusters. Custom editor/IME candidate rendering remains outside
this API. [SDL text activation](https://wiki.libsdl.org/SDL3/SDL_StartTextInput),
[editing offsets](https://wiki.libsdl.org/SDL3/SDL_TextEditingEvent).

`set_relative_pointer(bool)` and `set_pointer_grab(bool)` request backend modes;
queries are `relative_pointer()` and `pointer_grab()`. Platform support and focus
can constrain effective capture; failed requests throw. Mode changes stay outside
the event filter. Closing the native window releases its native input resources.

## Lifetime, backend and evidence

All owners/operations stay on the application main thread. `Window.id()` is a
never-reused process-local routing identity, not a pointer or raw constructor.
State and mutations validate identities. Explicit close and automatic drop
release queued text and presentation descendants before destroying the window.
Cleanup may wait for GPU completion and reports its first error. Stale owners
can close again; `live_count()` counts live window owners separately from GPU.

The backend uses SDL 3.2+ and shares private `internal/sdl` with GPU. Import of
`#window` compiles that source using the same SDK's `xu-native`; no SDL headers
or application native mapping is needed. SDL loads on first device/window open.
`XU_SDL_LIBRARY` selects one explicit library with no fallback. Window/device
owners hold separate balanced video references; the loader stays for process life.
The pure events package needs neither C tools nor SDL.

Native macOS/Linux/Windows 64-bit targets share the API. Metal presentation has
real macOS arm64 evidence. Input checks include actual SDL queue routing with
injected key/pointer/text events, exact public ABI/owned-text roundtrips, ASan
budget/failure/lifetime tests, and real macOS focus notifications. Real OS keyboard/text interaction remains unverified; injected events are
distinct from physical input. Installed SDK checks
compile input APIs/explicit missing-runtime handling and run pure event data;
they do not prove other-platform OS input or GPU execution.
