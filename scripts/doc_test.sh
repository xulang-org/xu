#!/usr/bin/env bash
# Product xu-doc command regression: golden output, directory input, -o, and CLI errors.
set -euo pipefail
cd "$(dirname "$0")/.."

DOC_BIN=${XU_DOC_BIN:-bin/xu-doc}
[ -x "$DOC_BIN" ] || { echo "doc_test: missing $DOC_BIN" >&2; exit 1; }

doc_tmp=$(mktemp -d)
serve_pid=0
cleanup() {
    if [ "$serve_pid" -ne 0 ]; then
        kill "$serve_pid" 2>/dev/null || true
        wait "$serve_pid" 2>/dev/null || true
    fi
    rm -rf "$doc_tmp"
}
trap cleanup EXIT

"$DOC_BIN" tests/doc/basic.xu > "$doc_tmp/basic.md"
cmp -s tests/doc/basic.expected.md "$doc_tmp/basic.md" \
    || { diff -u tests/doc/basic.expected.md "$doc_tmp/basic.md"; exit 1; }

"$DOC_BIN" tests/doc -o "$doc_tmp/dir.md"
cmp -s tests/doc/basic.expected.md "$doc_tmp/dir.md" \
    || { diff -u tests/doc/basic.expected.md "$doc_tmp/dir.md"; exit 1; }

mkdir -p "$doc_tmp/tree/nested"
cp tests/doc/basic.xu "$doc_tmp/tree/nested/basic.xu"
"$DOC_BIN" "$doc_tmp/tree" -o "$doc_tmp/nested.md"
grep -q '### pub struct Box#T' "$doc_tmp/nested.md"

"$DOC_BIN" tests/doc_public.xu --public > "$doc_tmp/public.md"
grep -q '### pub const Visible' "$doc_tmp/public.md"
grep -q '### pub struct PublicBox' "$doc_tmp/public.md"
grep -q '### struct@ Contract' "$doc_tmp/public.md"
grep -q 'pub value int' "$doc_tmp/public.md"
if grep -Eq 'Hidden|Secret|helper|private int' "$doc_tmp/public.md"; then
    echo "doc_test: --public leaked a private declaration or field" >&2
    exit 1
fi

serve_port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')
"$DOC_BIN" tests/doc --serve --addr "127.0.0.1:$serve_port" > "$doc_tmp/serve.log" 2>&1 &
serve_pid=$!
serve_ready=0
for _ in {1..40}; do
    if curl --max-time 1 -fsS "http://127.0.0.1:$serve_port/health" > "$doc_tmp/health" 2>/dev/null; then
        serve_ready=1
        break
    fi
    sleep 0.05
done
test "$serve_ready" -eq 1
test "$(tr -d '\n' < "$doc_tmp/health")" = ok
curl --max-time 2 -fsS "http://127.0.0.1:$serve_port/" > "$doc_tmp/page.html"
curl --max-time 2 -fsS "http://127.0.0.1:$serve_port/docs.md" > "$doc_tmp/served.md"
test "$(curl --max-time 2 -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:$serve_port/missing")" = 404
test "$(curl --max-time 2 -sS -X POST -o /dev/null -w '%{http_code}' "http://127.0.0.1:$serve_port/")" = 405
grep -q 'XUDOCS · XU declarations' "$doc_tmp/page.html"
grep -q '### pub struct Box#T' "$doc_tmp/served.md"
kill "$serve_pid" 2>/dev/null || true
wait "$serve_pid" 2>/dev/null || true
serve_pid=0

"$DOC_BIN" --help | grep -q 'render Xu declarations as Markdown'
if "$DOC_BIN" --unknown >/dev/null 2>&1; then
    echo "doc_test: --unknown unexpectedly succeeded" >&2
    exit 1
fi
if "$DOC_BIN" tests/doc --addr 127.0.0.1:6060 >/dev/null 2>&1; then
    echo "doc_test: --addr without --serve unexpectedly succeeded" >&2
    exit 1
fi
if "$DOC_BIN" --addr >/dev/null 2>&1; then
    echo "doc_test: missing --addr value unexpectedly succeeded" >&2
    exit 1
fi

python3 - "$doc_tmp/basic.md" <<'PY'
from pathlib import Path
import sys

data = Path(sys.argv[1]).read_bytes()
if b"\0" in data:
    raise SystemExit("doc_test: NUL byte in Markdown output")
for required in (b"set(v string)", b"identity#T", b"borrow(a &a string) &a string", b"struct@ Reader", b"Done(string)", b"#path/filepath as fp", b"hello\\nworld"):
    if required not in data:
        raise SystemExit(f"doc_test: missing {required!r}")
PY

echo "doc_test: PASS"
