#!/usr/bin/env python3
"""Validate a hosted artifact against its sidecar and current source closure."""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path


def read_provenance(binary: Path) -> dict[str, str]:
    sidecar = Path(str(binary) + '.provenance')
    if not binary.is_file() or not sidecar.is_file():
        raise ValueError('binary/provenance missing')
    values = {}
    for line in sidecar.read_text().splitlines():
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        if key in values:
            raise ValueError('duplicate provenance field: ' + key)
        values[key] = value
    return values


def fixed_point_identity(values: dict[str, str], digest: str) -> dict[str, str]:
    schema = values.get('schema', '1')
    if schema == '1':
        generation, pair, stages = '4', 'gen3_gen4', (3, 4)
    elif schema == '2':
        generation = values.get('confirmed_generation')
        if generation == '3':
            pair, stages = 'gen2_gen3', (2, 3)
        elif generation == '4':
            pair, stages = 'gen3_gen4', (3, 4)
        else:
            raise ValueError('provenance confirmed_generation must be 3 or 4')
        for key, expected in {
            'fixed_point_cmp': 'PASS', 'fixed_point_pair': pair,
            'confirmed_sha256': digest,
        }.items():
            if values.get(key) != expected:
                raise ValueError(f'provenance {key} mismatch: {values.get(key)!r} != {expected!r}')
        if generation == '3':
            for key in ('gen4_sha256', 'gen4_size', 'gen3_gen4_cmp'):
                if values.get(key) != 'SKIPPED':
                    raise ValueError(f'provenance {key} must be SKIPPED for Gen3 confirmation')
        elif (values.get('gen2_gen3_cmp') != 'DIFFERENT'
              or values.get('gen2_sha256') == values.get('gen3_sha256')):
            raise ValueError('provenance gen2_gen3_cmp must record the warmup transition')
    else:
        raise ValueError(f'unsupported provenance schema: {schema}')

    expected = {pair + '_cmp': 'PASS'}
    expected.update({f'gen{stage}_sha256': digest for stage in stages})
    for key, value in expected.items():
        if values.get(key) != value:
            raise ValueError(f'provenance {key} mismatch: {values.get(key)!r} != {value!r}')
    return dict(confirmed_generation=generation, confirmed_sha256=digest,
                fixed_point_pair=pair, fixed_point_cmp='PASS')


def verify(binary: Path, closure_sha256: str, lane: str = 'product') -> dict[str, str]:
    values = read_provenance(binary)
    for key, expected in {
        'status': 'PASS', 'lane': lane,
        'source_closure_sha256': closure_sha256,
    }.items():
        if values.get(key) != expected:
            raise ValueError(f'provenance {key} mismatch: {values.get(key)!r} != {expected!r}')
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    return values | fixed_point_identity(values, digest)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('binary', type=Path)
    ap.add_argument('--source-closure-sha256', required=True)
    ap.add_argument('--lane', choices=('product', 'oracle'), default='product')
    args = ap.parse_args()
    try:
        verify(args.binary, args.source_closure_sha256, args.lane)
    except (ValueError, OSError) as exc:
        ap.exit(1, f'verify_product_provenance: {exc}\n')
    print('verify_product_provenance: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
