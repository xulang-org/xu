#!/usr/bin/env bash
# Use signed Ubuntu archives directly when the hosted runner's mirror list stalls.
set -euo pipefail

. /etc/os-release
arch=$(dpkg --print-architecture)
case "$arch" in
    amd64) mirrors=(https://archive.ubuntu.com/ubuntu https://mirrors.edge.kernel.org/ubuntu) ;;
    arm64) mirrors=(https://ports.ubuntu.com/ubuntu-ports https://mirror.fi.ossplanet.net/ubuntu-ports) ;;
    *) printf 'Unsupported Ubuntu package architecture: %s\n' "$arch" >&2; exit 1 ;;
esac

sources=$(mktemp --suffix=.sources "${RUNNER_TEMP:-/tmp}/xu-apt.XXXXXX")
trap 'rm -f -- "$sources"' EXIT
apt_options=(
    -o "Dir::Etc::sourcelist=$sources"
    -o 'Dir::Etc::sourceparts=-'
    -o Acquire::Retries=0
    -o Acquire::https::Timeout=15
)
for mirror in "${mirrors[@]}"; do
    cat > "$sources" <<EOF
Types: deb
URIs: $mirror
Suites: $VERSION_CODENAME $VERSION_CODENAME-updates $VERSION_CODENAME-security
Components: main universe restricted multiverse
Architectures: $arch
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF
    if sudo apt-get "${apt_options[@]}" -o APT::Update::Error-Mode=any update &&
       sudo apt-get "${apt_options[@]}" install -y "$@"; then
        exit 0
    fi
done
printf 'Unable to install Ubuntu CI packages: %s\n' "$*" >&2
exit 1
