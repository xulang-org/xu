"""Exercise the build-only chain with a real temporary shell checkout."""
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.verify_product_provenance import verify

ROOT = Path(__file__).resolve().parents[1]


def repository(tmp_path):
    repo = tmp_path / 'repo'
    scripts = repo / 'scripts'
    scripts.mkdir(parents=True)
    for name in ('build_hosted_chain.sh', 'xu_host_seed.sh', 'install_product_executable.sh',
                 'check_module_paths.py', 'stage_seed_syntax.py'):
        shutil.copy2(ROOT / 'scripts' / name, scripts / name)
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    (scripts / 'gen1_sources.sh').write_text('GEN1_SRCS=source.xu\n')
    (repo / 'source.xu').write_text('source')
    (scripts / 'check_bootstrap_xu_boundary.py').write_text('''import hashlib,json
from pathlib import Path
print(json.dumps(dict(source_manifest=dict(complete=True,seed_sha256="seed",closure_sha256=hashlib.sha256(Path("source.xu").read_bytes()).hexdigest(),seed_files=1,closure_files=1),repo_head="head")))
''')
    # Fail loudly if candidate mode reaches any installation helper.
    for name in ('build_product_tools.sh', 'build_platform_xu.sh'):
        p = scripts / name
        p.write_text('#!/bin/sh\ntouch install-was-called\nexit 99\n')
        p.chmod(0o755)
    seed = repo / 'seed'
    seed.write_text('''#!/bin/sh
for arg do
    if [ "$last" = -o ]; then
        basename "$arg" >> hops.log
        cp "$0" "$arg"
        chmod +x "$arg"
    fi
    last=$arg
done
''')
    seed.chmod(0o755)
    (repo / 'bin').mkdir()
    (repo / 'bin' / 'xu').write_bytes(b'existing product')
    return repo, seed


def run(repo, seed, dest, *, candidate=True):
    flags = ['--candidate-only'] if candidate else []
    return subprocess.run([str(repo / 'scripts/build_hosted_chain.sh'), *flags, str(seed), str(dest)],
                          cwd=repo, capture_output=True, text=True, env={**os.environ, 'HOSTED_PROFILE': 'product'})


def test_candidate_chain_preserves_product_and_writes_identity(tmp_path):
    repo, seed = repository(tmp_path)
    dest = repo / 'candidates' / 'xu'
    result = run(repo, seed, dest)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (repo / 'bin' / 'xu').read_bytes() == b'existing product'
    assert not (repo / 'install-was-called').exists()
    assert dest.read_bytes() == seed.read_bytes()
    sidecar = Path(str(dest)+'.provenance').read_text()
    assert 'candidate_only=1' in sidecar and 'gen3_gen4_cmp=SKIPPED' in sidecar
    assert 'confirmed_generation=3' in sidecar and 'fixed_point_pair=gen2_gen3' in sidecar
    assert 'gen4_sha256=SKIPPED' in sidecar
    assert 'cross_targets=SKIPPED' in sidecar
    assert (repo / 'hops.log').read_text().splitlines() == ['gen1.xin', 'gen2.xin', 'gen3.xin']
    verify(dest, hashlib.sha256(b'source').hexdigest())


def change_seed(seed, *, warmup=False, unstable=False, fail_stage=None):
    source = seed.read_text()
    code = ''
    if fail_stage:
        code += f'[ "$(basename "$0")" = {fail_stage}.xin ] && exit 87\n'
    code += 'cp "$0" "$arg"\n'
    if unstable:
        code += 'printf "\\n# new generation\\n" >> "$arg"\n'
    elif warmup:
        code += '[ "$(basename "$0")" = gen2.xin ] && printf "\\n# warmup completed\\n" >> "$arg"\n'
    seed.write_text(source.replace('cp "$0" "$arg"', code))


def test_changed_gen2_requires_and_installs_matching_gen4(tmp_path):
    repo, seed = repository(tmp_path)
    change_seed(seed, warmup=True)
    dest = repo / 'candidates/xu'
    result = run(repo, seed, dest)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (repo / 'hops.log').read_text().splitlines() == ['gen1.xin', 'gen2.xin', 'gen3.xin', 'gen4.xin']
    sidecar = Path(str(dest) + '.provenance').read_text()
    assert 'confirmed_generation=4' in sidecar and 'fixed_point_pair=gen3_gen4' in sidecar
    assert 'gen2_gen3_cmp=DIFFERENT' in sidecar and 'gen3_gen4_cmp=PASS' in sidecar
    assert b'# warmup completed' in dest.read_bytes()
    verify(dest, hashlib.sha256(b'source').hexdigest())


