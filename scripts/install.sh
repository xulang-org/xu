#!/usr/bin/env bash
# Xu Programming Language — Cross-platform Development Environment Installer
# Supports offline installation (from unpacked bundle) and online installation (curl | bash).
set -euo pipefail

# ANSI color codes
BOLD=$'\033[1m'
GREEN=$'\033[0;32m'
BLUE=$'\033[0;34m'
YELLOW=$'\033[0;33m'
CYAN=$'\033[0;36m'
RED=$'\033[0;31m'
NC=$'\033[0m' # No Color

print_banner() {
    printf "%b" "${CYAN}${BOLD}"
    cat << 'EOF'
  __  __
  \ \/ /   _   _
   \  /   | | | |   Xu Programming Language
   /  \   | |_| |   Fast, Safe, GC-Free Systems Language
  /_/\_\   \__,_|   Development Environment Installer
EOF
    printf "%b\n" "${NC}"
}

log_info() { printf "${BLUE}[INFO]${NC} %b\n" "$1"; }
log_ok()   { printf "${GREEN}[OK]${NC} %b\n" "$1"; }
log_warn() { printf "${YELLOW}[WARN]${NC} %b\n" "$1"; }
log_err()  { printf "${RED}[ERROR]${NC} %b\n" "$1" >&2; }

# Detect operating system and architecture
detect_platform() {
    local os arch
    os="$(uname -s | tr '[:upper:]' '[:lower:]')"
    arch="$(uname -m)"

    case "$os" in
        darwin)  os="macos" ;;
        linux)   os="linux" ;;
        msys*|mingw*|cygwin*) os="windows" ;;
        *)
            log_err "Unsupported operating system: $os"
            exit 1
            ;;
    esac

    case "$arch" in
        x86_64|amd64)     arch="x64" ;;
        arm64|aarch64)   arch="arm64" ;;
        loongarch64)     arch="loongarch64" ;;
        riscv64)         arch="riscv64" ;;
        *)
            log_err "Unsupported CPU architecture: $arch"
            exit 1
            ;;
    esac

    echo "${os}-${arch}"
}

usage() {
    cat << EOF
Xu Development Environment Installer

Usage:
  install.sh [options]
  curl -fsSL https://xulang.org/install.sh | bash -s -- [options]

Options:
  --prefix <DIR>       Install directory (default: existing PATH SDK, otherwise ~/.xu; or \$XU_INSTALL_DIR)
  --version <VER>      Version to install when downloading (default: latest stable or \$XU_VERSION)
  --online             Force downloading release archive even if executed from local bundle
  --no-modify-path     Do not append environment variables to shell config files
  -y, --yes            Assume yes to all prompts
  -h, --help           Show this help message
EOF
}

# Configuration defaults
DEFAULT_INSTALL_DIR="$HOME/.xu"
INSTALL_DIR="${XU_INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"
PREFIX_EXPLICIT=0
if [[ -n "${XU_INSTALL_DIR:-}" ]]; then PREFIX_EXPLICIT=1; fi
DOWNLOAD_BASE_URL="${XU_DOWNLOAD_URL:-https://github.com/xulang-org/xu/releases/download}"
FALLBACK_VERSION="0.10.7"
TARGET_VERSION="${XU_VERSION:-}"
MODIFY_PATH=1
AUTO_YES=0
FORCE_ONLINE=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prefix)
            INSTALL_DIR="$2"
            PREFIX_EXPLICIT=1
            shift 2
            ;;
        --version)
            TARGET_VERSION="$2"
            shift 2
            ;;
        --online)
            FORCE_ONLINE=1
            shift
            ;;
        --no-modify-path)
            MODIFY_PATH=0
            shift
            ;;
        -y|--yes)
            AUTO_YES=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            log_err "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

print_banner

