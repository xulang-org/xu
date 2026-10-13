# Shared skip rules for the language-compiler gate (gen1_test / programs_cross_check).
# Net-package tests stay in tests/fixtures and tests/gen1/programs for stdlib
# runners (`make fixtures`); they must not block compiler self-hosting.
#
# Source from repo root:  . ./scripts/lang_gate_skip.sh

# True if this gen1 program is a stdlib-parity / net / compress / G-track
# (crypto/sm*) exercise.
# Those stay in tests/gen1/programs for stdlib runners; they must not block
# the language-compiler self-hosting gate (Gen1 emit of some stdlib paths
# still diverges — e.g. LZW, large format_float).
lang_gate_skip_program() {
    local base
    base=$(basename "$1" .xu)
    case "$base" in
        *_stdlib*|*_gm*) return 0 ;;
    esac
    grep -qE '^#(net|compress)(/|[[:space:]]|$)' "$1"
}

# True if this fixture directory name is a net/http stdlib test.
lang_gate_skip_fixture() {
    case "$1" in
        net_*|http_*) return 0 ;;
    esac
    return 1
}
