# Application frames

`#app.next_frame()` suspends a Phone game application until the system requests
the next frame. It returns `false` during normal shutdown. A game keeps its
ordinary typed owners and local state around the loop; the host preserves its
execution stack on the SDL application thread. Errors propagate normally.

```xu
#app

fn update() int {
    $frames := 0
    while true {
        ready := app.next_frame() >>>
        if !ready { <- }
        frames += 1
        // Update and draw one bounded frame.
    }
    << frames
}
```

The host retains an 8 MiB guarded application stack. `next_frame` is the frame
boundary; it does not automatically run other Xu tasks or render anything.
Return promptly to that boundary, and allow `false` to unwind local owners.
Creating GPU resources, submitting frames and releasing owners stay on the
same SDL thread. On Android this differs from the Java UI thread.

In this host mode `window.pump()` only routes the copied callback inbox; SDL
alone pumps the OS queue. Event/text data is copied before callbacks return.

Calling `next_frame` from an ordinary executable without the game host throws.
The current implementation targets ARM64 iOS devices and Android. SDL GPU does
not support iOS Simulator. See the [Phone game profile](../ui/host/phone/README.md)
and `examples/phone_game` for a native GPU presentation probe.

`app.resume_epoch()` changes when the host enters the foreground. Reset the
simulation clock when it changes. Background entry also discards pending input
and delivers `EVENT_INPUT_RESET` with `RESET_APPLICATION_SUSPENDED` on the next
window pump. Held actions and touch captures must be released on reset/focus loss.
`app.is_hosted()` reports whether a Phone game host owns the execution stack,
allowing games to share frame loops across desktop and mobile targets.
`app.intercept_back(true)` requests Android system Back events as
`EVENT_BACK_REQUESTED` via `#window/events` instead of closing immediately;
`Window.safe_area()` and `EVENT_SAFE_AREA_CHANGED` expose the safe client
rectangle in logical window coordinates.

The game profile delivers independent touch down/move/up/cancel events through
`#window/events`, in logical window coordinates. `(device_id, touch_id)` identifies
a finger; both fields preserve all 64 bits and may be negative. Pressure is 0...1;
larger backend raw force saturates at one without resetting held fingers. This
does not calibrate force against each device's maximum possible force.
There are at most ten active touches per window; exceeding the bound resets input.
Touch-generated mouse events are suppressed to prevent duplicate actions.

List packaged files in the application's optional `phone.resources`, one relative
path per line. Use ASCII letters, digits, slash, dot, dash and underscore; absolute
paths, empty/dot/parent segments, duplicates and the reserved `resources.index`
name are rejected. Limits: 256 files, 16 MiB each, 64 MiB total. An absent manifest
packages an empty resource set. `app.resource_path("images/player.png")` resolves
a packaged path for normal file readers; it throws without a game resource root.
iOS stores files under `xu-resources` in the bundle (avoiding Apple's reserved
`Resources` bundle layout). Android extracts the explicit APK asset list into
app-private storage before starting Xu, overwriting it on each launch.

`app.data_path("arena-v1.json")` joins a path under a separate writable,
app-private root created by the host. It accepts the same relative path alphabet
and rejects traversal. Create any subdirectories explicitly with `os.mkdir_all`.
The root survives normal process restarts; uninstalling the app may remove it.
Android's extracted resources use a separate directory and do not overwrite save
files. The Phone runtime supports mkdir/stat/exclusive file writes/rename/remove
through public libc so consumers can publish a small save with a same-directory
temporary file followed by rename. Rename provides atomic replacement, not a
power-loss durability guarantee; this API adds no fsync or cloud backup policy.

Frame execution, GPU/window linking, touch routing, resource transport, private
data paths and basic foreground recovery are implemented. Mobile audio interruptions,
extended lifecycle pressure and broader device coverage remain separate stages.
Build success is not physical-device evidence.