PLATFORM=$(detect_platform)
if [[ "$PLATFORM" == windows-* ]]; then
    log_err "Windows detected. Please use install.ps1 from PowerShell:"
    echo "  irm https://xulang.org/install.ps1 | iex"
    exit 1
fi
log_info "Detected host platform: ${BOLD}${PLATFORM}${NC}"
log_info "Target install directory: ${BOLD}${INSTALL_DIR}${NC}"

IS_LOCAL_SCRIPT=0
SCRIPT_DIR=""
# A legitimate local script invocation requires a real, readable regular file on disk.
# When invoked via pipe (e.g. curl ... | bash), BASH_SOURCE[0] is empty or /dev/fd/*
if [[ "$FORCE_ONLINE" -eq 0 && -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" && -r "${BASH_SOURCE[0]}" ]]; then
    case "${BASH_SOURCE[0]}" in
        /dev/*|/proc/*)
            IS_LOCAL_SCRIPT=0
            ;;
        *)
            SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
            if [[ -n "$SCRIPT_DIR" && -d "$SCRIPT_DIR" ]]; then
                IS_LOCAL_SCRIPT=1
            fi
            ;;
    esac
fi

SOURCE_DIR=""
# Check if SCRIPT_DIR is inside an unpacked distribution bundle
if [[ "$IS_LOCAL_SCRIPT" -eq 1 && -n "$SCRIPT_DIR" ]]; then
    for candidate in "$SCRIPT_DIR" "$SCRIPT_DIR/.."; do
        candidate="$(cd "$candidate" 2>/dev/null && pwd || true)"
        if [[ -n "$candidate" && -d "$candidate/src" ]]; then
            if [[ -f "$candidate/VERSION" || -f "$candidate/TARGET" || -d "$candidate/bin" ]]; then
                SOURCE_DIR="$candidate"
                log_info "Found local offline distribution files in: $SOURCE_DIR"
                break
            fi
        fi
    done
fi

# Resolve version
if [[ -z "$TARGET_VERSION" ]]; then
    if [[ -n "$SOURCE_DIR" && -f "$SOURCE_DIR/VERSION" ]]; then
        TARGET_VERSION="$(cat "$SOURCE_DIR/VERSION" | tr -d '[:space:]')"
    else
        # Try resolving latest official release from GitHub with a fast 2s timeout
        LATEST_TAG=$(curl -sSL --connect-timeout 2 -m 3 -H "Accept: application/vnd.github.v3+json" https://api.github.com/repos/xulang-org/xu/releases/latest 2>/dev/null | grep '"tag_name":' | head -n 1 | sed -E 's/.*"v?([^"]+)".*/\1/' || true)
        if [[ -n "$LATEST_TAG" && "$LATEST_TAG" =~ ^[0-9]+\.[0-9]+\.[0-9]+ ]]; then
            TARGET_VERSION="$LATEST_TAG"
            log_info "Resolved latest release version: ${BOLD}v${TARGET_VERSION}${NC}"
        else
            TARGET_VERSION="$FALLBACK_VERSION"
        fi
    fi
fi

TMP_DIR=""
cleanup() {
    if [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then
        rm -rf "$TMP_DIR"
    fi
}
trap cleanup EXIT

if [[ -z "$SOURCE_DIR" ]]; then
    log_info "Preparing to download online release v${TARGET_VERSION} for ${PLATFORM}..."
    ARCHIVE_NAME="xu-v${TARGET_VERSION}-${PLATFORM}.tar.gz"
    ARCHIVE_URL="${DOWNLOAD_BASE_URL}/v${TARGET_VERSION}/${ARCHIVE_NAME}"

    TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/xu_install_XXXXXX")"
    ARCHIVE_DEST="$TMP_DIR/$ARCHIVE_NAME"

    log_info "Downloading ${ARCHIVE_URL}..."
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --connect-timeout 15 --retry 2 "$ARCHIVE_URL" -o "$ARCHIVE_DEST"
    elif command -v wget >/dev/null 2>&1; then
        wget -q --tries=2 --timeout=15 -O "$ARCHIVE_DEST" "$ARCHIVE_URL"
    else
        log_err "Neither curl nor wget found. Please install curl or wget."
        exit 1
    fi

    log_info "Extracting bundle..."
    tar -xzf "$ARCHIVE_DEST" -C "$TMP_DIR"

    # Intelligent root discovery: find directory containing src/ and VERSION
    if [[ -d "$TMP_DIR/src" && -f "$TMP_DIR/VERSION" ]]; then
        SOURCE_DIR="$TMP_DIR"
    else
        for sub in "$TMP_DIR"/*; do
            if [[ -d "$sub" && -d "$sub/src" && -f "$sub/VERSION" ]]; then
                SOURCE_DIR="$sub"
                break
            fi
        done
        if [[ -z "$SOURCE_DIR" ]]; then
            found_src=$(find "$TMP_DIR" -maxdepth 2 -type d -name "src" 2>/dev/null | head -n 1 || true)
            if [[ -n "$found_src" ]]; then
                SOURCE_DIR="$(dirname "$found_src")"
            fi
        fi
    fi

    if [[ -z "$SOURCE_DIR" || ! -d "$SOURCE_DIR" ]]; then
        log_err "Failed to locate extracted distribution files in $TMP_DIR."
        exit 1
    fi
fi

# Pre-flight validation
if [[ ! -d "$SOURCE_DIR/src" || ! -f "$SOURCE_DIR/VERSION" ]]; then
    log_err "Invalid Xu distribution: src/ or VERSION is missing in $SOURCE_DIR."
    exit 1
fi

if [[ -f "$SOURCE_DIR/TARGET" ]]; then
    BUNDLE_TARGET="$(cat "$SOURCE_DIR/TARGET" | tr -d '[:space:]')"
    if [[ "$BUNDLE_TARGET" != "$PLATFORM" && "$BUNDLE_TARGET" != devkit-all ]]; then
        log_err "Bundle target '$BUNDLE_TARGET' does not match host '$PLATFORM'."
        exit 1
    fi
fi

BINARY_SOURCE="$SOURCE_DIR/bin"
if [[ -d "$BINARY_SOURCE/platform/$PLATFORM" ]]; then
    BINARY_SOURCE="$BINARY_SOURCE/platform/$PLATFORM"
fi

if [[ ! -x "$BINARY_SOURCE/xu" ]] || ! "$BINARY_SOURCE/xu" --version >/dev/null 2>&1; then
    log_err "Distribution compiler cannot run on $PLATFORM: $BINARY_SOURCE/xu"
    exit 1
fi

# Current SDKs own the complete replacement transaction. Keep the legacy
# copier only for old SDKs that do not yet advertise the native interface.
NATIVE_SETUP="$BINARY_SOURCE/xu-setup"
NATIVE_HELP=""
if [[ -x "$NATIVE_SETUP" ]]; then
    NATIVE_HELP="$("$NATIVE_SETUP" --help 2>/dev/null || true)"
fi
if [[ "$NATIVE_HELP" == *--no-modify-path* ]]; then
    NATIVE_ARGS=(--yes)
    if [[ "$PREFIX_EXPLICIT" -eq 1 ]]; then NATIVE_ARGS+=(--prefix "$INSTALL_DIR"); fi
    if [[ "$MODIFY_PATH" -eq 0 ]]; then NATIVE_ARGS+=(--no-modify-path); fi
    "$NATIVE_SETUP" "${NATIVE_ARGS[@]}"
    # Keep the online installer's existing editor integration after the native
    # transaction has verified the bundled extension and committed the SDK.
    if [[ "${XU_SKIP_EDITOR_INSTALL:-0}" != 1 ]] && command -v code >/dev/null 2>&1; then
        EDITOR_META="$SOURCE_DIR/editors/vscode/package.json"
        if [[ -f "$EDITOR_META" ]]; then
            EDITOR_NAME=$(sed -nE 's/.*"name"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' "$EDITOR_META" | head -n 1)
            EDITOR_VERSION=$(sed -nE 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' "$EDITOR_META" | head -n 1)
            if [[ "$EDITOR_NAME" =~ ^[A-Za-z0-9_-]+$ && "$EDITOR_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$ ]]; then
                EDITOR_VSIX="$SOURCE_DIR/editors/vscode/$EDITOR_NAME-$EDITOR_VERSION.vsix"
                if [[ -f "$EDITOR_VSIX" ]]; then
                    code --install-extension "$EDITOR_VSIX" --force >/dev/null 2>&1 && \
                        log_ok "VS Code extension installed successfully." || \
                        log_warn "Failed to install VS Code extension automatically."
                fi
            fi
        fi
    fi
    exit 0
fi
if [[ -f "$SOURCE_DIR/bundle.json" ]] && grep -q '"files"[[:space:]]*:' "$SOURCE_DIR/bundle.json"; then
    log_err "The SDK requires its transactional native installer, but it cannot run."
    exit 1
fi

# Prepare target install directory
mkdir -p "$INSTALL_DIR"
INSTALL_DIR="$(cd "$INSTALL_DIR" && pwd)"
if [[ "$INSTALL_DIR" == "$SOURCE_DIR" ]]; then
    log_err "Install directory must differ from source distribution. Use 'source env.sh' to activate in place."
    exit 1
fi

# 1. Binaries
log_info "Copying toolchain binaries..."
mkdir -p "$INSTALL_DIR/bin"
if [[ -d "$SOURCE_DIR/bin/platform/$PLATFORM" ]]; then
    cp -Rf "$SOURCE_DIR/bin/platform/$PLATFORM/." "$INSTALL_DIR/bin/"
elif [[ -d "$SOURCE_DIR/bin" ]]; then
    for b in xu xu-doctor xu-fmt xu-doc xu-map xu-desktop xu-setup xu-update xu-lsp xu-native; do
        if [[ -f "$SOURCE_DIR/bin/$b" ]]; then
            cp -f "$SOURCE_DIR/bin/$b" "$INSTALL_DIR/bin/"
        fi
    done
fi
chmod +x "$INSTALL_DIR/bin/"* 2>/dev/null || true

# 2. Standard library (src/)
log_info "Copying standard library (src/)..."
mkdir -p "$INSTALL_DIR/src"
cp -Rf "$SOURCE_DIR/src/." "$INSTALL_DIR/src/"

# 3. External modules (packages/)
PACKAGES_SOURCE="${XU_PACKAGES_ROOT:-$SOURCE_DIR/packages}"
if [[ -z "${XU_PACKAGES_ROOT:-}" && ! -d "$PACKAGES_SOURCE" ]]; then
    PACKAGES_SOURCE="$SOURCE_DIR/../packages"
    if [[ ! -d "$PACKAGES_SOURCE" ]]; then PACKAGES_SOURCE="$SOURCE_DIR/../xu-packages"; fi
fi
if [[ -n "${XU_PACKAGES_ROOT:-}" && ! -d "$PACKAGES_SOURCE" ]]; then
    log_err "XU_PACKAGES_ROOT does not exist: $PACKAGES_SOURCE"
    exit 1
fi
if [[ -d "$PACKAGES_SOURCE" ]]; then
    log_info "Copying external driver modules from: $PACKAGES_SOURCE"
    mkdir -p "$INSTALL_DIR/packages"
    if [[ -f "$PACKAGES_SOURCE/xu.xun" ]]; then cp -f "$PACKAGES_SOURCE/xu.xun" "$INSTALL_DIR/packages/xu.xun"; fi
    for module in "$PACKAGES_SOURCE"/*; do
        if [[ -d "$module" ]] && { [[ -f "$module/xu.xun" ]] || { [[ -f "$PACKAGES_SOURCE/xu.xun" ]] && compgen -G "$module/*.xu" > /dev/null; }; }; then
            cp -Rf "$module" "$INSTALL_DIR/packages/"
        fi
    done
else
    log_info "External driver repository absent; core toolchain installed."
fi

# 4. Native C headers (include/)
if [[ -d "$SOURCE_DIR/include" ]]; then
    log_info "Copying native headers (include/)..."
    mkdir -p "$INSTALL_DIR/include"
    cp -Rf "$SOURCE_DIR/include/." "$INSTALL_DIR/include/"
fi

# 5. VS Code extension (editors/vscode)
VSCODE_SOURCE="${XU_VSCODE_ROOT:-$SOURCE_DIR/editors/vscode}"
if [[ -z "${XU_VSCODE_ROOT:-}" && ! -d "$VSCODE_SOURCE" ]]; then
    VSCODE_SOURCE="$SOURCE_DIR/../vscode-xu"
    if [[ ! -d "$VSCODE_SOURCE" ]]; then VSCODE_SOURCE="$SOURCE_DIR/../vscode"; fi
    if [[ ! -d "$VSCODE_SOURCE" ]]; then VSCODE_SOURCE="$SOURCE_DIR/../xu-vscode"; fi
fi
if [[ -n "${XU_VSCODE_ROOT:-}" && ! -d "$VSCODE_SOURCE" ]]; then
    log_err "XU_VSCODE_ROOT does not exist: $VSCODE_SOURCE"
    exit 1
fi
VSIX_FILE=""
if [[ -d "$VSCODE_SOURCE" && -f "$VSCODE_SOURCE/package.json" ]]; then
    EXTENSION_NAME=$(sed -nE 's/.*"name"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' "$VSCODE_SOURCE/package.json" | head -n 1)
    EXTENSION_VERSION=$(sed -nE 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' "$VSCODE_SOURCE/package.json" | head -n 1)
    if [[ "$EXTENSION_NAME" =~ ^[A-Za-z0-9_-]+$ && "$EXTENSION_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+ ]]; then
        CURRENT_VSIX="$EXTENSION_NAME-$EXTENSION_VERSION.vsix"
        log_info "Copying VS Code extension from: $VSCODE_SOURCE"
        mkdir -p "$INSTALL_DIR/editors/vscode"
        for resource in package.json language-configuration.json README.md "$CURRENT_VSIX"; do
            if [[ -f "$VSCODE_SOURCE/$resource" ]]; then
                cp -f "$VSCODE_SOURCE/$resource" "$INSTALL_DIR/editors/vscode/$resource"
            fi
        done
        if [[ -f "$VSCODE_SOURCE/$CURRENT_VSIX" ]]; then
            VSIX_FILE="$INSTALL_DIR/editors/vscode/$CURRENT_VSIX"
        fi
    fi
else
    log_info "VS Code extension repository absent; core toolchain installed."
fi

# 6. Official examples (examples/)
EXAMPLES_CHECKOUT="${XU_EXAMPLES_ROOT:-$SOURCE_DIR/../examples}"
if [[ -z "${XU_EXAMPLES_ROOT:-}" && ! -d "$EXAMPLES_CHECKOUT" ]]; then EXAMPLES_CHECKOUT="$SOURCE_DIR/../xu-examples"; fi
EXAMPLES_SOURCE="$EXAMPLES_CHECKOUT/examples"
if [[ -d "$SOURCE_DIR/examples" ]]; then
    log_info "Copying official examples..."
    mkdir -p "$INSTALL_DIR/examples"
    cp -Rf "$SOURCE_DIR/examples/." "$INSTALL_DIR/examples/"
elif [[ -d "$EXAMPLES_SOURCE" ]]; then
    log_info "Copying official examples..."
    mkdir -p "$INSTALL_DIR/examples"
    cp -Rf "$EXAMPLES_SOURCE/." "$INSTALL_DIR/examples/"
fi
if [[ -d "$INSTALL_DIR/examples" ]]; then
    while IFS= read -r -d '' manifest; do
        nested="${manifest#"$INSTALL_DIR/examples/"}"
        package_path="../packages"
        while [[ "$nested" == */* ]]; do
            package_path="../$package_path"
            nested="${nested#*/}"
        done
        rewritten=$(mktemp "$manifest.XXXXXX")
        cp -p "$manifest" "$rewritten"
        sed -E "s@^([[:space:]]*\"?github\\.com/xulang-org/packages\"?[[:space:]]*:[[:space:]]*)file:.*@\\1file:$package_path@" "$manifest" > "$rewritten"
        mv -f "$rewritten" "$manifest"
    done < <(find "$INSTALL_DIR/examples" -type f -name xu.xun -print0)
fi

# 7. Metadata
for meta in README.md LICENSE VERSION TARGET bundle.json env.sh uninstall.sh; do
    if [[ -f "$SOURCE_DIR/$meta" ]]; then
        cp -f "$SOURCE_DIR/$meta" "$INSTALL_DIR/"
    elif [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/$meta" ]]; then
        cp -f "$SCRIPT_DIR/$meta" "$INSTALL_DIR/"
    elif [[ -f "$SOURCE_DIR/scripts/$meta" ]]; then
        cp -f "$SOURCE_DIR/scripts/$meta" "$INSTALL_DIR/"
    elif [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/scripts/$meta" ]]; then
        cp -f "$SCRIPT_DIR/scripts/$meta" "$INSTALL_DIR/"
    fi
done

# Ensure env.sh ALWAYS exists and is robust across zsh, bash, sh
cat << EOF > "$INSTALL_DIR/env.sh"
# Xu Development Environment Activation Script
if [ -n "\${ZSH_VERSION:-}" ]; then
    XU_ENV_SRC="\${(%):-%x}"
elif [ -n "\${BASH_SOURCE[0]:-}" ]; then
    XU_ENV_SRC="\${BASH_SOURCE[0]}"
else
    XU_ENV_SRC="\$0"
fi
XU_ENV_DIR="\$(cd "\$(dirname "\$XU_ENV_SRC")" 2>/dev/null && pwd || true)"
if [ -z "\$XU_ENV_DIR" ] || [ ! -d "\$XU_ENV_DIR/src" ]; then
    XU_ENV_DIR=$(printf '%q' "$INSTALL_DIR")
fi
export XU_ROOT="\$XU_ENV_DIR"
export XU_STDLIB_ROOT="\$XU_ROOT/src"
XU_ENV_BIN="\$XU_ROOT/bin"
XU_ENV_OS="\$(uname -s)"
XU_ENV_ARCH="\$(uname -m)"
case "\$XU_ENV_OS" in Darwin) XU_ENV_OS=macos ;; Linux) XU_ENV_OS=linux ;; esac
case "\$XU_ENV_ARCH" in arm64|aarch64) XU_ENV_ARCH=arm64 ;; x86_64|amd64) XU_ENV_ARCH=x64 ;; esac
if [ -d "\$XU_ENV_BIN/platform/\$XU_ENV_OS-\$XU_ENV_ARCH" ]; then
    XU_ENV_BIN="\$XU_ENV_BIN/platform/\$XU_ENV_OS-\$XU_ENV_ARCH"
