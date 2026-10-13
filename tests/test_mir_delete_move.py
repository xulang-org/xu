#!/usr/bin/env python3
"""Independent MIR deletion/movement contracts and production-pass gate."""
from pathlib import Path
import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / 'tests/mir_delete_move_test.xu'
CONSTS = [0, 1, 2, 5, 7, 10, 20, 30, 4]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def c(value):
    return -CONSTS.index(value)-2


def ins(kind, a=-1, b=-1, c=-1, d=-1, sval=''):
    return dict(kind=kind, a=a, b=b, c=c, d=d, sval=sval,
                next=-1, line=0, col=0, file=0)


def graph(chains, terms=None, locals_=None, temps=None, orphan=()):
    f = dict(instrs=[], blocks=[], locals=locals_ or [1, 1, 1],
             temps=temps or [1]*16, consts=CONSTS[:], input=[2, 7, 10])
    terms = terms or [(3, c(5), -1, -1)]*len(chains)
    for bi, (chain, term) in enumerate(zip(chains, terms)):
        ids = []
        for q0 in chain:
            q = copy.deepcopy(q0)
            ii = len(f['instrs'])
            q.update(line=101+ii, col=31+ii, file=ii % 3)
            f['instrs'].append(q)
            ids.append(ii)
        f['blocks'].append(dict(head=-1, tail=-1, tkind=term[0], ta=term[1],
                                tb=term[2], tc=term[3], line=401+bi))
        link(f, bi, ids)
    for q0 in orphan:
        q = copy.deepcopy(q0)
        ii = len(f['instrs'])
        q.update(line=101+ii, col=31+ii, file=ii % 3)
        f['instrs'].append(q)
    return f


def link(f, bi, ids):
    """Construct an explicitly specified expected chain, without a search."""
    b = f['blocks'][bi]
    b['head'], b['tail'] = (ids[0], ids[-1]) if ids else (-1, -1)
    for ii, nxt in zip(ids, ids[1:]+[-1]):
        f['instrs'][ii]['next'] = nxt


def tombstone(f, ii):
    q = f['instrs'][ii]
    q.update(kind=0, a=-1, b=-1, c=-1, d=-1, sval='', next=-1)


def empty_block(f, bi):
    f['blocks'][bi].update(head=-1, tail=-1, tkind=0, ta=-1, tb=-1, tc=-1)


