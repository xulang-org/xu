#!/bin/sh
set -eu
cd "$(dirname "$0")"
: "${ANDROID_HOME:?Set ANDROID_HOME to the Android SDK}"
: "${JAVA_HOME:?Set JAVA_HOME to JDK 17 or newer}"
tools="$ANDROID_HOME/build-tools/35.0.0"
ndk="${ANDROID_NDK_HOME:-$ANDROID_HOME/ndk/27.2.12479018}"
android="$ANDROID_HOME/platforms/android-35/android.jar"
cmake_bin="$ANDROID_HOME/cmake/3.22.1/bin/cmake"
for path in "$android" "$cmake_bin" "$tools/aapt2" "$tools/d8" "$ndk/build/cmake/android.toolchain.cmake" "$JAVA_HOME/bin/javac"; do
  if [ ! -f "$path" ]; then printf 'Missing game build prerequisite: %s\n' "$path" >&2; exit 1; fi
done
mkdir -p build/classes build/dex build/apk/lib/arm64-v8a
"$cmake_bin" -S . -B build/native -G Ninja \
  -DCMAKE_MAKE_PROGRAM="$ANDROID_HOME/cmake/3.22.1/bin/ninja" \
  -DCMAKE_TOOLCHAIN_FILE="$ndk/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-26 -DCMAKE_BUILD_TYPE=Release
"$cmake_bin" --build build/native --parallel "${XU_BUILD_JOBS:-4}"
for library in build/native/libmain.so build/native/native/SDL/libSDL3.so; do
  "$ndk/toolchains/llvm/prebuilt/$(uname -s | tr '[:upper:]' '[:lower:]')-x86_64/bin/llvm-readelf" \
    -lW "$library" > build/elf-alignment.txt
  awk '$1=="LOAD" { count++; if ($NF!="0x4000") bad=1 } END { exit (!count || bad) }' build/elf-alignment.txt
done
find native/SDL/android-project/app/src/main/java -name '*.java' > build/java-sources.txt
printf '%s\n' MainActivity.java >> build/java-sources.txt
"$JAVA_HOME/bin/javac" --release 17 -classpath "$android" -d build/classes @build/java-sources.txt
(cd build/classes && zip -q -r ../classes.jar .)
"$tools/d8" --min-api 26 --lib "$android" --output build/dex build/classes.jar
mkdir -p build/assets/resources
cp -R resources/. build/assets/resources/
"$tools/aapt2" link -I "$android" --manifest AndroidManifest.xml -A build/assets -o build/unsigned.apk
cp build/native/libmain.so build/apk/lib/arm64-v8a/
cp build/native/native/SDL/libSDL3.so build/apk/lib/arm64-v8a/
cp build/dex/classes.dex build/apk/
(cd build/apk && zip -q -r ../unsigned.apk lib classes.dex)
"$tools/zipalign" -P 16 -f 4 build/unsigned.apk build/aligned.apk
"$tools/zipalign" -c -P 16 4 build/aligned.apk
if [ ! -f build/debug.keystore ]; then
  "$JAVA_HOME/bin/keytool" -genkeypair -keystore build/debug.keystore -storepass android \
    -keypass android -alias androiddebugkey -dname 'CN=Android Debug,O=Android,C=US' \
    -keyalg RSA -keysize 2048 -validity 10000
fi
"$tools/apksigner" sign --ks build/debug.keystore --ks-pass pass:android \
  --ks-key-alias androiddebugkey --out build/XuPhoneGame-debug.apk build/aligned.apk
"$tools/apksigner" verify build/XuPhoneGame-debug.apk
printf 'Built %s/build/XuPhoneGame-debug.apk\n' "$PWD"
