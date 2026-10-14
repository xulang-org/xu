#!/usr/bin/env python3
"""Restore a hosted seed from a published SDK; never substitute a primer."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from pack_release_bundle import SUPPORTED_TARGETS
from sdk_seed import extract_seed


def resolve_seed_tag(version: str) -> str:
    if version:
        return 'v' + version.removeprefix('v')

    repo_root = Path(__file__).resolve().parent.parent
    version_file = repo_root / 'VERSION'
    local_tag = ''
    if version_file.exists():
        v_text = version_file.read_text(encoding='utf-8').strip()
        if v_text:
            local_tag = 'v' + v_text.removeprefix('v')

    try:
        output = subprocess.check_output(
            ['gh', 'release', 'list', '--repo', 'xulang-org/xu', '--limit', '10', '--json', 'tagName', '--jq', '.[].tagName'],
            text=True
        ).strip().splitlines()
        tags = [t.strip() for t in output if t.strip()]
        if local_tag and local_tag in tags:
            return local_tag
        if tags:
            return tags[0]
    except Exception:
        pass

    return subprocess.check_output(
        ['gh', 'release', 'view', '--repo', 'xulang-org/xu', '--json', 'tagName', '--jq', '.tagName'],
        text=True).strip()


def download(target: str, version: str, archives: Path) -> None:
    archives.mkdir(parents=True, exist_ok=True)
    tag = resolve_seed_tag(version)
    extension = 'zip' if target.startswith('windows-') else 'tar.gz'
    subprocess.run(['gh', 'release', 'download', tag, '--repo', 'xulang-org/xu',
                    '--pattern', f'xu-{tag}-{target}.{extension}', '--dir', str(archives)], check=True)


def restore(target: str, archives: Path, destination: Path) -> None:
    if destination.exists():
        raise ValueError('Refusing to overwrite an existing hosted seed')
    with tempfile.TemporaryDirectory(prefix='xu-product-seed-') as temporary:
        compiler = extract_seed(archives, target, Path(temporary) / 'sdk')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(compiler, destination)
        destination.chmod(0o755)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=SUPPORTED_TARGETS, required=True)
    parser.add_argument('--version', default=os.environ.get('XU_SDK_SEED_VERSION', ''))
    parser.add_argument('--archives', type=Path)
    parser.add_argument('--destination', type=Path)
    args = parser.parse_args()
    if not args.archives and not args.destination:
        parser.error('Provide --archives or --destination')
    try:
        with tempfile.TemporaryDirectory(prefix='xu-product-download-') as temporary:
            archives = args.archives or Path(temporary)
            download(args.target, args.version, archives)
            if args.destination:
                restore(args.target, archives, args.destination)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print('Product seed BLOCKED: no valid published SDK seed. Publish the initial verified SDK '
              'or configure a successful artifact run; oracle binaries are not product seeds.', file=sys.stderr)
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