def cases():
    rows = []

    def add(name, original, expected, op, bi=0, ii=0, other=0,
            success=True, facts=-1, equivalent=False):
        if equivalent:
            assert execute(original) == execute(expected), name
        rows.append(dict(name=name, original=original, expected=expected,
                         op=op, bi=bi, ii=ii, other=other,
                         success=success, facts=facts, equivalent=equivalent))

    pure = [ins(1, 0, c(10), 501, 601, 'copy-a'),
            ins(1, 1, c(20), 502, 602, 'copy-b'),
            ins(1, 2, c(30), 503, 603, 'copy-c')]
    for op, word in ((0, 'detach'), (1, 'delete')):
        for position, ii in (('head', 0), ('middle', 1), ('tail', 2), ('sole', 0)):
            f = graph([pure[:1] if position == 'sole' else pure])
            e = copy.deepcopy(f)
            remaining = [j for j in range(len(e['instrs'])) if j != ii]
            link(e, 0, remaining)
            e['instrs'][ii]['next'] = -1
            if op == 1:
                tombstone(e, ii)
            add(f'{word}-{position}', f, e, op, ii=ii, equivalent=True)
        for name, bi, ii in (('wrong-block', 1, 0), ('not-member', 0, 2),
                             ('block-negative', -1, 0), ('block-end', 2, 0),
                             ('instr-negative', 0, -1), ('instr-end', 0, 3)):
            f = graph([[pure[0]], [pure[1]]], orphan=[pure[2]])
            add(f'{word}-{name}', f, copy.deepcopy(f), op, bi, ii,
                success=False, facts=4, equivalent=True)

    # Each effect/payload is retained while the actual InstrId moves.  Calls
    # carry a long owned label; debug location and every operand are checked.
    payloads = [('call', ins(7, -1, 2, -1, 87, 'owned-call-label-with-payload')),
                ('checked-index', ins(14, 3, c(10), c(2), 8, 'checked-index-payload')),
                ('store', ins(18, c(7), 9, 2, 1, 'store-payload')),
                ('copy', ins(1, 3, c(20), 513, 613, 'copy-payload')),
                ('division-trap', ins(4, 3, 4, c(10), c(0), 'division-payload'))]
    for name, payload in payloads:
        f = graph([[payload, ins(1, 0, c(10))],
                   [ins(7, -1, 3, -1, 97, 'second-call'), ins(1, 1, c(30))]],
                  [(1, 1, -1, -1), (3, 1, -1, -1)])
        e = copy.deepcopy(f)
        link(e, 0, [1])
        link(e, 1, [2, 3, 0])
        add(f'move-append-{name}', f, e, 2, other=1)
        # Prepend's contract allocates a fresh instruction record.  It does
        # not claim to move an existing record or erase its original owner.
        e = copy.deepcopy(f)
        q = copy.deepcopy(e['instrs'][0])
        e['instrs'].append(q)
        link(e, 1, [4, 2, 3])
        add(f'insert-prepend-{name}', f, e, 3, bi=1, ii=0)

    # Production deletion passes: results and effects match original MIR,
    # but removed records are now explicit tombstones at stable InstrIds.
    f = graph([[ins(1, 0, c(10)), ins(1, 1, c(20)), ins(4, 2, 1, 1, c(1))]],
              [(3, 2, -1, -1)])
    e = copy.deepcopy(f); tombstone(e, 0); link(e, 0, [1, 2])
    add('dce-unused-copy', f, e, 4, facts=0, equivalent=True)
    f = graph([[ins(1, 0, c(10)), ins(1, 0, 0), ins(1, 1, 0)]],
              [(3, 1, -1, -1)])
    e = copy.deepcopy(f); tombstone(e, 1); link(e, 0, [0, 2])
    add('dce-identity-copy', f, e, 4, facts=0, equivalent=True)
    f = graph([[ins(1, 0, c(10)), ins(1, 1, 0), ins(3, 0, 1)]],
              temps=[4]*16)
    e = copy.deepcopy(f); tombstone(e, 1); e['instrs'][2]['b'] = 0; link(e, 0, [0, 2])
    add('copy-forward-f64-tombstone', f, e, 5, equivalent=True)
    f = graph([[ins(3, 0, c(10)), ins(3, 0, c(20)), ins(2, 0, 0)]],
              [(3, 0, -1, -1)])
    e = copy.deepcopy(f); tombstone(e, 0); link(e, 0, [1, 2])
    add('dse-overwritten-store', f, e, 6, facts=0, equivalent=True)
    f = graph([[ins(2, 0, 0), ins(3, 0, 0)]], [(3, 0, -1, -1)])
    e = copy.deepcopy(f); tombstone(e, 1); link(e, 0, [0])
    add('dse-redundant-store', f, e, 6, facts=0, equivalent=True)
    f = graph([[ins(3, 0, c(10)), ins(7, -1, 2, -1),
                ins(3, 0, c(20)), ins(2, 0, 0)]], [(3, 0, -1, -1)])
    add('dse-call-barrier-keeps-store', f, copy.deepcopy(f), 6,
        success=False, equivalent=True)
    f = graph([[ins(7, 0, 2, -1), ins(14, 1, c(10), c(2), 8),
                ins(4, 2, 4, 0, c(2)), ins(4, 3, 1, 1, 2)]],
              [(3, 3, -1, -1)])
    add('dce-live-call-index-division', f, copy.deepcopy(f), 4,
        success=False, equivalent=True)

    # Real CFG transformations retain Call/trap/store payload and order.
    f = graph([[ins(7, -1, 2, -1, 67, 'pre-call')],
               [ins(7, -1, 3, -1, 87, 'post-call'), ins(18, c(7), 9, 2, 1, 'mem-store'),
                ins(14, 0, c(10), c(2), 8, 'index'), ins(4, 1, 4, 0, c(2))]],
              [(1, 1, -1, -1), (3, 1, -1, -1)])
    e = copy.deepcopy(f); link(e, 0, [0, 1, 2, 3, 4])
    e['blocks'][0].update(tkind=3, ta=1, tb=-1, tc=-1); empty_block(e, 1)
    add('cfg-merge-effects-and-payload', f, e, 7, equivalent=True)

    for condition in (0, 1):
        f = graph([[ins(2, 0, 0)],
                   [ins(1, 1, c(10)), ins(7, -1, 2, -1, 77, 'true-effect')],
                   [ins(1, 1, c(10)), ins(7, -1, 3, -1, 78, 'false-effect')], []],
                  [(2, 0, 1, 2), (1, 3, -1, -1), (1, 3, -1, -1), (3, 1, -1, -1)],
                  locals_=[2, 1, 1], temps=[2]+[1]*15)
        f['input'][0] = condition
        e = copy.deepcopy(f); link(e, 0, [0, 1]); link(e, 1, [2]); link(e, 2, [4]); tombstone(e, 3)
        add(f'hoist-common-both-arms-{condition}', f, e, 8, equivalent=True)

    # Bounded three-iteration loop; Copy/Un move to the real preheader and
    # the induction state plus return remain unchanged.
    f = graph([[ins(3, 0, c(0))],
               [ins(1, 0, c(10), -1, -1, 'loop-copy'), ins(5, 1, 1, 0, -1, 'loop-negate'),
                ins(2, 2, 0), ins(4, 3, 1, 2, c(1)), ins(3, 0, 3), ins(4, 4, 8, 3, c(5))], []],
              [(1, 1, -1, -1), (2, 4, 1, 2), (3, 1, -1, -1)],
              temps=[1, 1, 1, 1, 2]+[1]*11)
    e = copy.deepcopy(f); link(e, 0, [0, 1, 2]); link(e, 1, [3, 4, 5, 6])
    add('licm-copy-and-unary-move', f, e, 9, equivalent=True)

    # Reachability authorizes deleting an unreachable effect, but merely
    # dropping its block header or presenting an orphan cannot do so.
    f = graph([[], [ins(7, -1, 2, -1, 99, 'dead-effect'), ins(1, 0, c(20))]])
    e = copy.deepcopy(f); tombstone(e, 0); tombstone(e, 1); empty_block(e, 1)
    add('unreachable-call-explicit-tombstone', f, e, 10, facts=0, equivalent=True)
    f = graph([[], [ins(1, 0, c(20))]],
              [(3, c(5), -1, -1), (0, -1, -1, -1)])
    e = copy.deepcopy(f); tombstone(e, 0); empty_block(e, 1)
    add('unreachable-open-linked-block', f, e, 10, facts=0, equivalent=True)
    for kind, payload in [('call', ins(7, -1, 2, -1, 99, 'unproved-effect')),
                          ('copy', ins(1, 0, c(20)))]:
        f = graph([[]], orphan=[payload])
        add(f'orphan-{kind}-still-rejected', f, copy.deepcopy(f), 11,
            success=False, facts=4, equivalent=True)

    # Membership alone does not authorize arbitrary executable-orphan
    # cleanup. A detached valid Copy remains rejected until reattached.
    for op, name in [(0, 'detach-is-not-deletion'), (1, 'delete-is-tombstone'),
                     (12, 'repeat-delete-is-not-success')]:
        f = graph([[ins(1, 0, c(10))]])
        e = copy.deepcopy(f); link(e, 0, []); e['instrs'][0]['next'] = -1
        if op != 0: tombstone(e, 0)
        add(name, f, e, op, success=op != 12, facts=4 if op == 0 else 0, equivalent=True)

    for operation, word in [(4, 'div'), (5, 'mod'), (99, 'unknown')]:
        f = graph([[ins(4, 0, operation, c(10), c(0))]])
        add('dce-unused-'+word+'-retained', f, copy.deepcopy(f), 4,
            success=False, equivalent=True)
    f = graph([[ins(4, 0, 1, c(10), c(20), 'opaque-bin-contract')]])
    add('dce-tagged-bin-retained', f, copy.deepcopy(f), 4,
        success=False, equivalent=True)

    # Rebuild passthrough records use owned snapshots. These direct rewrite
    # tests audit the common cloning path, not aggregate eligibility.
    for op, word in [(13, 'sroa'), (14, 'array-sroa')]:
        f = graph([[ins(7, 0, 2, -1, 33, 'long-owned-call-payload'),
                    ins(14, 1, c(10), c(2), 8, 'checked-index-payload'),
                    ins(18, c(7), 9, 2, 1, 'observable-store-payload'),
                    ins(4, 2, 4, 1, c(2), 'retained-division-payload')]],
                  [(3, 2, -1, -1)], orphan=[ins(7, -1, 3, -1, 88, 'unrelated-orphan')])
        e = copy.deepcopy(f)
        originals = copy.deepcopy(f['instrs'][:4])
        for j in range(4): tombstone(e, j)
        e['instrs'] += originals
        link(e, 0, [5, 6, 7, 8])
        add(word+'-clone-payload-order-retire-sources', f, e, op, equivalent=True)

    # Explicitly known pure callee: its value matches the independent Call
    # model; suffix records retain original identity and observable order.
    for position, prefix, suffix in [
            ('head', [], [ins(7, -1, 2, -1, 33, 'suffix-owned-call')]),
            ('middle', [ins(1, 0, c(10))], [ins(7, -1, 2, -1, 33, 'suffix-owned-call')]),
            ('tail', [ins(1, 0, c(10))], []), ('sole', [], [])]:
        ci = len(prefix)
        f = graph([prefix+[ins(7, 1, 200, -1, 0, 'replaced-owned-call')]+suffix],
                  [(3, 1, -1, -1)])
        e = copy.deepcopy(f); tombstone(e, ci); e['temps'].append(1)
        ni = len(e['instrs'])
        cloned = ins(1, 16, c(7), sval='cloned-owned-value-label')
        cloned.update(line=701, col=702, file=2)
        e['instrs'] += [cloned, ins(1, 1, 16)]
        e['blocks'][0].update(tkind=1, ta=1, tb=-1, tc=-1)
        e['blocks'] += [dict(head=-1, tail=-1, tkind=1, ta=2, tb=-1, tc=-1, line=700),
                        dict(head=-1, tail=-1, tkind=3, ta=1, tb=-1, tc=-1, line=401)]
        link(e, 0, list(range(ci))); link(e, 1, [ni, ni+1])
        link(e, 2, list(range(ci+1, len(f['instrs']))))
        add('inline-replacement-'+position, f, e, 15, ii=ci, equivalent=True)
    return rows


