# Phone counter

A native Xu worker renders a frame and handles touch events on iOS or Android.
The system WebView displays the local Canvas. Tap the red area to increment the
Xu counter; rotate the device to retain the counter and refresh canvas metrics.

From the SDK root:

```sh
bin/xu build examples/phone_counter --phone --target ios-simulator-arm64 \
  --bundle-id org.xulang.phonecounter -o build/counter-ios
build/counter-ios/build.sh
xcrun simctl install booted build/counter-ios/build/XuPhone.app
xcrun simctl launch booted org.xulang.phonecounter

bin/xu build examples/phone_counter --phone --target android-arm64 \
  --bundle-id org.xulang.phonecounter -o build/counter-android
ANDROID_HOME=/path/to/android-sdk JAVA_HOME=/path/to/jdk \
  build/counter-android/build.sh
```

See `src/ui/host/phone/README.md` for prerequisites, signing and the supported UI
profile. These commands require the Phone development compiler built from the
0.12.3 base; the original 0.12.3 release binary does not contain this new feature.
