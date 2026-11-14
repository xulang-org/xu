# Phone applications

Phone packaging extends the Xu 0.12.3 compiler with native ARM64 application
objects and system-owned iOS / Android application shells. The Xu application,
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
directory with `xu.xun`. The destination must not exist. Generation uses a
staging directory and publishes it only after compilation and copying succeed.
Rebuild Xu sources by generating into another directory. The initial package
uses a fixed XuPhone application name and the supplied bundle/application ID.

## UI profile

Use one root `ui.Window` with `draw.attach`, wait for `EV_CANVAS_READY`, and
record complete `draw.Frame` values. The host retains the previous frame while
idle. Native iOS and Android shells render **edge-to-edge**; `ui.metrics_of`
reports the full logical viewport and the host pushes safe-area cutouts plus
soft-keyboard (`ime_bottom`) insets (`xu_phone_insets`, readable via `#ui/phone`
`host_insets()`) and accessibility reduced-motion state (`xu_phone_reduced_motion`,
readable via `reduced_motion()` or `EV_CANVAS_PREFERENCES`). Rotation and IME changes
update metrics without recreating the Xu application. Single-finger input maps
to the existing pointer down/move/up/cancel events with monotonic timestamps for
kinetic scrolling and left-edge swipe back. Focus/blur follow the mobile
application lifecycle. See [the Phone UI design guide](../../phone/README.md).
`xu_target_os()` retains the Darwin/Linux runtime ABI; use `phone.platform()` for
the application platform.

This initial profile supports shapes, transforms, clipping, paths, images and
display lists. Text uses system fonts, font weights, alignment and bounded single-line ellipsis.
Its layout metrics remain estimated;
full shaping, wrapped text, native IME, accessibility semantics per control,
offscreen surfaces, multiple windows, embedded WebView controls, desktop menus,
tray icons and desktop dialogs are not implemented. Unsupported asynchronous
services complete with `REQUEST_UNSUPPORTED`; native text sessions report
`XUTI_NATIVE_UNAVAILABLE`. These boundaries apply even when an application
imports the broader desktop UI API. Legacy string drawing commands are not the
Phone frame API.

The mobile runtime translates its supported memory, clock, file descriptor and
sleep calls to public libc APIs. It emits no private iOS `svc` syscall path.
The full desktop process, filesystem and network API surface is not yet a
mobile compatibility promise; unavailable services return `ENOSYS`.

The three packaging targets are `ios-arm64`, `ios-simulator-arm64` and
`android-arm64`. x86 simulators, physical-device interaction, release credentials
and store acceptance require separate validation.

The minimal `examples/phone_counter` remains available for the host/frame
round-trip. Use `examples/phone_gallery` to start from a designed mobile UI.