def wrap(v):
    return (v+2**63) % 2**64-2**63


def execute(f):
    """Independent linked interpreter; never calls deletion/planning logic."""
    nl = len(f['locals'])
    state = f['input'][:] + [0]*(nl+len(f['temps'])-len(f['input']))
    def value(v):
        return state[nl+v] if v >= 0 else f['consts'][-v-2] if v <= -2 else 0
    bi, trace = 0, 0
    for _ in range(64):
        b = f['blocks'][bi]; ii = b['head']
        for _j in range(len(f['instrs'])):
            if ii < 0:
                break
            q = f['instrs'][ii]; k, a, bb, cc, dd = [q[key] for key in ('kind', 'a', 'b', 'c', 'd')]
            if k == 1: state[nl+a] = value(bb)
            elif k == 2: state[nl+a] = state[bb]
            elif k == 3: state[a] = value(bb)
            elif k == 4:
                x, y = value(cc), value(dd)
                if bb == 1: v = wrap(x+y)
                elif bb == 2: v = wrap(x-y)
                elif bb == 3: v = wrap(x*y)
                elif bb in (4, 5):
                    if not y: return [2, 0, trace]
                    quotient = abs(x)//abs(y) * (-1 if (x < 0) != (y < 0) else 1)
                    v = quotient if bb == 4 else x-quotient*y
                elif bb == 8: v = int(x < y)
                else: return [9, 0, trace]
                state[nl+a] = v
            elif k == 5 and bb == 1: state[nl+a] = wrap(-value(cc))
            elif k == 7:
                if bb == 200:
                    if a >= 0: state[nl+a] = 7
                else:
                    trace = wrap(trace*131+1000+bb)
                    if a >= 0: state[nl+a] = 100+bb
            elif k == 14:
                idx = value(cc); trace = wrap(trace*131+2000+idx)
                if idx < 0 or idx >= 4: return [1, 0, trace]
                state[nl+a] = value(bb)+idx*7
            elif k == 18: trace = wrap(trace*131+3000+value(a))
            elif k != 0: return [9, 0, trace]
            ii = q['next']
        if b['tkind'] == 3: return [0, value(b['ta']), trace]
        if b['tkind'] == 1: bi = b['ta']
        elif b['tkind'] == 2: bi = b['tb'] if value(b['ta']) else b['tc']
        else: return [8, 0, trace]
    return [7, 0, trace]


