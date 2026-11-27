#!/bin/sh
set -eu
cd "$(dirname "$0")"
cmake -S . -B build/native -G Ninja -DCMAKE_SYSTEM_NAME=iOS \
  -DCMAKE_OSX_SYSROOT=iphoneos -DCMAKE_OSX_ARCHITECTURES=arm64 \
  -DCMAKE_OSX_DEPLOYMENT_TARGET=16.4 -DCMAKE_BUILD_TYPE=Release
cmake --build build/native --parallel "${XU_BUILD_JOBS:-4}"
mkdir -p build/XuPhoneGame.app
cp build/native/XuPhoneGame.app/XuPhoneGame Info.plist build/XuPhoneGame.app/
if [ -f ca-bundle.pem ]; then cp ca-bundle.pem build/XuPhoneGame.app/; fi
if [ -d icons ]; then cp icons/AppIcon*.png build/XuPhoneGame.app/; fi
mkdir -p build/XuPhoneGame.app/xu-resources
cp -R resources/. build/XuPhoneGame.app/xu-resources/
if [ -n "${PROVISIONING_PROFILE:-}" ]; then
  cp "$PROVISIONING_PROFILE" build/XuPhoneGame.app/embedded.mobileprovision
fi
if [ -n "${CODE_SIGN_IDENTITY:-}" ]; then
  if [ -n "${CODE_SIGN_ENTITLEMENTS:-}" ]; then
    codesign --force --sign "$CODE_SIGN_IDENTITY" --entitlements "$CODE_SIGN_ENTITLEMENTS" build/XuPhoneGame.app
  else
    codesign --force --sign "$CODE_SIGN_IDENTITY" build/XuPhoneGame.app
  fi
  printf 'Built and signed %s/build/XuPhoneGame.app; device installation also requires matching provisioning.\n' "$PWD"
else
  printf 'Built unsigned %s/build/XuPhoneGame.app; signing and provisioning are required before installation.\n' "$PWD"
fi
