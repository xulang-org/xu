#!/usr/bin/env python3
"""Exercise large mixed FP/index CFGs through actual compiler admission and emission."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MODES = {'O0': ['-O0'], 'O1': ['-O1'], 'O2': ['-O2'], 'O3': ['-O3'],
         'no-regcache': ['--no-regcache'], 'ra0': ['-O3', '--ra=0']}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pbm(size):
    width = (size + 7) // 8 * 8
    out = bytearray(width * width // 8)
    for y in range(width):
        ci = 2.0 * y / width - 1.0
        for x in range(width):
            cr = 2.0 * x / width - 1.5
            zr = zi = tr = ti = 0.0
            step = 0
            while step < 50 and tr + ti <= 4.0:
                zi = 2.0 * zr * zi + ci
                zr = tr - ti + cr
                tr, ti = zr * zr, zi * zi
                step += 1
            if tr + ti <= 4.0:
                out[y * (width // 8) + x // 8] |= 128 >> (x & 7)
    return f'P4\n{width} {width}\n'.encode() + out


def branches():
    return '\n'.join(f'if i % {k} == 0 {{ z += 0.5 }} else {{ z += 0.25 }}'
                     for k in range(2, 22))


def mixed_source(ty):
    cast = 'u8(int(z * 4.0) & 255)' if ty == 'u8' else 'int(z * 4.0)' if ty == 'int' else 'z * 4.0'
    source = f'''@main
fn cfg_{ty}(dst &mut []{ty}, seed f64) f64 {{
    mut z := seed
    for i in 0:dst.len {{
        {branches()}
        dst[i] = dst[i] + {cast}
    }}
    << z
}}
fn main() int {{
    mut dst := []{ty}{{}}
    for i in 0:37 {{ dst.push({ty}(i & 3)) }}
    println(int(cfg_{ty}(mut &dst, 0.25) * 4.0))
    for i in 0:dst.len {{ println(int(dst[i])) }}
    println(int(cfg_{ty}(mut &dst, 1.5) * 4.0))
    for i in 0:dst.len {{ println(int(dst[i])) }}
    mut empty := []{ty}{{}}
    println(int(cfg_{ty}(mut &empty, 2.25) * 4.0))
    << 0
}}
'''
    values = [i & 3 for i in range(37)]
    lines = []
    for seed in (0.25, 1.5):
        z = seed
        for i in range(37):
            z += sum(0.5 if i % k == 0 else 0.25 for k in range(2, 22))
            values[i] += int(z * 4)
            if ty == 'u8':
                values[i] &= 255
        lines += [str(int(z * 4)), *map(str, values)]
    lines.append('9')
    return source, ('\n'.join(lines) + '\n').encode()


def fallback_source():
    # Recursion prevents the unknown call from being erased by inlining.
    source = f'''@main
fn external_shape(x int) f64 {{
    if x <= 0 {{ << 0.25 }}
    << external_shape(x - 1) + 0.25
}}
fn cfg_call(dst &mut []int) f64 {{
    mut z := 0.25
    for i in 0:dst.len {{
        {branches()}
        z += external_shape(i % 3)
        dst[i] = int(z * 4.0)
    }}
    << z
}}
fn main() int {{
    mut dst := []int{{}}
    for i in 0:37 {{ dst.push(0) }}
    println(int(cfg_call(mut &dst) * 4.0))
    for i in 0:dst.len {{ println(dst[i]) }}
    << 0
}}
'''
    z, values = 0.25, []
    for i in range(37):
        z += sum(0.5 if i % k == 0 else 0.25 for k in range(2, 22))
        z += (i % 3 + 1) * 0.25
        values.append(str(int(z * 4)))
    return source, ('\n'.join([str(int(z * 4)), *values]) + '\n').encode()


def build(compiler, source, binary, flags, root=ROOT):
    command = [str(root / 'scripts/run_product_compiler.sh'), str(compiler),
               'build', *flags, str(source), '-o', str(binary)]
    result = subprocess.run(command, cwd=root, capture_output=True, timeout=180)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    return result.stderr.decode()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--modes', default=','.join(MODES))
    args = ap.parse_args()
    compiler, out = args.xu.resolve(), args.out.resolve()
    data = out.with_suffix('')
    data.mkdir(parents=True, exist_ok=True)
    identity = sha(compiler)
    source_ids = {str(p.relative_to(ROOT)): sha(p) for p in (ROOT / 'src').rglob('*.xu')}
    rows = []
    report = dict(status='RUNNING', compiler_sha256=identity, source_sha256=source_ids, rows=rows)
    with tempfile.TemporaryDirectory(prefix='xu-f64-cfg-') as td:
        work = Path(td)
        shutil.copytree(ROOT / 'src', work / 'src')
        shutil.copytree(ROOT / 'scripts', work / 'scripts')
        emit = work / 'src/cmd/compile/emit_function.xu'
        text = emit.read_text()
        seam = '    ra_note_fn(a, try_vregs, has_vreg, a.rc_on, scalar_spills)'
        assert text.count(seam) == 1
        # Diagnostic copy only. Requiring identical program bytes below keeps
        # the observer from silently masking a self-host/code-generation bug.
        emit.write_text(text.replace(seam, seam + '''
    mut cfg_name := ""
    for cfg_i in 0:types.mir_fn_name_len(m, fi) { cfg_name.push_byte(types.mir_fn_name_byte(m, fi, cfg_i)) }
    eprintln("[TEST-F64-CFG] " + cfg_name + " blocks=" + str(types.mir_nblocks(m, fi)) + " try=" + str(try_vregs) + " vreg=" + str(has_vreg) + " frame=" + str(fr.size))
'''))
        srcs = [work / 'src/cmd/compile/main.xu', *sorted(p for p in (work / 'src/cmd/compile').glob('*.xu') if p.name != 'main.xu')]
        observer = data / 'observer'
        result = subprocess.run([str(work / 'scripts/run_product_compiler.sh'), str(compiler),
            'build', *map(str, srcs), '-o', str(observer)], cwd=work, capture_output=True, timeout=300)
        (data / 'observer.build.log').write_bytes(result.stderr)
        assert result.returncode == 0, result.stderr.decode()
        cases = [('mandelbrot', ROOT / 'tests/data/compiler_workloads/game/mandelbrot.xu', 'render',
                  [(str(n), pbm(n)) for n in (0, 1, 8, 15, 24, 64, 200)], True)]
        for ty in ('u8', 'int', 'f64'):
            source, expected = mixed_source(ty)
            path = data / f'cfg_{ty}.xu'
            path.write_text(source)
            cases.append((f'cfg_{ty}', path, f'cfg_{ty}', [('', expected)], True))
        source, expected = fallback_source()
        path = data / 'cfg_call.xu'
        path.write_text(source)
        cases.append(('cfg_call', path, 'cfg_call', [('', expected)], False))
        oob = data / 'cfg_oob.xu'
        oob.write_text(f'''@main
fn cfg_oob(dst &mut []u8) {{
    mut z := 0.25
    for i in 0:dst.len {{ {branches()}
        dst[i + 1] = u8(int(z * 4.0) & 255)
    }}
}}
fn main() int {{
    mut dst := []u8{{}}
    for i in 0:5 {{ dst.push(u8(0)) }}
    cfg_oob(mut &dst)
    << 0
}}
''')
        cases.append(('cfg_oob', oob, 'cfg_oob', [('', b'')], True))
        for mode in args.modes.split(','):
            flags = MODES[mode]
            enabled = mode in ('O1', 'O2', 'O3')
            for name, source, target, inputs, admitted in cases:
                binary, observed = data / f'{name}-{mode}', data / f'{name}-{mode}-observed'
                build(compiler, source, binary, flags)
                diagnostics = build(observer, source, observed, flags)
                (data / f'{name}-{mode}.log').write_text(diagnostics)
                assert binary.read_bytes() == observed.read_bytes(), (name, mode, 'observer changes emitted program')
                match = re.search(r'\[TEST-F64-CFG\] ' + target + r' blocks=(\d+) try=(\w+) vreg=(\w+) frame=(\d+)', diagnostics)
                assert match, (name, mode, 'missing admission observation')
                blocks, attempted, vreg, frame = match.groups()
                for argument, expected in inputs:
                    run = subprocess.run([str(binary), *([argument] if argument else [])], capture_output=True, timeout=60)
                    if name == 'cfg_oob':
                        assert run.returncode == 1 and run.stdout == b'' and run.stderr == b'index out of bounds\n', (name, mode, run)
                    else:
                        assert run.returncode == 0 and run.stdout == expected and not run.stderr, (name, mode, argument, run.stdout, expected, run.stderr)
                row = dict(case=name, mode=mode, blocks=int(blocks), attempted=attempted, vreg=vreg,
                           frame_bytes=int(frame), binary_sha256=sha(binary), inputs=len(inputs), status='PASS')
                rows.append(row)
                out.write_text(json.dumps(report, indent=2) + '\n')
                if enabled:
                    assert int(blocks) > 32, (name, mode, 'does not exercise large CFG')
                    assert (attempted, vreg) == (('true', 'true') if admitted else ('false', 'false')), (name, mode, row)
                else:
                    assert (attempted, vreg) == ('false', 'false'), (name, mode, row)
    assert identity == sha(compiler)
    assert source_ids == {str(p.relative_to(ROOT)): sha(p) for p in (ROOT / 'src').rglob('*.xu')}
    report['status'] = 'PASS'
    report['scope'] = 'Actual source/MIR admission and emitted programs; independent Python numeric/PBM oracles, fallback calls and OOB traps. Observer output binaries must equal product binaries.'
    out.write_text(json.dumps(report, indent=2) + '\n')
    print(f'PASS: {len(rows)} source/mode configurations; {sum(r["inputs"] for r in rows)} executions')


if __name__ == '__main__':
    main()