fi
for XU_ENV_PATH in "\$XU_ROOT/packages" "\$XU_ROOT/src"; do
    [ -d "\$XU_ENV_PATH" ] || continue
    case ":\${XUPATH:-}:" in
        *":\$XU_ENV_PATH:"*) ;;
        *) export XUPATH="\$XU_ENV_PATH\${XUPATH:+:\$XUPATH}" ;;
    esac
done
case ":\$PATH:" in
    *":\$XU_ENV_BIN:"*) ;;
    *) export PATH="\$XU_ENV_BIN:\$PATH" ;;
esac
unset XU_ENV_PATH XU_ENV_DIR XU_ENV_BIN XU_ENV_OS XU_ENV_ARCH XU_ENV_SRC
echo "Xu environment activated: \$XU_ROOT"
EOF
chmod +x "$INSTALL_DIR/env.sh"

# Ensure uninstall.sh ALWAYS exists
cat << EOF > "$INSTALL_DIR/uninstall.sh"
#!/usr/bin/env bash
set -euo pipefail
PREFIX="\${1:-$INSTALL_DIR}"
echo "Removing Xu development environment from: \$PREFIX"
if [ -d "\$PREFIX" ]; then
    rm -rf "\$PREFIX"
    echo "[OK] Removed \$PREFIX"
