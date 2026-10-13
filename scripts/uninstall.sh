#!/usr/bin/env bash
# Xu Programming Language — Uninstaller
set -euo pipefail

INSTALL_DIR="${XU_INSTALL_DIR:-$HOME/.xu}"

printf "\033[1;33mRemoving Xu Development Environment from: %s\033[0m\n" "$INSTALL_DIR"

if [[ -d "$INSTALL_DIR" ]]; then
    rm -rf "$INSTALL_DIR"
    printf "\033[0;32m[OK] Directory %s removed.\033[0m\n" "$INSTALL_DIR"
fi

ENV_SNIPPET_START="# >>> xu development environment >>>"
ENV_SNIPPET_END="# <<< xu development environment <<<"

for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.profile" "$HOME/.config/fish/config.fish"; do
    if [[ -f "$rc" ]] && grep -q "$ENV_SNIPPET_START" "$rc"; then
        sed -i.bak "/$ENV_SNIPPET_START/,/$ENV_SNIPPET_END/d" "$rc" 2>/dev/null || true
        rm -f "${rc}.bak"
        printf "\033[0;32m[OK] Cleaned environment config from %s\033[0m\n" "$rc"
    fi
done

printf "\033[1;32mXu has been uninstalled successfully.\033[0m\n"
