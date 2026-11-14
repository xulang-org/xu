#!/bin/sh
set -eu
cd "$(dirname "$0")"
: "${ANDROID_HOME:?Set ANDROID_HOME to an SDK with platform 35, build-tools 35.0.0, NDK 27.2.12479018 and CMake 3.22.1}"
: "${JAVA_HOME:?Set JAVA_HOME to a JDK (17 or newer)}"
sdk="$ANDROID_HOME"
tools="$sdk/build-tools/35.0.0"
ndk="$sdk/ndk/27.2.12479018"
android="$sdk/platforms/android-35/android.jar"
cmake="$sdk/cmake/3.22.1/bin/cmake"
for path in "$android" "$cmake" "$tools/aapt2" "$tools/d8" "$ndk/build/cmake/android.toolchain.cmake" "$JAVA_HOME/bin/javac"; do
  if [ ! -f "$path" ]; then printf 'Missing Phone build prerequisite: %s\n' "$path" >&2; exit 1; fi
done
mkdir -p build/classes build/dex build/apk/assets build/apk/lib/arm64-v8a
"$cmake" -S app/src/main/cpp -B build/native -G Ninja \
  -DCMAKE_MAKE_PROGRAM="$sdk/cmake/3.22.1/bin/ninja" \
  -DCMAKE_TOOLCHAIN_FILE="$ndk/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-26 -DCMAKE_BUILD_TYPE=Release
"$cmake" --build build/native
"$JAVA_HOME/bin/javac" --release 17 -classpath "$android" -d build/classes \
  app/src/main/java/org/xulang/phone/MainActivity.java
"$JAVA_HOME/bin/jar" --create --file build/classes.jar -C build/classes .
"$tools/d8" --min-api 26 --lib "$android" --output build/dex build/classes.jar
# The IDE manifest uses AGP's applicationId; aapt2 needs it in its input XML.
sed 's/<manifest /<manifest package="@BUNDLE_ID@" /; s/<application /<uses-sdk android:minSdkVersion="26" android:targetSdkVersion="35"\/><application /' \
  app/src/main/AndroidManifest.xml > build/AndroidManifest.xml
"$tools/aapt2" link -I "$android" --manifest build/AndroidManifest.xml -o build/unsigned.apk
cp canvas.html build/apk/assets/
cp build/native/libxuphone.so build/apk/lib/arm64-v8a/
cp build/dex/classes.dex build/apk/
(cd build/apk && zip -q -r ../unsigned.apk assets lib classes.dex)
"$tools/zipalign" -P 16 -f 4 build/unsigned.apk build/aligned.apk
if [ ! -f build/debug.keystore ]; then
  "$JAVA_HOME/bin/keytool" -genkeypair -keystore build/debug.keystore -storepass android \
    -keypass android -alias androiddebugkey -dname 'CN=Android Debug,O=Android,C=US' \
    -keyalg RSA -keysize 2048 -validity 10000
fi
"$tools/apksigner" sign --ks build/debug.keystore --ks-pass pass:android \
  --ks-key-alias androiddebugkey --out build/XuPhone-debug.apk build/aligned.apk
"$tools/apksigner" verify build/XuPhone-debug.apk
printf 'Built %s/build/XuPhone-debug.apk\n' "$PWD"