fi
for rc in "\$HOME/.zshrc" "\$HOME/.bashrc" "\$HOME/.bash_profile" "\$HOME/.profile" "\$HOME/.config/fish/config.fish"; do
    if [ -f "\$rc" ] && grep -q "# >>> xu development environment >>>" "\$rc"; then
        sed -i.bak '/# >>> xu development environment >>>/,/# <<< xu development environment <<</d' "\$rc" 2>/dev/null || true
        rm -f "\${rc}.bak"
        echo "[OK] Cleaned \$rc"
    fi
done
echo "Xu has been uninstalled successfully."
EOF
chmod +x "$INSTALL_DIR/uninstall.sh"

log_ok "Core development files installed to: $INSTALL_DIR"

# Try installing VSCode extension if 'code' command is available
if [[ "${XU_SKIP_EDITOR_INSTALL:-0}" != 1 ]] && command -v code >/dev/null 2>&1 && [[ -n "$VSIX_FILE" && -f "$VSIX_FILE" ]]; then
    log_info "Detected VS Code CLI. Installing Xu Language extension..."
    code --install-extension "$VSIX_FILE" --force >/dev/null 2>&1 && \
        log_ok "VS Code extension installed successfully." || \
        log_warn "Failed to install VS Code extension automatically."
fi

