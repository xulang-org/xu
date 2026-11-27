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

if __package__:
    from .pack_release_bundle import SUPPORTED_TARGETS
    from .release_version import Version
    from .sdk_seed import extract_seed
else:
    from pack_release_bundle import SUPPORTED_TARGETS
    from release_version import Version
    from sdk_seed import extract_seed

REPO = 'xulang-org/xu'


def list_published_releases() -> list[tuple[Version, str]]:
    output = subprocess.check_output(
        [
            'gh', 'api', '--paginate', f'repos/{REPO}/releases?per_page=100',
            '--jq', '.[] | {tag_name, draft, prerelease}',
        ],
        text=True,
        encoding='utf-8',
    )
    releases: list[tuple[Version, str]] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get('draft') or row.get('prerelease'):
            continue
        tag = (row.get('tag_name') or '').strip()
        if not tag:
            continue
        try:
            ver = Version.parse(tag.removeprefix('v'))
        except ValueError:
            continue
        releases.append((ver, tag))
    releases.sort(key=lambda item: item[0], reverse=True)
    return releases


def resolve_seed_tag(
    version: str,
    before_version: str = '',
    *,
    releases: list[tuple[Version, str]] | None = None,
) -> str:
    if version:
        return 'v' + version.removeprefix('v')

    published = sorted(
        releases if releases is not None else list_published_releases(),
        key=lambda item: item[0],
        reverse=True,
    )

    if before_version:
        limit = Version.parse(before_version.removeprefix('v'))
        for ver, tag in published:
            if ver < limit:
                return tag
        raise ValueError(f'No published release found prior to {limit}')

    if published:
        return published[0][1]

    if releases is not None:
        raise ValueError('No published releases available')

    return subprocess.check_output(
        ['gh', 'release', 'view', '--repo', REPO, '--json', 'tagName', '--jq', '.tagName'],
        text=True,
        encoding='utf-8',
    ).strip()


def download(target: str, version: str, archives: Path, before_version: str = '') -> None:
    archives.mkdir(parents=True, exist_ok=True)
    tag = resolve_seed_tag(version, before_version)
    extension = 'zip' if target.startswith('windows-') else 'tar.gz'
    subprocess.run(
        ['gh', 'release', 'download', tag, '--repo', REPO,
         '--pattern', f'xu-{tag}-{target}.{extension}', '--dir', str(archives)],
        check=True,
    )


def download_accepted_sdk(run_id: str, target: str, archives: Path) -> None:
    """Use frozen SDK seeds only after their source and producer are accepted."""
    if not run_id.isdecimal() or int(run_id) <= 0:
        raise ValueError('SDK seed run must be a positive Actions run ID')

    def api(path: str):
        return json.loads(subprocess.check_output(
            ['gh', 'api', f'repos/{REPO}/' + path], text=True, encoding='utf-8'))

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
    subprocess.run(
        ['gh', 'run', 'download', run_id, '--repo', REPO, '--name', name, '--dir', str(archives)],
        check=True,
    )
    print(f'Accepted SDK seed: run={run_id} source={source} artifact={matches[0]["id"]}')


def restore(target: str, archives: Path, destination: Path, *, replace_existing: bool = False) -> None:
    if destination.exists() and not replace_existing:
        raise ValueError('Refusing to overwrite an existing hosted seed')
    with tempfile.TemporaryDirectory(prefix='xu-product-seed-', ignore_cleanup_errors=True) as temporary:
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
                with tempfile.TemporaryDirectory(
                    prefix='.seed-source-', dir=source_cache.parent, ignore_cleanup_errors=True
                ) as source_stage:
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
            print('Restored hosted seed: target=' + target + ' sha256='
                  + hashlib.sha256(destination.read_bytes()).hexdigest(), flush=True)
            # The replaced binary's fixed-point identity cannot describe the
            # restored SDK seed. A fresh chain will write new provenance.
            Path(str(destination) + '.provenance').unlink(missing_ok=True)
        finally:
            staged.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=SUPPORTED_TARGETS)
    parser.add_argument('--version', default=os.environ.get('XU_SDK_SEED_VERSION', ''))
    parser.add_argument('--before-version', default=os.environ.get('XU_SDK_SEED_BEFORE_VERSION', ''),
                        help='select the highest published release strictly older than this version')
    parser.add_argument('--print-seed-version', action='store_true',
                        help='print the resolved seed version (without leading v) and exit')
    parser.add_argument('--artifact-run-id', default='',
                        help='accepted SDK seed run to use when no published version is explicitly selected')
    parser.add_argument('--archives', type=Path)
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--replace-existing', action='store_true',
                        help='atomically replace a cached seed after validating the downloaded SDK')
    args = parser.parse_args()
    if args.print_seed_version:
        print(resolve_seed_tag(args.version, args.before_version).removeprefix('v'))
        return 0
    if not args.target:
        parser.error('--target is required unless --print-seed-version is set')
    if not args.archives and not args.destination:
        parser.error('Provide --archives or --destination')
    try:
        with tempfile.TemporaryDirectory(prefix='xu-product-download-', ignore_cleanup_errors=True) as temporary:
            archives = args.archives or Path(temporary)
            if args.artifact_run_id and not args.version:
                download_accepted_sdk(args.artifact_run_id, args.target, archives)
            else:
                download(args.target, args.version, archives, args.before_version)
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
