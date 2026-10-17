if [ -n "${ZSH_VERSION:-}" ]; then
    XU_ENV_SRC="${(%):-%x}"
elif [ -n "${BASH_SOURCE[0]:-}" ]; then
    XU_ENV_SRC="${BASH_SOURCE[0]}"
else
    XU_ENV_SRC="$0"
fi
XU_ENV_DIR="$(cd "$(dirname "$XU_ENV_SRC")" && pwd)"
if [[ ! -d "$XU_ENV_DIR/src" && -d "$XU_ENV_DIR/../src" ]]; then XU_ENV_DIR="$(cd "$XU_ENV_DIR/.." && pwd)"; fi
export XU_ROOT="$XU_ENV_DIR"
export XU_STDLIB_ROOT="$XU_ROOT/src"
XU_ENV_BIN="$XU_ROOT/bin"
XU_ENV_OS="$(uname -s)"
XU_ENV_ARCH="$(uname -m)"
case "$XU_ENV_OS" in Darwin) XU_ENV_OS=macos ;; Linux) XU_ENV_OS=linux ;; esac
case "$XU_ENV_ARCH" in arm64|aarch64) XU_ENV_ARCH=arm64 ;; x86_64|amd64) XU_ENV_ARCH=x64 ;; esac
if [[ -d "$XU_ENV_BIN/platform/$XU_ENV_OS-$XU_ENV_ARCH" ]]; then
    XU_ENV_BIN="$XU_ENV_BIN/platform/$XU_ENV_OS-$XU_ENV_ARCH"
fi
for XU_ENV_PATH in "$XU_ROOT/packages" "$XU_ROOT/src"; do
    [[ -d "$XU_ENV_PATH" ]] || continue
    case ":${XUPATH:-}:" in
        *":$XU_ENV_PATH:"*) ;;
        *) export XUPATH="$XU_ENV_PATH${XUPATH:+:$XUPATH}" ;;
    esac
done
case ":$PATH:" in
    *":$XU_ENV_BIN:"*) ;;
    *) export PATH="$XU_ENV_BIN:$PATH" ;;
esac
unset XU_ENV_PATH XU_ENV_DIR XU_ENV_BIN XU_ENV_OS XU_ENV_ARCH XU_ENV_SRC
echo "Xu environment activated: $XU_ROOT"
