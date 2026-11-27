# Phone applications

The Xu 0.12.4 phone toolchain generates native ARM64 application objects and
system-owned iOS and Android application shells. The Xu application,
heap and cooperative tasks execute as machine code on a libc worker thread.
Drawing runs in a local Canvas inside WKWebView / Android WebView. No Xu/WASM
interpreter, remote page or JavaScript implementation of application logic is
included.

```sh
make xu-phone
bin/xu build examples/phone_gallery --phone --target ios-simulator-arm64 \
  --bundle-id org.xulang.phonecounter -o build/counter-ios
build/counter-ios/build.sh
bin/xu build examples/phone_gallery --phone --target android-arm64 \
  --bundle-id org.xulang.phonecounter -o build/counter-android
ANDROID_HOME=/path/to/android-sdk JAVA_HOME=/path/to/jdk \
  build/counter-android/build.sh
```

`--target ios-arm64` generates the device variant. iOS requires macOS and Xcode,
with iOS 16.4 or newer on the destination. The simulator build is ad hoc signed;
installation uses `xcrun simctl install booted build/counter-ios/build/XuPhone.app`.
Device installation needs an Apple signing identity, matching provisioning
profile and entitlements. Supply `CODE_SIGN_IDENTITY`, `PROVISIONING_PROFILE`
and `CODE_SIGN_ENTITLEMENTS` to the device build script. Ad hoc signing does not
make a device build installable or suitable for distribution.

Android requires a JDK 17 or newer and SDK components `platforms;android-35`,
`build-tools;35.0.0`, `ndk;27.2.12479018`, and `cmake;3.22.1`. The build script
uses these SDK tools directly and generates `build/XuPhone-debug.apk`, including
verification of its debug signature. It does not need Gradle. Android Studio
may instead open the generated Gradle project (AGP 8.7.3, Gradle 8.9, JDK 17).
Android's minimum version is API 26; the native library uses 16 KiB alignment.
Release signing and store submission remain platform-toolchain operations.

The generated project includes its native object and host source closure; it
can build independently of the originating SDK checkout. Input is a module
directory with `xu.xun`. The destination must not exist unless `--force` is
passed (staging replaces the existing directory atomically only after
compilation and copying succeed). Supply `--app-name` and `--version` (or
`--app-version`) to customize the mobile display name and version string;
an optional `phone.resources` file in the application module directory packages
assets for both `ui` and `game` profiles. For the `game` profile, `XU_PHONE_SDL_SOURCE` accepts either a
git checkout or an unpacked SDL 3.4.14 source tree.

## UI profile

Use one root `ui.Window` with `draw.attach`, wait for `EV_CANVAS_READY`, and
record complete `draw.Frame` values. The host retains the previous frame while
idle. Native iOS and Android shells render **edge-to-edge**; `ui.metrics_of`
reports the full logical viewport and the host pushes safe-area cutouts plus
soft-keyboard (`ime_bottom`) insets (`xu_phone_insets`, readable via `#ui/phone`
`host_insets()`), accessibility reduced-motion state (`xu_phone_reduced_motion`,
readable via `reduced_motion()` or `EV_CANVAS_PREFERENCES`), system dark mode
and font scale (`xu_phone_system_appearance` -> `system_dark()`,
`xu_phone_font_scale` -> `font_scale()`), and writable data/resource roots
(`xu_phone_set_paths` -> `data_dir()`, `resource_dir()`). Rotation and IME changes
update metrics without recreating the Xu application. Single-finger input maps
to the existing pointer down/move/up/cancel events with monotonic timestamps for
kinetic scrolling and left-edge swipe back. Focus/blur follow the mobile
application lifecycle. See [the Phone UI design guide](../../phone/README.md).
`xu_target_os()` retains the Darwin/Linux runtime ABI; use `phone.platform()` for
the application platform.

This profile supports shapes, transforms, clipping, paths, images (Base64 RGBA
transfer in `XDF_IMAGE`), display lists, single-line and wrapped multiline text
layout/caret/hit queries, lightweight haptic cues (`xu_phone_haptic` /
`xu_phone_haptic_take`), host clipboard read/write via `#ui/requests`
(`xu_phone_set_clipboard` backed by `UIPasteboard` on iOS and
`ClipboardManager` on Android), and native soft-keyboard IME sessions (`TextInput`
via iOS `UITextInput` and Android `InputConnection`, `xu_phone_key`, and
`xu_phone_text_input_*`). Text uses system fonts, font weights, alignment,
bounded single-line ellipsis or word/CJK multiline wrapping (`line_height`), and
grapheme-clustered proportional/CJK layout metrics for caret placement and
selection. Accessibility semantics per control, offscreen surfaces, multiple
windows, embedded WebView controls, desktop menus, tray icons and desktop dialogs
are not implemented; unsupported asynchronous services (other than clipboard)
complete with `REQUEST_UNSUPPORTED`. Legacy string drawing commands are not the
Phone frame API.

The mobile runtime (`runtime.cc`) translates memory, clock, file descriptor,
directory enumeration (`getdirentries64`/`getdents64`), entropy (`arc4random_buf`
on iOS, `getrandom`/urandom on Android), sockets, `kqueue`/`epoll`/`poll` event
waits, and sleep calls to public POSIX/BSD/Bionic libc APIs. It emits no private
iOS `svc` syscall path. Unavailable syscalls return `-ENOSYS`.

The three packaging targets are `ios-arm64`, `ios-simulator-arm64` and
`android-arm64`. `android-x64` is not currently supported because Phone runtime
code generation (`emit_phone_arm64_runtime`), syscall stubs and `game_context.S`
target ARM64 only. Physical-device interaction, release credentials and store
acceptance require separate validation.

## Developer CLI & Packaging Flags

- `xu phone doctor [--strict]` — checks Xcode iOS/Simulator SDKs, Android SDK/NDK/CMake, JDK 17+, `sips`, and `XU_PHONE_SDL_SOURCE`.
- `xu phone devices` — lists available iOS Simulators (`xcrun simctl`) and connected ADB devices (`adb devices -l`).
- `xu phone run APP --target TARGET [...]` — packages, builds, and installs/launches onto iOS Simulator or Android device (pass `--build-only` to stop after building).
- `--internet` — opts in `android.permission.INTERNET` / `ACCESS_NETWORK_STATE` and bundles CA roots (`ca-bundle.pem`) on iOS.
- `--icon PNG` — slices an app PNG into iOS `AppIcon*.png` and Android `mipmap-*/ic_launcher.png`.
- `--orientation auto|portrait|landscape` & `--version-code N` — configure mobile orientation locks and bundle build numbers / Android `versionCode`.

The minimal `examples/phone_counter` remains available for the host/frame
round-trip. Use `examples/phone_gallery` to start from a designed mobile UI.
