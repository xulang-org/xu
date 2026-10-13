"""Exercise platform verdicts using actual hosted builds and native execution."""
import os
import platform
import shutil
import subprocess
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(platform.system() != 'Darwin' or platform.machine() != 'arm64',
                              reason='native macOS arm64 execution contract')


def checkout(tmp_path):
    repo = tmp_path / 'repo'
    (repo / 'scripts').mkdir(parents=True)
    for name in ('platform_test.sh', 'run_product_compiler.sh', 'xu_host_seed.sh',
                 'docker_run_target.sh'):
        shutil.copy2(ROOT / 'scripts' / name, repo / 'scripts' / name)
    shutil.copytree(ROOT / 'tests/fixtures/hello_string', repo / 'tests/fixtures/hello_string')
    (repo / 'tests/lang').mkdir(parents=True)
    for name in ('test.ok.xu', 'test.ok.expected.txt'):
        shutil.copy2(ROOT / 'tests/lang' / name, repo / 'tests/lang' / name)
    return repo


@pytest.mark.parametrize('wrong_golden', [None, 'fixture', 'harness'])
def test_explicit_test_artifact_runs_and_bad_outputs_fail(tmp_path, wrong_golden):
    repo = checkout(tmp_path)
    if wrong_golden:
        target = repo / ('tests/fixtures/hello_string/expected.txt' if wrong_golden == 'fixture'
                         else 'tests/lang/test.ok.expected.txt')
        target.write_text('deliberately wrong independent expected output\n')
    compiler = Path(os.environ.get('XU_COMPILER', os.environ.get('XU', str(ROOT / 'bin/xu')))).resolve()
    result = subprocess.run([str(repo / 'scripts/platform_test.sh'), f'--xu={compiler}',
        '--lane=product', '--targets=macos-arm64', '--fixtures=hello_string'], cwd=repo,
        capture_output=True, text=True, timeout=120)
    verdicts = [line for line in result.stdout.splitlines() if line.startswith(('PASS ', 'FAIL '))]
    assert len(verdicts) == 2, result.stdout + result.stderr
    assert 'compile+file' not in '\n'.join(verdicts), 'this regression must execute both artifacts'
    assert result.returncode == int(wrong_golden is not None), result.stdout + result.stderr
    if wrong_golden:
        failed = 'hello_string' if wrong_golden == 'fixture' else 'test.ok'
        assert f'FAIL {failed}/macos-arm64 (stdout)' in verdicts
    else:
        assert verdicts == ['PASS hello_string/macos-arm64', 'PASS test.ok/macos-arm64']
