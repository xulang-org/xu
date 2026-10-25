#!/usr/bin/env python3
"""Build a disposable transition compiler from an older published SDK's sources.

Only the legacy constant-case check is removed in the private copy. This
compiler is never a product generation: the caller restarts Gen1 on the full,
unchanged current source and still requires the normal fixed point.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess


LEGACY_GUARD = ('    if k == ast.nk_const {\n'
                '        c.require_snake(p, n, "const")\n'
                '    }\n')


def source_digest(source: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(source.rglob('*.xu')):
        digest.update(path.relative_to(source).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def prepare(seed: Path, destination: Path) -> str:
    output = subprocess.check_output([str(seed), '--version'], text=True)
    match = re.search(r'Xu Compiler Toolchain v(\d+\.\d+\.\d+) \(self-hosted\)', output)
    if not match:
        raise ValueError('Constant migration requires a published hosted SDK seed')
    version = match.group(1)
    digest = hashlib.sha256(seed.read_bytes()).hexdigest()
    candidates = [seed.parent / '.xu-seed-sources' / digest, seed.parent.parent]
    sdk = next((p for p in candidates if (p / 'VERSION').is_file()
                and (p / 'VERSION').read_text().strip() == version
                and (p / 'src/cmd/compile/main.xu').is_file()), None)
    if sdk is None:
        raise ValueError('Matching seed sources missing; restore the published SDK again')
    checker = sdk / 'src/xu/types/check_00_names.xu'
    text = checker.read_text()
    if text.count(LEGACY_GUARD) != 1:
        raise ValueError('Seed does not have the supported legacy constant-case check')
    shutil.copytree(sdk / 'src', destination / 'src')
    shutil.copy2(sdk / 'VERSION', destination / 'VERSION')
    (destination / 'src/xu/types/check_00_names.xu').write_text(text.replace(LEGACY_GUARD, ''))
    return source_digest(destination / 'src')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('compiler_args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    seed, destination, output = args.seed.resolve(), args.destination.resolve(), args.output.resolve()
    digest = prepare(seed, destination)
    print('seed_const_bridge: disposable published-SDK source sha256=' + digest, flush=True)
    (destination / 'source.sha256').write_text(digest + '\n')
    # Legacy internal-package lookup also considers the executable's SDK root.
    # Keep the seed beside the private sources so a CI bin/xu cannot shadow
    # them with the current repository's incompatible constant declarations.
    private_seed = destination / 'bin' / seed.name
    private_seed.parent.mkdir()
    shutil.copy2(seed, private_seed)
    private_seed.chmod(0o755)
    sources = sorted((destination / 'src/cmd/compile').glob('*.xu'))
    main_source = destination / 'src/cmd/compile/main.xu'
    sources.remove(main_source)
    profile = args.compiler_args
    if profile[:1] == ['--']:
        profile = profile[1:]
    env = dict(os.environ, XU_ROOT=destination.as_posix(), XU_STDLIB_ROOT=(destination / 'src').as_posix(), XUPATH='')
    subprocess.run([str(private_seed), 'build', *profile, str(main_source), *map(str, sources), '-o', str(output)],
                   cwd=destination, env=env, check=True)


if __name__ == '__main__':
    main()