# Configure Shell environment
if [[ "$MODIFY_PATH" -eq 1 ]]; then
    log_info "Configuring shell environment variables..."

    ENV_SNIPPET_START="# >>> xu development environment >>>"
    ENV_SNIPPET_END="# <<< xu development environment <<<"

    TARGET_RC_FILES=()

    # Detect all shells present in user home
    if [[ -f "$HOME/.zshrc" ]] || [[ "${SHELL:-}" == *"zsh"* ]]; then
        TARGET_RC_FILES+=("$HOME/.zshrc")
    fi
    if [[ -f "$HOME/.bashrc" ]]; then
        TARGET_RC_FILES+=("$HOME/.bashrc")
    fi
    if [[ -f "$HOME/.bash_profile" ]]; then
        TARGET_RC_FILES+=("$HOME/.bash_profile")
    fi
    if [[ -f "$HOME/.profile" ]]; then
        TARGET_RC_FILES+=("$HOME/.profile")
    fi
    if [[ -f "$HOME/.config/fish/config.fish" ]] || [[ "${SHELL:-}" == *"fish"* ]]; then
        TARGET_RC_FILES+=("$HOME/.config/fish/config.fish")
    fi

    # Fallback if no known rc file exists
    if [[ ${#TARGET_RC_FILES[@]} -eq 0 ]]; then
        case "$(basename "${SHELL:-bash}")" in
            zsh)  TARGET_RC_FILES+=("$HOME/.zshrc") ;;
            fish) TARGET_RC_FILES+=("$HOME/.config/fish/config.fish") ;;
            *)    TARGET_RC_FILES+=("$HOME/.bashrc") ;;
        esac
    fi

    # Deduplicate files
    UNIQUE_RC_FILES=()
    for rc in "${TARGET_RC_FILES[@]}"; do
        already=0
        for u in "${UNIQUE_RC_FILES[@]:-}"; do
            if [[ "$rc" == "$u" ]]; then already=1; break; fi
        done
        if [[ $already -eq 0 ]]; then UNIQUE_RC_FILES+=("$rc"); fi
    done

    for rc in "${UNIQUE_RC_FILES[@]}"; do
        mkdir -p "$(dirname "$rc")"
        touch "$rc"

        # Remove existing snippet if present
        if grep -q "$ENV_SNIPPET_START" "$rc"; then
            sed -i.bak "/$ENV_SNIPPET_START/,/$ENV_SNIPPET_END/d" "$rc" 2>/dev/null || true
            rm -f "${rc}.bak"
        fi

        if [[ "$rc" == *"/config.fish" ]]; then
            cat << EOF >> "$rc"
