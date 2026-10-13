"""Product dependency modes: no tools, no trust-on-first-use, portable vendor."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get("XU", ROOT / "bin/xu"))


@pytest.fixture
def project(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    calls = tmp_path / "calls.jsonl"
    tools = tmp_path / "tools"
    tools.mkdir()
    stub = '''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
with open(os.environ['XU_DEP_LOG'],'a') as f: f.write(json.dumps(sys.argv)+'\\n')
if Path(sys.argv[0]).name=='curl':
 Path(sys.argv[sys.argv.index('-o')+1]).write_text('@rempkg\\npub fn answer() int { << 42 }\\n')
else: sys.exit(92)
'''
    for name in ("curl", "git"):
        tool = tools / name
        tool.write_text(stub)
        tool.chmod(0o755)
    env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ["PATH"],
               XUPATH="", XU_CACHE=str(tmp_path / "cache"), XU_DEP_LOG=str(calls))
    for k in ("XUOS", "XUARCH", "XU_HEAP_STATS", "XU_OFFLINE", "XU_FROZEN"):
        env.pop(k, None)
    env['XU_STDLIB_ROOT'] = str(ROOT / 'src')

    def declare(locator="https://invalid.example/rempkg.xu", key="rempkg"):
        (app / "xu.xun").write_text(f'module: app\nversion: !ver 0.1.0\nrequire:\n  "{key}": {locator}\n')
        (app / "main.xu").write_text(f'@main\nlib #"{key}"\nfn main() int {{ println(lib.answer())\n << 0 }}\n')

    def invoke(command="build", flags=(), extra=()):
        args = [str(XU), command, *flags]
        if command == "install":
            args += [str(app), *extra]
        elif command == "check":
            args += [str(app / "main.xu"), *extra]
        else:
            source = app / 'test.answer.xu' if command == 'test' else app / 'main.xu'
            args += [str(source), "-o", str(app / "program"), *extra]
        return subprocess.run(args, cwd=app, env=env, capture_output=True, text=True, timeout=90)

    declare()
    return tmp_path, app, calls, env, declare, invoke


def ok(r):
    assert r.returncode == 0, r.stdout + r.stderr


def reject(r, needle):
    assert r.returncode != 0, 'dependency policy was ignored'
    assert needle in r.stderr, r.stderr


@pytest.mark.parametrize('locator', ['https://invalid.example/rempkg.xu', 'git:https://invalid.example/rempkg@v1.0.0'])
@pytest.mark.parametrize('command', ['build', 'check', 'install'])
def test_offline_miss_never_invokes_download_or_writes(project, locator, command):
    root, app, calls, _, declare, invoke = project
    declare(locator)
    reject(invoke(command, ['--offline']), 'offline')
    assert not calls.exists()
    assert not (app / 'xu.lock').exists()
    assert not (root / 'cache').exists()
    assert not (app / 'vendor').exists()


def test_frozen_missing_lock_rejects_warm_cache_without_changes(project):
    root, app, calls, _, _, invoke = project
    ok(invoke())
    count = calls.read_bytes()
    (app / 'xu.lock').unlink()
    before = {str(p):p.read_bytes() for p in (root / 'cache').rglob('*') if p.is_file()}
    reject(invoke(flags=['--frozen']), 'existing xu.lock')
    assert not (app / 'xu.lock').exists()
    assert calls.read_bytes() == count
    assert before == {str(p):p.read_bytes() for p in (root / 'cache').rglob('*') if p.is_file()}


def test_frozen_warm_cache_is_read_only(project):
    root, app, calls, _, _, invoke = project
    ok(invoke())
    lock = (app / 'xu.lock').read_bytes()
    cache = {str(p):p.read_bytes() for p in (root / 'cache').rglob('*') if p.is_file()}
    count = calls.read_bytes()
    ok(invoke(flags=['--frozen']))
    ok(invoke('check', ['--frozen']))
    assert (app / 'xu.lock').read_bytes() == lock
    assert cache == {str(p):p.read_bytes() for p in (root / 'cache').rglob('*') if p.is_file()}
    assert calls.read_bytes() == count


def test_offline_cache_can_prepare_vendor_then_frozen_needs_no_cache(project):
    root, app, calls, _, _, invoke = project
    ok(invoke())
    count = calls.read_bytes()
    ok(invoke('install', ['--offline']))
    shutil.rmtree(root / 'cache')
    lock = (app / 'xu.lock').read_bytes()
    ok(invoke(flags=['--frozen']))
    assert subprocess.check_output([str(app / 'program')], text=True) == '42\n'
    assert (app / 'xu.lock').read_bytes() == lock
    assert calls.read_bytes() == count
    assert not (root / 'cache').exists()


@pytest.mark.parametrize('canonical', [False, True])
def test_local_snapshot_is_portable_and_authenticated(project, canonical):
    root, app, calls, env, declare, invoke = project
    provider = root / 'provider'
    provider.mkdir()
    key = 'example.com/lib' if canonical else 'rempkg'
    (provider / 'mod.xu').write_text(f'@"{key}"\npub fn answer() int {{ << 42 }}\n')
    (provider / 'xu.xun').write_text(f'module: "{key}"\nversion: !ver 1.2.0\n')
    declare('file:../provider', key)
    ok(invoke('install', ['--offline']))
    shutil.rmtree(provider)
    lock = (app / 'xu.lock').read_bytes()
    ok(invoke(flags=['--frozen']))
    assert subprocess.check_output([str(app / 'program')], text=True) == '42\n'
    copy = root / 'relocated'
    shutil.copytree(app, copy)
    r = subprocess.run([str(XU), 'build', '--frozen', str(copy / 'main.xu'), '-o', str(copy / 'program')],
                       cwd=copy, env=env, capture_output=True, text=True, timeout=90)
    ok(r)
    source = app / 'vendor' / key / 'mod.xu'
    source.write_text(source.read_text().replace('42', '99'))
    reject(invoke(flags=['--frozen']), 'checksum')
    assert (app / 'xu.lock').read_bytes() == lock
    assert not calls.exists()


def test_local_development_is_allowed_offline_but_requires_snapshot_when_frozen(project):
    root, app, calls, _, declare, invoke = project
    provider = root / 'provider'
    provider.mkdir()
    (provider / 'rempkg.xu').write_text('@rempkg\npub fn answer() int { << 42 }\n')
    declare('file:../provider')
    ok(invoke(flags=['--offline']))
    reject(invoke(flags=['--frozen']), 'xu.lock')
    ok(invoke('install'))
    shutil.rmtree(app / 'vendor')
    reject(invoke(flags=['--frozen']), 'vendor snapshot')
    assert not calls.exists()


def test_frozen_preflights_unused_declared_dependencies(project):
    _, app, calls, _, _, invoke = project
    ok(invoke())
    count = calls.read_bytes()
    manifest = app / 'xu.xun'
    manifest.write_text(manifest.read_text() + '  unused: https://invalid.example/unused.xu\n')
    lock = (app / 'xu.lock').read_bytes()
    reject(invoke(flags=['--frozen']), 'existing xu.lock')
    assert (app / 'xu.lock').read_bytes() == lock
    assert calls.read_bytes() == count


def test_frozen_install_never_mutates_dependencies(project):
    _, app, calls, _, _, invoke = project
    reject(invoke('install', ['--frozen']), 'forbids dependency writes')
    assert not calls.exists()
    assert not (app / 'xu.lock').exists()
    assert not (app / 'vendor').exists()


def test_program_arguments_and_output_names_are_not_dependency_options(project):
    _, app, calls, env, _, _ = project
    r = subprocess.run([str(XU), 'run', str(app / 'main.xu'), '--', '--frozen'],
                       cwd=app, env=env, capture_output=True, text=True, timeout=90)
    ok(r)
    assert r.stdout == '42\n'
    assert calls.exists()
    (app / 'xu.lock').unlink()
    r = subprocess.run([str(XU), 'build', str(app / 'main.xu'), '-o', '--frozen'],
                       cwd=app, env=env, capture_output=True, text=True, timeout=90)
    ok(r)
    assert (app / '--frozen').exists()
    assert (app / 'xu.lock').exists()


def test_install_rejects_overlapping_local_source_before_copy(project):
    _, app, calls, _, declare, invoke = project
    declare('file:.')
    reject(invoke('install'), 'overlaps the vendor')
    assert not calls.exists()
    assert not (app / 'vendor').exists()
    assert not (app / 'xu.lock').exists()


def test_help_documents_dependency_modes(project):
    _, app, _, env, _, _ = project
    r = subprocess.run([str(XU), '--help'], cwd=app, env=env, capture_output=True, text=True)
    ok(r)
    assert '--frozen' in r.stdout and '--offline' in r.stdout


def test_frozen_local_native_manifest_cannot_escape_snapshot(project):
    root, app, calls, _, declare, invoke = project
    provider = root / 'provider'
    provider.mkdir()
    outside = root / 'outside.a'
    outside.write_bytes(b'not an archive')
    (provider / 'mod.xu').write_text('@"example.com/lib"\npub fn answer() int { << 42 }\n')
    (provider / 'xu.xun').write_text('module: "example.com/lib"\nversion: !ver 1.0.0\nnative:\n  helper: file:' + str(outside) + '\n')
    declare('file:../provider', 'example.com/lib')
    ok(invoke('install'))
    reject(invoke(flags=['--frozen']), 'outside authenticated dependency content')
    assert not calls.exists()


def test_frozen_run_and_test_share_build_policy(project):
    _, app, calls, _, _, invoke = project
    ok(invoke('install'))
    count = calls.read_bytes()
    lock = (app / 'xu.lock').read_bytes()
    ok(invoke('run', ['--frozen']))
    (app / 'test.answer.xu').write_text('@main\n#rempkg\nfn test_answer() { assert(rempkg.answer() == 42) }\n')
    ok(invoke('test', ['--frozen']))
    assert (app / 'xu.lock').read_bytes() == lock
    assert calls.read_bytes() == count


def test_frozen_does_not_silently_delegate_to_desktop_packer(project):
    _, _, calls, _, _, invoke = project
    reject(invoke(flags=['--frozen', '--desktop']), 'does not support')
    assert not calls.exists()


def test_frozen_rejects_intermediate_vendor_link_even_when_content_matches(project):
    root,app,_,_,declare,invoke=project
    provider=root/'provider';provider.mkdir()
    (provider/'mod.xu').write_text('@"example.com/lib"\npub fn answer() int { << 42 }\n')
    (provider/'xu.xun').write_text('module: "example.com/lib"\nversion: !ver 1.0.0\n')
    declare('file:../provider','example.com/lib')
    ok(invoke('install'))
    lock=(app/'xu.lock').read_bytes()
    domain=app/'vendor/example.com'
    outside=root/'outside';shutil.move(domain,outside)
    domain.symlink_to(outside,target_is_directory=True)
    reject(invoke(flags=['--frozen']),'symlink')
    assert (app/'xu.lock').read_bytes()==lock
    assert (outside/'lib/mod.xu').is_file()
