# Window lifecycle

`#window` is an optional hosted window service. SDK **0.12.3-dev.7** provides
window creation, lifecycle pumping, logical/pixel size snapshots, visibility,
minimize/restore, resize and close. It creates no GPU device. `#gpu` separately
binds a typed window borrow to a presentation surface. Cameras, scenes, input
actions, GUI controls and rendering policy remain outside this service.

```xu
#window

options := window.Options{title: "Example",width: 640,height: 360,
    resizable: true,high_pixel_density: true,hidden: false}
$target := window.open(&options) or >>
window.pump() or >>
state := target.state() or >>
assert(state.width > 0 && state.pixel_width > 0)
target.close() or >>
```

Options are explicit; dimensions are positive int32 logical units, while title
storage is 1...4096 UTF-8 bytes without NUL. Native creation may still fail.
`state()` snapshots logical dimensions, pixel dimensions, close-request,
minimized, visible and focused flags in one native call. Resize/minimize/restore
requests may complete asynchronously: pump events and inspect state. Pixel
dimensions need not equal logical dimensions. A close request is latched until
the window is closed; it does not destroy the window from inside event handling.

Keep all owners and operations on the application main thread. `Window.id()` is
a process-local routing identity, never reused by this backend; it is not a
native pointer or a public raw-handle constructor. State and mutations validate
the current identity. Explicit `close` and automatic `drop` release ownership.
Closing a window first safely tears down its presentation binding and acquired
frame, then destroys the native window. Cleanup may wait for GPU completion;
the first failure is reported after cleanup. A stale owner can close again
safely. `live_count()` counts live window owners, independently of GPU stats.

`pump()` services owned lifecycle events without installing a permanent SDL
filter. Foreign-window, application-defined and global quit events stay in
SDL's queue for other users; global quit also latches owned close requests.
Owned native input/text events are currently drained to bound the queue, but
this API does not expose a keyboard/mouse/text event stream yet. Application
input integration and GUI controls require additional APIs. With no owned
windows, pumping is a no-op.

The first backend uses SDL 3.2+ and shares the private source backend/loader with
GPU. Import compiles that backend using the same SDK's `xu-native`; no SDL
development headers or application native mapping is needed. SDL loads only
when opening a device/window. `XU_SDL_LIBRARY` selects one explicit library
path and disables fallback. This replaces the unpublished GPU-specific name.
Window/device owners hold separate balanced SDL video references; closing one
does not shut down unrelated users. The loader stays alive for the process.

Native macOS/Linux/Windows 64-bit targets share the API. Real window/GPU
presentation evidence currently covers macOS arm64 Metal. A dummy-video test
also checks window use without creating a GPU, event preservation and SDL
reference isolation. Installed-SDK compile/missing-runtime checks do not prove
window presentation or GPU availability on CI.
