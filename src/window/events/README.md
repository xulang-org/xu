# Portable window event data

`#window/events` contains only Xu data/constants. It has no native compiler,
SDL, GPU, file, scene or window-creation dependency. `window.Window.poll()`
returns an owned `Event`; game input actions belong in engine adapters.

`EVENT_NONE` means an empty queue. Lifecycle events cover close, focus and
logical/pixel resize. Keyboard events separate physical USB HID keyboard-page
usages 4...231 (0 unknown) from logical keys: printable Unicode scalars, or
`KEY_SPECIAL_BASE + physical key` for named control/navigation keys. Unknown
or unsupported keys use 0. Modifier bits use the constants here, not SDL masks.
Text/IME events are separate from key presses; do not derive text from keycodes.

Pointer positions are fractional logical window coordinates; relative movement
retains backend units. Wheel dx/dy are normalized to positive right/up and retain
fractional steps. Button indices are 1...32; named constants cover left, middle,
right, back and forward. `buttons` uses bit `(button - 1)`.

`window_id` routes to a live window's process-local metadata identity, never a
native pointer or owner constructor. `device_id` is opaque backend metadata,
0 if unknown; it is not a persistent device identity. `timestamp_ns` is a backend
nanosecond timestamp, not wall time; reset/unavailable timestamps use 0.

Text is an independent validated UTF-8 string. Editing selection offsets/lengths
count Unicode codepoints, not UTF-8 bytes or grapheme clusters; -1 is unset.
Applications own text layout, grapheme navigation and editor behavior.

`EVENT_INPUT_RESET` explicitly reports loss of queued history: queue full,
text limit/budget, allocation failure or invalid input. Release held actions and
pointer drags. Focus loss and close also clear held state. See the window service
for queue progress, budgets and recovery; event constants alone start no service.
