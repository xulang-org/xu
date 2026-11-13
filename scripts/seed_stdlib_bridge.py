#!/usr/bin/env python3
"""Build a disposable compiler before importing source-backed runtime primitives.

An older published seed may preflight ordinary imports with a frontend that
cannot check runtime/core primitives. Use its SHA-bound SDK sources for math
and the string storage helper to compile the current compiler once. The caller
must then restart Gen1 against the complete, unchanged current stdlib and require
the normal fixed point. This transition artifact is never installed or counted
as a product generation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


RUNTIME_IMPORT = re.compile(r'^\s*(?:\w+\s+)?#runtime/core\b', re.MULTILINE)


def source_digest(source: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(source.rglob('*.xu')):
        digest.update(path.relative_to(source).as_posix().encode() + b'\0')
        digest.update(path.read_bytes() + b'\0')
    return digest.hexdigest()


def prepare(seed: Path, source: Path, destination: Path) -> dict:
    version_output = subprocess.check_output([str(seed), '--version'], text=True)
    # Published seeds can carry prerelease identities and terminal colors.
    plain = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', version_output)
    match = re.search(r'Xu Compiler Toolchain v(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)', plain)
    digest = hashlib.sha256(seed.read_bytes()).hexdigest()
    if not match:
        raise ValueError('Unrecognized hosted SDK seed identity: sha256=' + digest + ' output=' + repr(plain))
    version = match.group(1)
    print('seed_stdlib_bridge: original seed version=' + version + ' sha256=' + digest, flush=True)
    candidates = [seed.parent / '.xu-seed-sources' / digest, seed.parent.parent]
    sdk = next((p for p in candidates if (p / 'VERSION').is_file()
                and (p / 'VERSION').read_text().strip() == version
                and (p / 'src/cmd/compile/main.xu').is_file()), None)
    if sdk is None:
        raise ValueError('Matching published seed sources missing; restore its SDK again')
    current_math = source / 'src/math/float.xu'
    if not current_math.is_file() or 'core #runtime/core' not in current_math.read_text():
        raise ValueError('Unsupported current math runtime layout')
    old_math = sdk / 'src/math'
    if not (old_math / 'mod.xu').is_file():
        raise ValueError('Published SDK is missing its math source')
    for path in old_math.rglob('*.xu'):
        if RUNTIME_IMPORT.search(path.read_text()):
            raise ValueError('Published math already imports runtime/core; refusing unrelated recovery')
    shutil.copytree(source / 'src', destination / 'src')
    shutil.copy2(source / 'VERSION', destination / 'VERSION')
    shutil.rmtree(destination / 'src/math')
    shutil.copytree(old_math, destination / 'src/math')
    record = {'transition': 'math_runtime_v1', 'published_version': version,
              'published_seed_sha256': digest, 'math_source_sha256': source_digest(old_math)}
    storage = destination / 'src/strings/storage.xu'
    if storage.is_file() and RUNTIME_IMPORT.search(storage.read_text()):
        old_storage = sdk / 'src/strings/storage.xu'
        if not old_storage.is_file() or RUNTIME_IMPORT.search(old_storage.read_text()):
            raise ValueError('Published SDK is missing a seed-compatible string storage helper')
        shutil.copy2(old_storage, storage)
        record['string_storage_source_sha256'] = hashlib.sha256(old_storage.read_bytes()).hexdigest()
    record['transition_source_sha256'] = source_digest(destination / 'src')
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=Path, required=True, help='original published seed identity')
    parser.add_argument('--compiler', type=Path, required=True, help='effective seed after existing syntax bridges')
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('compiler_args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    seed, compiler = args.seed.resolve(), args.compiler.resolve()
    source, destination, output = args.source.resolve(), args.destination.resolve(), args.output.resolve()
    if destination == source or destination == seed.parent.parent or destination.exists():
        raise ValueError('Transition must use a fresh private source directory')
    record = prepare(seed, source, destination)
    # Legacy lookup also considers executable-relative SDK sources. Use one
    # consistent private root rather than letting a CI bin/xu shadow math.
    private_seed = destination / 'bin' / compiler.name
    private_seed.parent.mkdir()
    shutil.copy2(compiler, private_seed)
    private_seed.chmod(0o755)
    record['effective_seed_sha256'] = hashlib.sha256(private_seed.read_bytes()).hexdigest()
    (destination / 'source.json').write_text(json.dumps(record, indent=2) + '\n')
    (destination / 'source.sha256').write_text(record['transition_source_sha256'] + '\n')
    print('seed_stdlib_bridge: ' + json.dumps(record, sort_keys=True), flush=True)
    sources = sorted((destination / 'src/cmd/compile').glob('*.xu'))
    main_source = destination / 'src/cmd/compile/main.xu'
    sources.remove(main_source)
    profile = args.compiler_args[1:] if args.compiler_args[:1] == ['--'] else args.compiler_args
    env = dict(os.environ, XU_ROOT=str(destination), XU_STDLIB_ROOT=str(destination / 'src'), XUPATH='')
    subprocess.run([str(private_seed), 'build', *profile, str(main_source), *map(str, sources), '-o', str(output)],
                   cwd=destination, env=env, check=True)


if __name__ == '__main__':
    main()