$ENV_SNIPPET_START
set -gx XU_ROOT "$INSTALL_DIR"
set -gx XU_STDLIB_ROOT "$INSTALL_DIR/src"
set -gx XUPATH "$INSTALL_DIR/src:$INSTALL_DIR/packages" \$XUPATH
fish_add_path "$INSTALL_DIR/bin"
$ENV_SNIPPET_END
EOF
        else
            cat << EOF >> "$rc"
$ENV_SNIPPET_START
if [ -f "$INSTALL_DIR/env.sh" ]; then
    source "$INSTALL_DIR/env.sh"
else
    export XU_ROOT="$INSTALL_DIR"
    export XU_STDLIB_ROOT="$INSTALL_DIR/src"
    export XUPATH="$INSTALL_DIR/src:$INSTALL_DIR/packages\${XUPATH:+:\$XUPATH}"
    export PATH="$INSTALL_DIR/bin:\$PATH"
fi
$ENV_SNIPPET_END
EOF
        fi
        log_ok "Updated environment variables in: $rc"
    done
fi

# Self-check compiler
log_info "Running Xu toolchain self-check..."
export XU_ROOT="$INSTALL_DIR"
export XU_STDLIB_ROOT="$INSTALL_DIR/src"
export XUPATH="$INSTALL_DIR/src:$INSTALL_DIR/packages"
export PATH="$INSTALL_DIR/bin:$PATH"

