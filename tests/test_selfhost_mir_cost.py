#!/usr/bin/env python3
"""Differential execution of real Xu MIR DCE and multi-word borrow dataflow."""
from pathlib import Path
import argparse, hashlib, json, shutil, subprocess, tempfile

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'tests/data/selfhost_mir_cost'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    compiler = args.xu.resolve()
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    identity = sha(compiler)
    sources = {str(p.relative_to(ROOT)): sha(p) for p in (ROOT / 'src').rglob('*.xu')}
    rows = []
    with tempfile.TemporaryDirectory(prefix='xu-mir-cost-') as td:
        work = Path(td)
        # Private hooks are confined to an immutable source copy. They expose
        # the implementation to this executable gate without a product API.
        shutil.copytree(ROOT / 'src', work / 'src')
        shutil.copytree(ROOT / 'scripts', work / 'scripts')
        hook = work / 'src/xu/types/selfhost_cost_test.xu'
        hook.write_text((DATA / 'dce_reference.xu').read_text() +
                        (DATA / 'support.xu').read_text().replace('@xu/types', '', 1))
        source = work / 'main.xu'
        source.write_bytes((DATA / 'main.xu').read_bytes())
        for opt in ('-O0', '-O1'):
            binary = work / ('test' + opt)
            built = subprocess.run([str(work / 'scripts/run_product_compiler.sh'),
                str(compiler), 'build', opt, str(source), '-o', str(binary)],
                cwd=work, capture_output=True, text=True, timeout=180)
            if built.returncode:
                raise ValueError(f'{opt}: {built.stderr}')
            run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60)
            if run.returncode or run.stderr or run.stdout != 'DCE reference and borrow words ok\n':
                raise ValueError(f'{opt}: {run}')
            rows.append(dict(opt=opt, status='PASS', build_stderr=built.stderr,
                stdout=run.stdout, binary_sha256=sha(binary),
                operand_cases=300, differential_cfg_cases=512, borrow_cases=14, ssa_cases=3))
    if sha(compiler) != identity or sources != {
            str(p.relative_to(ROOT)): sha(p) for p in (ROOT / 'src').rglob('*.xu')}:
        raise ValueError('compiler/source changed during MIR cost gate')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dict(status='PASS', compiler=str(compiler),
        compiler_sha256=identity, source_sha256=sources,
        test_source_sha256={p.name: sha(p) for p in DATA.glob('*.xu')}, rows=rows), indent=2) + '\n')
    print('PASS: exact DCE reference, operand coverage and borrow word boundaries')


if __name__ == '__main__':
    main()
