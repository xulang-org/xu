#!/usr/bin/env python3
"""Restore a hosted seed from a published or accepted CI SDK; never a primer."""
import argparse
import hashlib
import json
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


def download_accepted_sdk(run_id: str, target: str, archives: Path) -> None:
    """Use frozen SDK seeds only after their source and producer are accepted."""
    if not run_id.isdecimal() or int(run_id) <= 0:
        raise ValueError('SDK seed run must be a positive Actions run ID')
    def api(path):
        return json.loads(subprocess.check_output(
            ['gh', 'api', 'repos/xulang-org/xu/' + path], text=True, encoding='utf-8'))
    run = api('actions/runs/' + run_id)
    workflow = api('actions/workflows/sdk.yml')
    if run['workflow_id'] != workflow['id'] or run['status'] != 'completed':
        raise ValueError('SDK seed run must be a completed Installed SDK workflow')
    source = run['head_sha']
    if len(source) != 40 or any(c not in '0123456789abcdef' for c in source):
        raise ValueError('Invalid SDK seed source revision')
    if api('compare/' + source + '...main')['status'] not in ('ahead', 'identical'):
        raise ValueError('SDK seed source has not been accepted into main')
    jobs = api('actions/runs/' + run_id + '/jobs?per_page=100')['jobs']
    if not any(j['name'] == 'Native macOS Intel SDK and platform seeds'
               and j['conclusion'] == 'success' for j in jobs):
        raise ValueError('SDK seed producer did not pass its native acceptance')
    if target != 'macos-x64' and not any(
            j['name'] == f'Install and run ({target}, product)' and j['conclusion'] == 'success'
            for j in jobs):
        raise ValueError('SDK seed target did not pass native installation acceptance')
    artifacts = api('actions/runs/' + run_id + '/artifacts?per_page=100')['artifacts']
    name = 'xu-sdk-product-' + target
    matches = [a for a in artifacts if a['name'] == name and not a['expired']]
    if len(matches) != 1:
        raise ValueError('Expected one unexpired verified SDK seed artifact')
    archives.mkdir(parents=True, exist_ok=True)
    subprocess.run(['gh', 'run', 'download', run_id, '--repo', 'xulang-org/xu',
                    '--name', name, '--dir', str(archives)], check=True)
    print(f'Accepted SDK seed: run={run_id} source={source} artifact={matches[0]["id"]}')


def restore(target: str, archives: Path, destination: Path, *, replace_existing: bool = False) -> None:
    if destination.exists() and not replace_existing:
        raise ValueError('Refusing to overwrite an existing hosted seed')
    with tempfile.TemporaryDirectory(prefix='xu-product-seed-') as temporary:
        compiler = extract_seed(archives, target, Path(temporary) / 'sdk')
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Preserve the matching published sources for one-time language
        # migrations. The binary digest prevents reusing another SDK's tree.
        sdk_root = compiler.parent.parent
        if (sdk_root / 'src/cmd/compile/main.xu').is_file() and (sdk_root / 'VERSION').is_file():
            digest = hashlib.sha256(compiler.read_bytes()).hexdigest()
            source_cache = destination.parent / '.xu-seed-sources' / digest
            if not source_cache.exists():
                source_cache.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix='.seed-source-', dir=source_cache.parent) as source_stage:
                    staged_source = Path(source_stage) / 'sdk'
                    shutil.copytree(sdk_root / 'src', staged_source / 'src')
                    shutil.copy2(sdk_root / 'VERSION', staged_source / 'VERSION')
                    os.rename(staged_source, source_cache)
        # Complete SDK identity verification and copying before replacing a
        # partially restored cache. A failed download/extraction/install keeps
        # the previous bytes, and Mach-O installation receives a fresh inode.
        fd, staged_name = tempfile.mkstemp(prefix='.xu-product-seed-', dir=destination.parent)
        os.close(fd)
        staged = Path(staged_name)
        try:
            shutil.copy2(compiler, staged)
            staged.chmod(0o755)
            os.replace(staged, destination)
            # The replaced binary's fixed-point identity cannot describe the
            # restored SDK seed. A fresh chain will write new provenance.
            Path(str(destination) + '.provenance').unlink(missing_ok=True)
        finally:
            staged.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=SUPPORTED_TARGETS, required=True)
    parser.add_argument('--version', default=os.environ.get('XU_SDK_SEED_VERSION', ''))
    parser.add_argument('--artifact-run-id', default='',
                        help='accepted SDK seed run to use when no published version is explicitly selected')
    parser.add_argument('--archives', type=Path)
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--replace-existing', action='store_true',
                        help='atomically replace a cached seed after validating the downloaded SDK')
    args = parser.parse_args()
    if not args.archives and not args.destination:
        parser.error('Provide --archives or --destination')
    try:
        with tempfile.TemporaryDirectory(prefix='xu-product-download-') as temporary:
            archives = args.archives or Path(temporary)
            if args.artifact_run_id and not args.version:
                download_accepted_sdk(args.artifact_run_id, args.target, archives)
            else:
                download(args.target, args.version, archives)
            if args.destination:
                restore(args.target, archives, args.destination, replace_existing=args.replace_existing)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print('Product seed BLOCKED: no verified hosted SDK seed. Publish the initial verified SDK '
              'or configure a successful artifact run; oracle binaries are not product seeds.', file=sys.stderr)
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
