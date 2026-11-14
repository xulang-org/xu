#!/bin/sh
set -eu
cd "$(dirname "$0")"
sdk=iphoneos
triple=arm64-apple-ios16.4
if [ '@TARGET@' = ios-simulator-arm64 ]; then sdk=iphonesimulator; triple=arm64-apple-ios16.4-simulator; fi
sdkroot=$(xcrun --sdk "$sdk" --show-sdk-path)
mkdir -p build/XuPhone.app
xcrun --sdk "$sdk" clang++ -std=c++17 -O2 -target "$triple" -isysroot "$sdkroot" \
  -fno-omit-frame-pointer -fobjc-arc App.mm native/host/phone/host.cc native/host/phone/runtime.cc \
  native/host/xu_ui_mem.cc native/app.o -framework UIKit -framework WebKit \
  -framework Foundation -framework CoreGraphics -framework QuartzCore -o build/XuPhone.app/XuPhone
cp Info.plist canvas.html build/XuPhone.app/
if [ "$sdk" = iphonesimulator ]; then codesign --force --sign - build/XuPhone.app;
else
  : "${CODE_SIGN_IDENTITY:?Set CODE_SIGN_IDENTITY and embed a matching provisioning profile before installing on a device}"
  if [ -n "${PROVISIONING_PROFILE:-}" ]; then cp "$PROVISIONING_PROFILE" build/XuPhone.app/embedded.mobileprovision; fi
  if [ -n "${CODE_SIGN_ENTITLEMENTS:-}" ]; then
    codesign --force --sign "$CODE_SIGN_IDENTITY" --entitlements "$CODE_SIGN_ENTITLEMENTS" build/XuPhone.app
  else
    codesign --force --sign "$CODE_SIGN_IDENTITY" build/XuPhone.app
  fi
fi
printf 'Built %s/build/XuPhone.app\n' "$PWD"