def dump(f):
    out = [len(f['instrs']), len(f['blocks'])]
    for q in f['instrs']:
        out += [q[key] for key in ('kind', 'a', 'b', 'c', 'd', 'sval', 'next', 'line', 'col', 'file')]
    for b in f['blocks']:
        out += [b[key] for key in ('head', 'tail', 'tkind', 'ta', 'tb', 'tc', 'line')]
    return out


def generate(data):
    rows = cases(); support = [SUPPORT.read_text()]; main = ['@main', '#xu/types']
    expected = []; oracle = []
    for cid, row in enumerate(rows):
        f = row['original']
        support += [f'pub fn delete_move_fixture_{cid}() MFn {{', ' mut f := mir_fn_blank()',
                    ' f.ret = 1', ' f.ret_nslots = 1', f' f.nparams = {len(f["locals"])}']
        for ty in f['locals']:
            support += [f' f.locals.push({ty})', ' f.locals_nslots.push(1)',
                        ' f.locals_owning.push(false)', ' f.moved.push(false)', ' f.fcons.push(0)']
        for ty in f['temps']:
            support += [f' f.temps.push({ty})', ' f.temps_nslots.push(1)']
        for val in f['consts']: support += [f' f.consts.push({val})']
        for b in f['blocks']:
            support += [' f.blocks.push(MBlock{'+', '.join(f'{key}: {val}' for key, val in b.items())+'})']
        for q in f['instrs']:
            support += [' f.instrs.push(MInstr{'+', '.join(f'{key}: {json.dumps(val)}' for key, val in q.items())+'})']
        support += [' << f', '}']
        first = len(expected)+1
        main += [f'fn dump_delete_move_{cid}() {{', f' mut f := types.delete_move_fixture_{cid}()',
                 ' input := ['+', '.join(map(str, f['input']))+']',
                 ' before := types.delete_move_execute(&f, &input)',
                 ' for j in 0:before.len { println(before[j]) }',
                 f' println(types.delete_move_apply(mut &f, {row["op"]}, {row["bi"]}, {row["ii"]}, {row["other"]}))',
                 ' types.delete_move_dump(&f)',
                 ' after := types.delete_move_execute(&f, &input)',
                 ' for j in 0:after.len { println(after[j]) }']
        expected += execute(f)+['true' if row['success'] else 'false']+dump(row['expected'])+execute(row['expected'])
        if row['facts'] >= 0:
            main += [' println(types.delete_move_facts(f))']
        else:
            main += [' println(-1)']
        expected += [row['facts']]; main += ['}']
        oracle.append(dict(name=row['name'], first_line=first, last_line=len(expected),
                           operation=row['op'], equivalent=row['equivalent'],
                           original=row['original'], expected=row['expected'], facts=row['facts']))
    main += ['fn main() int { argv := args()', ' if argv.len > 1 && argv[1] == "baseline" { << 0 }']
    main += [f' dump_delete_move_{cid}()' for cid in range(len(rows))]+[' << 0', '}']
    data.mkdir(parents=True, exist_ok=True)
    for name, lines in [('support.xu', support), ('main.xu', main), ('expected.txt', expected)]:
        (data/name).write_text('\n'.join(map(str, lines))+'\n')
    (data/'oracle.json').write_text(json.dumps(dict(cases=oracle, output_lines=len(expected),
        semantic_runs=len(rows)*2, equivalent_cases=sum(row['equivalent'] for row in rows)), indent=2)+'\n')
    return oracle, (data/'expected.txt').read_bytes()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--xu', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--source-root', type=Path, default=ROOT)
    p.add_argument('--data-dir', type=Path)
    p.add_argument('--modes', default='O0,O1,O2,O3,no-regcache,ra0,ra1,ra2')
    p.add_argument('--generate-only', action='store_true')
    a = p.parse_args()
    source, compiler = a.source_root.resolve(), a.xu.resolve()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    data = (a.data_dir or a.out.parent/'delete-move-data').resolve()
    oracle, expected = generate(data)
    if a.generate_only:
        print(f'Generated {len(oracle)} independent cases and {len(expected.splitlines())} golden lines')
        return
    options = dict(O0=['-O0'], O1=['-O1'], O2=['-O2'], O3=['-O3'],
                   **{'no-regcache': ['--no-regcache'], 'ra0': ['--ra=0'], 'ra1': ['--ra=1'], 'ra2': ['--ra=2']})
    modes = a.modes.split(',')
    if any(mode not in options for mode in modes): p.error('unknown mode')
    compiler_identity = sha(compiler)
    source_identity = {str(path.relative_to(source)): sha(path) for path in (source/'src').rglob('*.xu')}
    test_identity = {str(path.relative_to(ROOT)): sha(path) for path in (SUPPORT, Path(__file__))}
    actual = data/'actual'; actual.mkdir(exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory(prefix='xu-delete-move-') as td:
        work = Path(td)
        shutil.copytree(source/'src', work/'src')
        shutil.copytree(source/'scripts', work/'scripts')
        shutil.copy2(data/'support.xu', work/'src/xu/types/delete_move_test.xu')
        shutil.copy2(data/'main.xu', work/'main.xu')
        for mode in modes:
            binary = actual/mode
            env = dict(os.environ); env.pop('XU_HEAP_STATS', None)
            if mode in ('O0', 'O3'): env['XU_GEN1_HEAP_LEDGER'] = '1'
            build = subprocess.run([str(work/'scripts/run_product_compiler.sh'), str(compiler),
                'build', *options[mode], str(work/'main.xu'), '-o', str(binary)],
                cwd=work, capture_output=True, env=env, timeout=300)
            (actual/f'{mode}.build.stderr').write_bytes(build.stderr)
            if build.returncode:
                raise ValueError(f'{mode}: build failed: {build.stderr.decode(errors="replace")}')
            run_env = dict(os.environ); run_env.pop('XU_HEAP_STATS', None)
            run = subprocess.run([str(binary)], capture_output=True, env=run_env, timeout=90)
            (actual/f'{mode}.stdout').write_bytes(run.stdout)
            (actual/f'{mode}.stderr').write_bytes(run.stderr)
            if run.returncode or run.stderr or run.stdout != expected:
                want, got = expected.decode().splitlines(), run.stdout.decode(errors='replace').splitlines()
                first = next((i+1 for i, pair in enumerate(zip(want, got)) if pair[0] != pair[1]), min(len(want), len(got))+1)
                case = next((row['name'] for row in oracle if row['first_line'] <= first <= row['last_line']), 'outside')
                a.out.with_suffix('.failure.json').write_text(json.dumps(dict(mode=mode, rc=run.returncode,
                    stderr=run.stderr.decode(errors='replace'), case=case, first_mismatch_line=first), indent=2)+'\n')
                raise ValueError(f'{mode}: mismatch line {first} in {case}; rc={run.returncode}, stderr={run.stderr!r}')
            heap = {}
            if mode in ('O0', 'O3'):
                ledgers = []
                for arg in ('baseline', 'run_____'):
                    r = subprocess.run([str(binary), arg], capture_output=True, text=True,
                                       env=dict(run_env, XU_HEAP_STATS='1'), timeout=90)
                    (actual/f'{mode}.{arg}.ledger').write_text(r.stderr)
                    stats = {k: int(v) for k, v in re.findall(r'xu_heap_stats (\w+)=(\d+)', r.stderr)}
                    extra = re.sub(r'xu_heap_stats \w+=\d+\n', '', r.stderr)
                    if r.returncode or extra or len(stats) != 7 or r.stdout != ('' if arg == 'baseline' else expected.decode()):
                        raise ValueError(f'{mode}/{arg}: invalid ledger output')
                    ledgers.append(stats)
                baseline, result = ledgers
                if (result['live_bytes'] != baseline['live_bytes'] or
                    result['allocs']-result['frees'] != baseline['allocs']-baseline['frees'] or
                    any(row[k] for row in ledgers for k in ('unknown_frees', 'double_frees', 'ledger_overflows'))):
                    raise ValueError(f'{mode}: heap ledger failed: {ledgers}')
                heap = dict(baseline=baseline, actual=result, incremental_live_bytes=0, incremental_net_allocations=0)
            rows.append(dict(mode=mode, status='PASS', golden_lines=len(expected.splitlines()),
                             binary_sha256=sha(binary), stdout_sha256=hashlib.sha256(run.stdout).hexdigest(),
                             heap_ledger=heap))
    if (sha(compiler) != compiler_identity or
        source_identity != {str(path.relative_to(source)): sha(path) for path in (source/'src').rglob('*.xu')} or
        test_identity != {str(path.relative_to(ROOT)): sha(path) for path in (SUPPORT, Path(__file__))}):
        raise ValueError('compiler/source/test changed during delete/move gate')
    report = dict(status='PASS', compiler_sha256=compiler_identity, source_sha256=source_identity,
                  test_sha256=test_identity, cases=len(oracle), semantic_runs=len(oracle)*2,
                  golden_lines=len(expected.splitlines()), oracle_sha256=sha(data/'oracle.json'),
                  expected_sha256=sha(data/'expected.txt'), support_sha256=sha(data/'support.xu'), rows=rows,
                  scope='Explicit expected full MIR records/chains, independent linked execution and production passes. Call/Index/StorePtr are interpreter events, not host effects; no optimization performance claim.')
    a.out.write_text(json.dumps(report, indent=2)+'\n')
    print(f'PASS: {len(oracle)} cases, {report["golden_lines"]} golden lines x {len(rows)} modes; {len(oracle)*2} executions per mode')


if __name__ == '__main__':
    main()
