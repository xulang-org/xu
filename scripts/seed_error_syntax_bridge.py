#!/usr/bin/env python3
"""Build a disposable transition compiler before `>>>` error-handling syntax.

An older published seed (such as v0.14.2) only lexes legacy `>>` throws and
`or` / `or >>` error handlers. Rewrite only non-string, non-comment `>>>`
error-handling tokens in a private copy of `src/` to compile a temporary
transition compiler once, then restart Gen1 on the complete, unchanged current
source tree and require the normal fixed point.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def source_digest(source: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(source.rglob('*.xu')):
        digest.update(path.relative_to(source).as_posix().encode() + b'\0')
        digest.update(path.read_bytes() + b'\0')
    return digest.hexdigest()


def rewrite_error_syntax(text: str) -> tuple[str, int]:
    """Rewrite non-string, non-comment `>>>` error syntax to legacy `>>`/`or`."""
    out: list[str] = []
    n = len(text)
    i = 0
    count = 0
    line_stmt_start = True

    while i < n:
        ch = text[i]
        # Line comment
        if ch == '/' and i + 1 < n and text[i + 1] == '/':
            end = text.find('\n', i)
            if end == -1:
                out.append(text[i:])
                break
            out.append(text[i:end + 1])
            i = end + 1
            line_stmt_start = True
            continue
        # Block comment
        if ch == '/' and i + 1 < n and text[i + 1] == '*':
            end = text.find('*/', i + 2)
            if end == -1:
                out.append(text[i:])
                break
            seg = text[i:end + 2]
            out.append(seg)
            if '\n' in seg:
                line_stmt_start = True
            i = end + 2
            continue
        # Double-quoted string literal
        if ch == '"':
            j = i + 1
            while j < n:
                if text[j] == '\\' and j + 1 < n:
                    j += 2
                    continue
                if text[j] == '"':
                    j += 1
                    break
                j += 1
            out.append(text[i:j])
            i = j
            line_stmt_start = False
            continue
        # Backtick raw string literal
        if ch == '`':
            end = text.find('`', i + 1)
            j = n if end == -1 else end + 1
            out.append(text[i:j])
            i = j
            line_stmt_start = False
            continue
        # Triple-gt candidate
        if text.startswith('>>>', i):
            if line_stmt_start:
                out.append('>>')
                i += 3
                count += 1
                line_stmt_start = False
                continue
            j = i + 3
            while j < n and text[j] in (' ', '\t'):
                j += 1
            if j < n and text[j] == '(':
                out.append('or')
                i += 3
                count += 1
                continue
            out.append('or >>')
            i += 3
            count += 1
            line_stmt_start = False
            continue

        out.append(ch)
        if ch in ('\n', '{', ';'):
            line_stmt_start = True
        elif ch not in (' ', '\t', '\r'):
            line_stmt_start = False
        i += 1

    return ''.join(out), count


def prepare(source: Path, destination: Path) -> dict:
    shutil.copytree(source / 'src', destination / 'src')
    shutil.copy2(source / 'VERSION', destination / 'VERSION')
    rewritten_files = 0
    rewritten_tokens = 0
    for path in sorted((destination / 'src').rglob('*.xu')):
        original = path.read_text(encoding='utf-8')
        if '>>>' not in original:
            continue
        updated, n = rewrite_error_syntax(original)
        if n > 0:
            path.write_text(updated, encoding='utf-8')
            rewritten_files += 1
            rewritten_tokens += n
    if rewritten_tokens == 0:
        raise ValueError('No `>>>` syntax found in current source tree; refusing unrelated bridge')

    atomic_calls = 0
    atomic_pat = re.compile(r'\batomic_(load|store|add|cas)\(')
    for rel in ('src/runtime/core/core.xu', 'src/runtime/core/chan.xu'):
        p = destination / rel
        if p.is_file():
            txt = p.read_text(encoding='utf-8')
            new_txt, n_sub = atomic_pat.subn(r'boot_atomic_\1(', txt)
            if n_sub > 0:
                p.write_text(new_txt, encoding='utf-8')
                atomic_calls += n_sub
    if atomic_calls > 0:
        core_xu = destination / 'src/runtime/core/core.xu'
        helpers = (
            '\n'
            'fn boot_atomic_load(p c_ptr) int {\n'
            '    << rt_load(int(p), 8)\n'
            '}\n'
            'fn boot_atomic_store(p c_ptr, v int) {\n'
            '    rt_store(int(p), 8, v)\n'
            '}\n'
            'fn boot_atomic_add(p c_ptr, d int) int {\n'
            '    old := rt_load(int(p), 8)\n'
            '    rt_store(int(p), 8, old + d)\n'
            '    << old\n'
            '}\n'
            'fn boot_atomic_cas(p c_ptr, old int, new int) bool {\n'
            '    if rt_load(int(p), 8) == old {\n'
            '        rt_store(int(p), 8, new)\n'
            '        << true\n'
            '    }\n'
            '    << false\n'
            '}\n'
        )
        core_xu.write_text(core_xu.read_text(encoding='utf-8') + helpers, encoding='utf-8')

    return {
        'transition': 'error_syntax_v1',
        'rewritten_files': rewritten_files,
        'rewritten_tokens': rewritten_tokens,
        'rewritten_runtime_atomics': atomic_calls,
        'transition_source_sha256': source_digest(destination / 'src'),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('compiler_args', nargs=argparse.REMAINDER)
    args = parser.parse_args()

    seed = args.seed.resolve()
    source = args.source.resolve()
    destination = args.destination.resolve()
    output = args.output.resolve()
    if destination == source or destination == seed.parent.parent or destination.exists():
        raise ValueError('Transition must use a fresh private directory')

    record = prepare(source, destination)
    private_seed = destination / 'bin' / seed.name
    private_seed.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(seed, private_seed)
    private_seed.chmod(0o755)
    record['seed_sha256'] = hashlib.sha256(private_seed.read_bytes()).hexdigest()
    (destination / 'source.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    (destination / 'source.sha256').write_text(record['transition_source_sha256'] + '\n', encoding='utf-8')
    print('seed_error_syntax_bridge: ' + json.dumps(record, sort_keys=True), flush=True)

    sources = sorted((destination / 'src/cmd/compile').glob('*.xu'))
    main_source = destination / 'src/cmd/compile/main.xu'
    sources.remove(main_source)
    profile = args.compiler_args[1:] if args.compiler_args[:1] == ['--'] else args.compiler_args
    env = dict(os.environ, XU_ROOT=str(destination), XU_STDLIB_ROOT=str(destination / 'src'), XUPATH='')
    subprocess.run(
        [str(private_seed), 'build', *profile, str(main_source), *map(str, sources), '-o', str(output)],
        cwd=destination,
        env=env,
        check=True,
    )


if __name__ == '__main__':
    main()
