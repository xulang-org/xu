from pathlib import Path
import hashlib
import pytest
from scripts.verify_product_provenance import verify


def artifact(tmp_path):
    binary = tmp_path / 'xu'
    binary.write_bytes(b'candidate')
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    values = dict(status='PASS', lane='product', gen3_gen4_cmp='PASS',
                  gen3_sha256=digest, gen4_sha256=digest,
                  source_closure_sha256='closure')
    return binary, values


def save(binary, values):
    Path(str(binary) + '.provenance').write_text(''.join(f'{k}={v}\n' for k, v in values.items()))


def adaptive_artifact(tmp_path, generation):
    binary, values = artifact(tmp_path)
    digest = values['gen3_sha256']
    values.update(schema='2', confirmed_generation=str(generation), confirmed_sha256=digest,
                  fixed_point_cmp='PASS', gen2_sha256=digest,
                  fixed_point_pair='gen2_gen3' if generation == 3 else 'gen3_gen4',
                  gen2_gen3_cmp='PASS' if generation == 3 else 'DIFFERENT')
    if generation == 3:
        values.update(gen4_sha256='SKIPPED', gen4_size='SKIPPED', gen3_gen4_cmp='SKIPPED')
    else:
        values['gen2_sha256'] = hashlib.sha256(b'warmup').hexdigest()
    return binary, values


@pytest.mark.parametrize('generation', [3, 4])
def test_adaptive_confirmation_verifies_installed_generation(tmp_path, generation):
    binary, values = adaptive_artifact(tmp_path, generation)
    save(binary, values)
    result = verify(binary, 'closure')
    assert result['confirmed_generation'] == str(generation)
    assert result['confirmed_sha256'] == values['gen3_sha256']


@pytest.mark.parametrize('key,value', [
    ('confirmed_generation', '2'), ('fixed_point_pair', 'gen3_gen4'),
    ('confirmed_sha256', 'different'), ('fixed_point_cmp', 'DIFFERENT'),
    ('gen2_gen3_cmp', 'DIFFERENT'), ('gen2_sha256', 'different'),
    ('gen4_sha256', 'invented'), ('gen4_size', '123'), ('gen3_gen4_cmp', 'PASS'),
    ('schema', '3'),
])
def test_early_confirmation_rejects_inconsistent_evidence(tmp_path, key, value):
    binary, values = adaptive_artifact(tmp_path, 3)
    values[key] = value
    save(binary, values)
    with pytest.raises(ValueError, match=key):
        verify(binary, 'closure')


def test_artifact_source_and_stage_identity_are_independent(tmp_path):
    binary, values = artifact(tmp_path)
    save(binary, values)
    verify(binary, 'closure')
    with pytest.raises(ValueError, match='source_closure_sha256'):
        verify(binary, 'different-source')
    binary.write_bytes(b'replaced')
    with pytest.raises(ValueError, match='gen3_sha256'):
        verify(binary, 'closure')


@pytest.mark.parametrize('key,value', [
    ('status', 'FAIL'), ('lane', 'oracle'), ('gen3_gen4_cmp', 'DIFFERENT'),
    ('gen3_sha256', 'different'), ('gen4_sha256', 'different'),
])
def test_fixed_point_does_not_override_provenance_failure(tmp_path, key, value):
    binary, values = artifact(tmp_path)
    values[key] = value
    save(binary, values)
    with pytest.raises(ValueError, match=key):
        verify(binary, 'closure')


def test_missing_or_duplicate_sidecar_fails(tmp_path):
    binary, values = artifact(tmp_path)
    with pytest.raises(ValueError, match='missing'):
        verify(binary, 'closure')
    save(binary, values)
    sidecar = Path(str(binary) + '.provenance')
    sidecar.write_text(sidecar.read_text() + 'lane=product\n')
    with pytest.raises(ValueError, match='duplicate'):
        verify(binary, 'closure')


@pytest.mark.parametrize('generation', [3, 4])
def test_baseline_lock_records_the_actual_confirmed_generation(tmp_path, monkeypatch, capsys, generation):
    from scripts import lock_product_baseline
    directory = tmp_path / 'bin'
    directory.mkdir()
    binary, values = adaptive_artifact(directory, generation)
    product = directory / 'xu'
    binary.rename(product)
    save(product, values)
    (tmp_path / 'VERSION').write_text('0.1.0\n')
    manifest = tmp_path / 'src/cmd/compile/xu.xun'
    manifest.parent.mkdir(parents=True)
    manifest.write_text('module: xu\nversion: !ver 0.1.0\nxu: !ver 0.1.0\n')
    (tmp_path / 'docs/audit').mkdir(parents=True)
    monkeypatch.setattr(lock_product_baseline, 'ROOT', tmp_path)
    assert lock_product_baseline.main() == 0
    import json
    lock = json.loads((tmp_path / 'docs/audit/baseline.lock.json').read_text())
    assert lock['confirmed_generation'] == str(generation)
    assert lock['confirmed_sha256'] == values['confirmed_sha256']
    assert lock['gen4_sha256'] == ('SKIPPED' if generation == 3 else values['confirmed_sha256'])


@pytest.mark.parametrize('generation', [3, 4])
def test_release_identity_accepts_the_actual_confirmation(tmp_path, monkeypatch, capsys, generation):
    import sys
    from scripts import check_release_identity
    binary, values = adaptive_artifact(tmp_path, generation)
    save(binary, values)
    (tmp_path / 'VERSION').write_text('0.1.0\n')
    manifest = tmp_path / 'src/cmd/compile/xu.xun'
    manifest.parent.mkdir(parents=True)
    manifest.write_text('module: xu\nversion: !ver 0.1.0\nxu: !ver 0.1.0\n')
    monkeypatch.setattr(check_release_identity, 'ROOT', tmp_path)
    monkeypatch.setattr(check_release_identity, 'xu_cli_version', lambda _: '0.1.0')
    monkeypatch.setattr(sys, 'argv', ['check_release_identity.py', '--xu', str(binary), '--require-cli'])
    assert check_release_identity.main() == 0
    assert f'confirmed Gen{generation}' in capsys.readouterr().out


@pytest.mark.parametrize('field', ['version', 'xu'])
def test_release_identity_rejects_compiler_version_drift(tmp_path, monkeypatch, field):
    import sys
    from scripts import check_release_identity
    binary, values = adaptive_artifact(tmp_path, 3)
    save(binary, values)
    (tmp_path / 'VERSION').write_text('0.1.0\n')
    manifest = tmp_path / 'src/cmd/compile/xu.xun'
    manifest.parent.mkdir(parents=True)
    text = 'module: xu\nversion: !ver 0.1.0\nxu: !ver 0.1.0\n'
    manifest.write_text(text.replace(field + ': !ver 0.1.0', field + ': !ver 0.2.0'))
    monkeypatch.setattr(check_release_identity, 'ROOT', tmp_path)
    monkeypatch.setattr(check_release_identity, 'xu_cli_version', lambda _: '0.1.0')
    monkeypatch.setattr(sys, 'argv', ['check_release_identity.py', '--xu', str(binary), '--require-cli'])
    assert check_release_identity.main() == 1
