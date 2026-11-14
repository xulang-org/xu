# Phone design gallery / 小计

A mobile application built with reusable `#ui/phone` components. The three
screens demonstrate a dashboard, scrollable records and grouped settings.
Portrait uses bottom tabs and a fixed primary action; landscape uses a navigation
rail and two panes. Light/dark appearance covers the native safe areas as well
as the canvas.

Try recording a focus, reading or activity session, switch pages, change the
goal in its bottom sheet, drag the sheet header down, undo the latest record,
and cancel or confirm a reset. Scrolling never activates the row under a drag.
Records and selections survive rotation and page changes within this process;
records are not persisted between application launches.

```sh
bin/xu build examples/phone_gallery --phone --target ios-simulator-arm64 \
  --bundle-id org.xulang.phonedesign -o build/design-ios
build/design-ios/build.sh
xcrun simctl install booted build/design-ios/build/XuPhone.app
xcrun simctl launch booted org.xulang.phonedesign

bin/xu build examples/phone_gallery --phone --target android-arm64 \
  --bundle-id org.xulang.phonedesign -o build/design-android
ANDROID_HOME=/path/to/android-sdk JAVA_HOME=/path/to/jdk build/design-android/build.sh
```

`model.xu` owns application data/actions, `views.xu` composes mobile components,
and `main.xu` owns the event loop and canvas lifetime. See
`src/ui/phone/README.md` for the design and interaction contracts.