@pytest.mark.parametrize('warmup', [False, True])
def test_product_install_uses_the_confirmed_generation(tmp_path, warmup):
    repo, seed = repository(tmp_path)
    change_seed(seed, warmup=warmup)
    for name in ('build_product_tools.sh', 'build_platform_xu.sh'):
        (repo / 'scripts' / name).write_text(f'#!/bin/sh\necho {name} >> installed-helpers.log\n')
    dest = repo / 'bin/xu'
    result = run(repo, seed, dest, candidate=False)
    assert result.returncode == 0, result.stdout + result.stderr
    identity = verify(dest, hashlib.sha256(b'source').hexdigest())
    assert identity['confirmed_generation'] == ('4' if warmup else '3')
    assert (repo / 'bin/xu.bak').read_bytes() == b'existing product'
    assert (repo / 'installed-helpers.log').read_text().splitlines() == ['build_product_tools.sh', 'build_platform_xu.sh']
    assert len((repo / 'hops.log').read_text().splitlines()) == (4 if warmup else 3)


def test_early_confirmation_still_rejects_source_drift(tmp_path):
    repo, seed = repository(tmp_path)
    seed.write_text(seed.read_text().replace('cp "$0" "$arg"',
        'cp "$0" "$arg"\n[ "$(basename "$arg")" = gen3.xin ] && echo drift >> source.xu\n'))
    dest = repo / 'candidates/xu'
    result = run(repo, seed, dest)
    assert result.returncode != 0
    assert 'stage=source_identity' in result.stderr
    assert 'source changed during chain' in result.stderr
    assert not dest.exists()


@pytest.mark.parametrize('failure,stage', [('unstable', 'fixed_point_cmp'), ('gen2', 'gen2_to_gen3'), ('gen3', 'gen3_to_gen4')])
def test_confirmation_failure_preserves_destination(tmp_path, failure, stage):
    repo, seed = repository(tmp_path)
    change_seed(seed, warmup=True, unstable=failure == 'unstable',
                fail_stage=None if failure == 'unstable' else failure)
    dest = repo / 'candidates/xu'
    dest.parent.mkdir()
    dest.write_bytes(b'previous candidate')
    result = run(repo, seed, dest)
    assert result.returncode != 0
    assert f'stage={stage}' in result.stderr
    assert dest.read_bytes() == b'previous candidate'
    assert not Path(str(dest) + '.provenance').exists()
    assert not (repo / 'install-was-called').exists()


def test_candidate_mode_rejects_product_destination(tmp_path):
    repo, seed = repository(tmp_path)
    result = run(repo, seed, repo / 'bin' / 'xu')
    assert result.returncode != 0
    assert 'outside product directories' in result.stderr
    assert (repo / 'bin' / 'xu').read_bytes() == b'existing product'


def test_recovery_lineage_survives_hosted_descendant(tmp_path):
    repo, seed = repository(tmp_path)
    Path(str(seed)+'.provenance').write_text('lane=oracle\n')
    dest = repo / 'candidates' / 'xu'
    result = run(repo, seed, dest)
    assert result.returncode == 0, result.stdout+result.stderr
    assert 'lane=oracle' in Path(str(dest)+'.provenance').read_text()
    assert not (repo / 'install-was-called').exists()


def test_legacy_seed_reads_staged_manifest_only_on_first_hop(tmp_path):
    repo, seed = repository(tmp_path)
    compiler = repo / 'src/cmd/compile'
    compiler.mkdir(parents=True)
    (compiler / 'main.xu').write_text('compiler source')
    (compiler / 'xu.xun').write_text('module: xu\nversion: !ver 0.1.1\nxu: !ver 0.1.0\n')
    (repo / 'scripts/gen1_sources.sh').write_text('GEN1_SRCS=src/cmd/compile/main.xu\n')
    seed.write_text('''#!/bin/sh
for arg do
    case "$arg" in
        *.xu)
            manifest="$(dirname "$arg")/xu.xun"
            if [ "$(basename "$0")" = seed ]; then
                grep -q '^version:' "$manifest" && exit 88
                grep -q '^module: xu$' "$manifest" || exit 89
                [ "$(cat "$arg")" = "compiler source" ] || exit 90
            else
                grep -q '^version: !ver 0.1.1$' "$manifest" || exit 91
            fi
            ;;
    esac
    if [ "$last" = -o ]; then
        cp "$0" "$arg"
        chmod +x "$arg"
    fi
    last=$arg
done
''')
    result = run(repo, seed, repo / 'candidates/xu')
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'version: !ver 0.1.1' in (compiler / 'xu.xun').read_text()