if [[ -x "$INSTALL_DIR/bin/xu" ]]; then
    XU_VER="$("$INSTALL_DIR/bin/xu" --version)"
    log_ok "Xu compiler is ready: ${BOLD}$XU_VER${NC}"
else
    log_err "Installed compiler is not executable."
    exit 1
fi

if [[ -x "$INSTALL_DIR/bin/xu-doctor" ]]; then
    echo
    "$INSTALL_DIR/bin/xu-doctor" || true
    echo
fi

printf "\n${GREEN}${BOLD}🎉 Xu development environment installed successfully!${NC}\n\n"
cat << EOF
Installed components:
  • Core compiler & toolchain: $INSTALL_DIR/bin (xu, xu-setup, xu-doctor, xu-fmt, xu-doc, xu-map, xu-desktop, xu-update, xu-lsp, xu-native)
  • Standard library (src):    $INSTALL_DIR/src
  • External driver modules:   $INSTALL_DIR/packages (redis, mysql, postgres, sqlite, etcd, etc.)
  • Native C headers:          $INSTALL_DIR/include
  • VS Code extension:         $INSTALL_DIR/editors/vscode
  • Official examples:         $INSTALL_DIR/examples

To get started:
  1. Reload your shell environment:
     source ~/.zshrc   # or source ~/.bashrc

  2. Or activate in your current terminal session:
     source $INSTALL_DIR/env.sh

  3. Compile and run an official example:
     xu run $INSTALL_DIR/examples/01_hello/main.xu

  4. Check toolchain diagnosis:
     xu doctor

EOF
