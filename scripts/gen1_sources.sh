#!/usr/bin/env sh
# Shared Gen1 source lists (POSIX sh, meant to be sourced, not executed).
#
#   cd "$(dirname "$0")/.."            # repo root
#   . ./scripts/gen1_sources.sh || exit 1
#
# Lists are discovered from the tree so newly split files are picked up
# automatically. Ordering is LC_ALL=C sorted for reproducibility; the compiler
# build list keeps src/cmd/compile/main.xu first as the build requires.
#
# Defines: GEN1_SRCS GEN1_SPAN GEN1_TOKEN GEN1_AST GEN1_LEXER GEN1_SCANNER
#          GEN1_PARSER GEN1_PRINTER GEN1_FORMAT GEN1_TYPES GEN1_PARSE

# Space-separated, C-locale sorted list of *.xu in a directory (may be empty).
xu_sorted_srcs() {
    (
        for _f in "$1"/*.xu; do
            [ -f "$_f" ] && printf '%s\n' "$_f"
        done
    ) | LC_ALL=C sort | tr '\n' ' ' | sed 's/ *$//'
}

# Compiler build list: main.xu first, everything else C-locale sorted.
xu_compile_srcs() {
    _main="src/cmd/compile/main.xu"
    _rest=$(
        (
            for _f in src/cmd/compile/*.xu; do
                [ -f "$_f" ] || continue
                [ "$_f" = "$_main" ] && continue
                printf '%s\n' "$_f"
            done
        ) | LC_ALL=C sort | tr '\n' ' ' | sed 's/ *$//'
    )
    printf '%s %s' "$_main" "$_rest" | sed 's/ *$//'
}

if [ ! -f src/cmd/compile/main.xu ]; then
    echo "gen1_sources.sh: src/cmd/compile/main.xu not found (run from repo root)" >&2
    return 1 2>/dev/null || exit 1
fi

GEN1_SRCS=$(xu_compile_srcs)
GEN1_SPAN=$(xu_sorted_srcs src/xu/span)
GEN1_TOKEN=$(xu_sorted_srcs src/xu/token)
GEN1_AST=$(xu_sorted_srcs src/xu/ast)
GEN1_LEXER=$(xu_sorted_srcs src/xu/lexer)
GEN1_SCANNER=$(xu_sorted_srcs src/xu/scanner)
GEN1_PARSER=$(xu_sorted_srcs src/xu/parser)
GEN1_PRINTER=$(xu_sorted_srcs src/xu/printer)
GEN1_FORMAT=$(xu_sorted_srcs src/xu/format)
GEN1_TYPES=$(xu_sorted_srcs src/xu/types)
GEN1_MIR=$(xu_sorted_srcs src/xu/mir)
GEN1_MC=$(xu_sorted_srcs src/xu/mc)
GEN1_TARGET=$(xu_sorted_srcs src/xu/target)
GEN1_CODEGEN=$(xu_sorted_srcs src/xu/codegen)
GEN1_OBJ=$(xu_sorted_srcs src/xu/obj)
GEN1_RTGEN=$(xu_sorted_srcs src/xu/rtgen)
GEN1_PKGMGR=$(xu_sorted_srcs src/xu/pkgmgr)
GEN1_DRIVER=$(xu_sorted_srcs src/xu/driver)
GEN1_MODEL=$(xu_sorted_srcs src/xu/target/chips/model)
GEN1_GENERIC=$(xu_sorted_srcs src/xu/target/chips/generic)
GEN1_APPLE_M1=$(xu_sorted_srcs src/xu/target/chips/apple_m1)
GEN1_ARM_A53=$(xu_sorted_srcs src/xu/target/chips/arm_a53)
GEN1_ARM_A76=$(xu_sorted_srcs src/xu/target/chips/arm_a76)
GEN1_CORTEX_M4=$(xu_sorted_srcs src/xu/target/chips/cortex_m4)
GEN1_X86_64_V3=$(xu_sorted_srcs src/xu/target/chips/x86_64_v3)
GEN1_ESP32_C3=$(xu_sorted_srcs src/xu/target/chips/esp32_c3)
GEN1_ESP32_LX6=$(xu_sorted_srcs src/xu/target/chips/esp32_lx6)

# Self-parse list: the compiler plus the src/xu packages it imports.
GEN1_PARSE="$GEN1_SRCS $GEN1_SPAN $GEN1_TOKEN $GEN1_AST $GEN1_LEXER $GEN1_SCANNER $GEN1_PARSER $GEN1_PRINTER $GEN1_FORMAT $GEN1_TYPES $GEN1_MIR $GEN1_MC $GEN1_TARGET $GEN1_CODEGEN $GEN1_OBJ $GEN1_RTGEN $GEN1_PKGMGR $GEN1_DRIVER $GEN1_MODEL $GEN1_GENERIC $GEN1_APPLE_M1 $GEN1_ARM_A53 $GEN1_ARM_A76 $GEN1_CORTEX_M4 $GEN1_X86_64_V3 $GEN1_ESP32_C3 $GEN1_ESP32_LX6"
