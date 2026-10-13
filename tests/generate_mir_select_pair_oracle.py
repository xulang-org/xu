#!/usr/bin/env python3
"""Independent sequential MIR and simultaneous SelectPair semantic oracle."""
from pathlib import Path
import argparse
import copy
import json
import random


CONSTS = [0, 1, 99, 2**63 - 1, -2**63]


def wrap(value):
    return (value + 2**63) % 2**64 - 2**63


def xu_int(value):
    return '0 - 9223372036854775807 - 1' if value == -2**63 else str(value)


def ins(k, a=0, b=0, c=0, d=0):
    return dict(k=k, a=a, b=b, c=c, d=d)


def block(es=(), tk=1, a=3, b=-1, c=-1):
    return dict(es=list(es), tk=tk, a=a, b=b, c=c)


def fixture(name='four-sources', storage='Local', seed=None, chain=1, padding=0):
    nl, nt, np = 9, 24, 5
    lt, tt = [2] + [1]*6 + [2, 2], [1]*nt
    tt[0] = 2
    outs = [('L', 5), ('L', 6)] if storage == 'Local' else [('T', 5), ('T', 6)] if storage == 'Temp' else [('L', 5), ('T', 6)]
    entry = [ins(2, 0, 0)] + [ins(2, i, i) for i in range(1, 5)]
    for (kind, cell), src in zip(outs, (1, 2)):
        entry.append(ins(3 if kind == 'L' else 1, cell, src))
    def write(out, value):
        kind, cell = out
        return ins(3 if kind == 'L' else 1, cell, value)
    bs = [block(entry, 2, 0, 1, 2),
          block([write(outs[0], 1), write(outs[1], 2)]),
          block([write(outs[0], 3), write(outs[1], 4)]),
          block([], 3, 23)]
    accepted = True
    phis = {}
    from_ = 0
    if name == 'commuted-plus-one':
        bs[1]['es'] = [ins(4, 11, 1, -3, 1), write(outs[0], 11), write(outs[1], 2)]
    elif name == 'wrap-plus-one':
        bs[1]['es'] = [ins(4, 11, 1, 1, -3), write(outs[0], 11), write(outs[1], 2)]
    elif name == 'constant-wrap':
        bs[1]['es'] = [ins(4, 11, 1, -5, -3), write(outs[0], 11), write(outs[1], -6)]
    elif name == 'constant-pair':
        bs[1]['es'] = [write(outs[0], -5), write(outs[1], -6)]
        bs[2]['es'] = [write(outs[0], -6), write(outs[1], -5)]
    elif name == 'cross-cell-swap':
        assert storage == 'Local'
        bs[1]['es'] = [ins(2, 7, 5), ins(2, 8, 6), ins(3, 5, 8), ins(3, 6, 7)]
        bs[2]['es'] = [ins(2, 7, 5), ins(2, 8, 6), ins(3, 5, 7), ins(3, 6, 8)]
    elif name == 'serial-cross-cell':
        assert storage == 'Local'
        bs[1]['es'] = [ins(2, 7, 6), ins(3, 5, 7), ins(2, 8, 5), ins(3, 6, 8)]
    elif name == 'old-temp-snapshot':
        assert storage == 'Temp'
        bs[1]['es'] = [ins(1, 7, 5), ins(1, 5, 6), ins(1, 6, 7)]
        bs[2]['es'] = [ins(1, 7, 5), ins(1, 5, 7), ins(1, 6, 7)]
    elif name == 'old-local-snapshot':
        assert storage == 'Local'
        bs[1]['es'] = [ins(2, 7, 5), ins(3, 5, 2), ins(3, 6, 7)]
    elif name in ('keep-true', 'keep-false'):
        arm = 1 if name == 'keep-true' else 2
        bs[arm]['es'] = []
    elif name in ('direct-true', 'direct-false'):
        arm = 1 if name == 'direct-true' else 2
        bs[0]['b' if arm == 1 else 'c'] = 3
        bs[arm]['es'] = []
    elif name == 'bool-pair':
        outs = [('L', 7), ('T', 18)]
        tt[18] = 2
        bs[0]['es'] += [ins(3, 7, 0), ins(1, 18, 0)]
        bs[1]['es'] = [write(outs[0], 0), write(outs[1], -2)]
        bs[2]['es'] = [write(outs[0], -3), write(outs[1], 0)]
    elif name == 'condition-copy':
        tt[19] = 2
        bs[0]['es'].append(ins(1, 19, 0)); bs[0]['a'] = 19
    elif name == 'entry-prefix':
        from_ = len(bs)
        bs.append(block([], 2, 0, 1, 2)); bs[0]['tk'] = 1; bs[0]['a'] = from_; bs[0]['b'] = bs[0]['c'] = -1
    elif name == 'real-phi':
        assert storage == 'Temp'
        bs[0]['es'] = entry[:-2]
        bs[1]['es'] = [ins(1, 7, 1), ins(1, 8, 2)]
        bs[2]['es'] = [ins(1, 9, 3), ins(1, 10, 4)]
        phis = {3: [(5, {1: 7, 2: 9}), (6, {1: 8, 2: 10})]}
    elif name == 'third-temp-escape':
        bs[0]['es'].append(ins(1, 9, 4)); bs[1]['es'].append(ins(1, 9, 1)); accepted = False
    elif name == 'third-local-escape':
        bs[1]['es'].append(ins(3, 8, -3)); accepted = False
    elif name == 'call':
        bs[1]['es'].append(ins(7, 11, 1, -1)); accepted = False
    elif name == 'division':
        bs[1]['es'].append(ins(4, 11, 4, 1, -2)); accepted = False
    elif name == 'unary':
        bs[1]['es'].append(ins(5, 11, 1, 1)); accepted = False
    elif name == 'multiply':
        bs[1]['es'].append(ins(4, 11, 3, 1, -3)); accepted = False
    elif name == 'double-increment':
        bs[1]['es'] = [ins(4, 11, 1, 1, -3), ins(4, 12, 1, 11, -3), write(outs[0], 12), write(outs[1], 2)]; accepted = False
    elif name == 'undefined-source':
        bs[1]['es'][0]['b'] = 16; accepted = False
    elif name == 'bool-increment':
        tt[11] = 2; bs[1]['es'].append(ins(4, 11, 1, 0, -3)); accepted = False
    elif name == 'one-output':
        bs[1]['es'] = bs[1]['es'][:1]; bs[2]['es'] = bs[2]['es'][:1]; accepted = False
    elif name == 'duplicate-successor':
        bs[0]['c'] = 1; accepted = False
    elif name == 'extra-predecessor':
        from_ = len(bs)
        bs.append(block([], 2, 0, 1, 2)); bs.append(block([], 1, 1))
        bs[0]['b'], bs[0]['c'] = from_, from_ + 1; accepted = False
    elif name == 'shared-chain':
        bs[2]['a'] = 1; accepted = False
    elif name == 'cycle':
        bs[1]['a'] = 1; accepted = False
    elif name == 'dead-call':
        bs.append(block([ins(7, 11, 1, -1)], 3, -4)); accepted = False
    elif name == 'dead-empty-return':
        bs.append(block([], 3, -1))
    elif name == 'reachable-empty-return':
        bs[3]['a'] = -1; accepted = False
    elif name == 'dead-nonempty-return':
        bs.append(block([ins(1, 17, -2)], 3, -1)); accepted = False
    elif name == 'dead-malformed-return':
        bs.append(block([], 3, -1, 0)); accepted = False
    elif name != 'four-sources':
        raise ValueError(name)
    for pos, (kind, cell) in enumerate(outs):
        dest = 21 + pos
        tt[dest] = lt[cell] if kind == 'L' else tt[cell]
        bs[3]['es'].append(ins(2 if kind == 'L' else 1, dest, cell))
    bs[3]['es'].append(ins(1, 23, -4 if tt[21] == 2 else 21))
    if name == 'third-temp-escape':
        bs[3]['es'].append(ins(1, 23, 9))
    tail = 1
    for _ in range(chain - 1):
        to = len(bs); bs[tail]['a'] = to; bs.append(block([], 1, 3)); tail = to
    bs[1]['es'] += [ins(0)] * padding
    if chain > 8 or len(bs[1]['es']) > 128:
        accepted = False
    if phis and tail != 1:
        for _, args in phis[3]: args[tail] = args.pop(1)
    lm, tm, bm = list(range(nl)), list(range(nt)), list(range(len(bs)))
    if seed is not None:
        rng = random.Random(seed)
        formal = list(range(np)); rng.shuffle(formal)
        rest = list(range(np, nl)); rng.shuffle(rest); lm = formal + rest
        rng.shuffle(tm)
        rest = list(range(1, len(bs))); rng.shuffle(rest); bm = [0] + rest
    out = [None] * len(bs)
    for bi, old in enumerate(bs):
        b = copy.deepcopy(old)
        if b['tk'] == 1: b['a'] = bm[b['a']]
        else:
            if b['a'] >= 0: b['a'] = tm[b['a']]
            if b['tk'] == 2: b['b'], b['c'] = bm[b['b']], bm[b['c']]
        for e in b['es']:
            k = e['k']
            if k in (0, 7): continue
            e['a'] = lm[e['a']] if k == 3 else tm[e['a']]
            if k == 2: e['b'] = lm[e['b']]
            elif k in (1, 3) and e['b'] >= 0: e['b'] = tm[e['b']]
            elif k in (4, 5):
                for key in ('c', 'd') if k == 4 else ('c',):
                    if e[key] >= 0: e[key] = tm[e[key]]
        out[bm[bi]] = b
    locals_, temps = [0]*nl, [0]*nt
    for i, ty in enumerate(lt): locals_[lm[i]] = ty
    for i, ty in enumerate(tt): temps[tm[i]] = ty
    outputs = sorted([(1 if k == 'L' else 2, lm[i] if k == 'L' else tm[i]) for k, i in outs], key=lambda v: v[1] + (nl if v[0] == 2 else 0))
    return dict(name=name+'-'+storage, blocks=out, locals=locals_, types=temps, nparams=np, consts=CONSTS,
                phis={bm[b]: [(tm[d], {bm[p]: tm[v] for p, v in args.items()}) for d, args in rows] for b, rows in phis.items()},
                phi_locals={tm[5]: lm[5], tm[6]: lm[6]},
                from_=bm[from_], join=bm[3], outputs=outputs, input_map=lm[:np], accepted=accepted,
                chain=chain, padding=padding, seed=seed)


def execute(c, inputs):
    loc, tmp = [None]*len(c['locals']), [None]*len(c['types'])
    for old, at in enumerate(c['input_map']): loc[at] = inputs[old]
    def value(v): return tmp[v] if v >= 0 else c['consts'][-v-2]
    bi, pred = 0, -1
    for _ in range(128):
        writes = [(d, value(args[pred])) for d, args in c['phis'].get(bi, [])]
        for d, val in writes: tmp[d] = val
        for e in c['blocks'][bi]['es']:
            k, a, b, x, y = (e[v] for v in ('k', 'a', 'b', 'c', 'd'))
            if k == 1: tmp[a] = value(b)
            elif k == 2: tmp[a] = loc[b]
            elif k == 3: loc[a] = value(b)
            elif k == 4:
                assert b == 1
                tmp[a] = wrap(value(x) + value(y))
            elif k != 0: raise AssertionError(k)
        bb = c['blocks'][bi]
        if bb['tk'] == 3:
            return [loc[i] if k == 1 else tmp[i] for k, i in c['outputs']] + [value(bb['a'])]
        pred, bi = bi, bb['a'] if bb['tk'] == 1 else bb['b'] if value(bb['a']) else bb['c']
    raise AssertionError('MIR did not terminate')


def edge_symbols(c, arm):
    """Execute symbolic paths independently; snapshots are at from terminator."""
    nl, nt = len(c['locals']), len(c['types'])
    env = [('snapshot', i, 0) for i in range(nl+nt)]
    touched = [0]*(nl+nt)
    from_ = c['from_']; bi = c['blocks'][from_]['b' if arm == 0 else 'c']; pred = from_
    path = []
    def val(v): return env[nl+v] if v >= 0 else ('constant', c['consts'][-v-2], 0)
    while bi != c['join']:
        path.append(bi)
        for e in c['blocks'][bi]['es']:
            k, a, b, x, y = (e[v] for v in ('k', 'a', 'b', 'c', 'd'))
            if k == 0: continue
            dc = a if k == 3 else nl+a
            if k in (1, 3): source = val(b)
            elif k == 2: source = env[b]
            elif k == 4:
                source = val(x) if y < 0 and c['consts'][-y-2] == 1 else val(y)
                source = (source[0], source[1], source[2]+1)
            else: raise AssertionError(k)
            env[dc] = source; touched[dc] = 1
        pred, bi = bi, c['blocks'][bi]['a']
    # Production PhiElim copies implement the original simultaneous Phi.
    if c['phis']:
        writes = [(nl+d, val(args[pred])) for d, args in c['phis'].get(c['join'], [])]
        for dc, source in writes: env[dc] = source; touched[dc] = 1
    expressions = []
    for kind, dest in c['outputs']:
        symbol, source, inc = env[dest + (nl if kind == 2 else 0)]
        ty = c['locals'][dest] if kind == 1 else c['types'][dest]
        sk = 3 if symbol == 'constant' else 1 if source < nl else 2
        expressions.append([sk, source if sk in (1, 3) else source-nl, ty, inc])
    return expressions, path, touched


def emit_fixture(c, cid):
    lines = [f'pub fn select_fixture_{cid}() Mir {{', ' mut m := empty_mir()', ' mut f := mir_fn_blank()',
             f' f.nparams = {c["nparams"]}', ' f.ret = 1', ' f.ret_nslots = 1']
    for ty in c['locals']: lines += [f' f.locals.push({ty})', ' f.locals_nslots.push(1)', ' f.locals_owning.push(false)']
    for ty in c['types']: lines += [f' f.temps.push({ty})', ' f.temps_nslots.push(1)']
    for val in c['consts']: lines.append(' f.consts.push('+xu_int(val)+')')
    for b in c['blocks']: lines.append(f' f.blocks.push(MBlock{{head: -1, tail: -1, tkind: {b["tk"]}, ta: {b["a"]}, tb: {b["b"]}, tc: {b["c"]}, line: 0}})')
    for bi, b in enumerate(c['blocks']):
        for e in b['es']:
            if e['k'] == 0: continue
            lines += [' if true {', f' mut q := mkinstr({e["k"]})'] + [f' q.{key} = {xu_int(e[key])}' for key in 'abcd'] + [f' mir_cfg_append(mut &f, {bi}, q)', ' }']
        noops = sum(e['k'] == 0 for e in b['es'])
        if noops: lines.append(f' for _ in 0:{noops} {{ mir_cfg_append(mut &f, {bi}, mkinstr(0)) }}')
    for bi, rows in c['phis'].items():
        for index, (dest, args) in enumerate(rows):
            pairs = [v for item in args.items() for v in item]
            lines += [' if true {', ' pair := ['+', '.join(map(str, pairs))+']', f' select_add_phi(mut &f, {bi}, {c["phi_locals"][dest]}, {dest}, &pair)', ' }']
    if c['phis']: lines.append(' if !select_finish_phi(mut &f) { << m }')
    lines += [' m.fns.push(f)', ' m.superseded.push(0)', ' << m', '}']
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', required=True, type=Path)
    args = parser.parse_args(); out = args.out_dir; out.mkdir(parents=True, exist_ok=True)
    cases = []
    for storage in ('Local', 'Temp', 'Mixed'):
        for name in ('four-sources', 'wrap-plus-one', 'commuted-plus-one', 'constant-wrap', 'constant-pair', 'keep-true', 'keep-false', 'direct-true', 'direct-false', 'condition-copy', 'entry-prefix'):
            cases.append(fixture(name, storage))
        cases += [fixture(storage=storage, seed=20261005+i) for i in range(6)]
    for name, storage in (('cross-cell-swap', 'Local'), ('serial-cross-cell', 'Local'), ('old-local-snapshot', 'Local'), ('old-temp-snapshot', 'Temp'), ('bool-pair', 'Mixed'), ('real-phi', 'Temp')):
        cases.append(fixture(name, storage))
    cases += [fixture('real-phi', 'Temp', seed=20261105+i) for i in range(4)]
    for name in ('third-temp-escape', 'third-local-escape', 'call', 'division', 'unary', 'multiply', 'double-increment', 'undefined-source', 'bool-increment', 'one-output', 'duplicate-successor', 'extra-predecessor', 'shared-chain', 'cycle', 'dead-call', 'dead-empty-return', 'reachable-empty-return', 'dead-nonempty-return', 'dead-malformed-return'):
        cases.append(fixture(name))
    cases += [fixture(chain=8), fixture(chain=9), fixture(padding=126), fixture(padding=127)]
    inputs = [[cond, *row] for cond in (0, 1) for row in ((0, 1, 2, 3), (11, 22, 33, 44), (-2**63, 2**63-1, -1, 0), (2**63-1, -2**63, 7, -7), (-5, -5, -5, -5))]
    support = ['@xu/types', '', Path(__file__).with_name('mir_select_pair_test.xu').read_text().split('\n', 1)[1]]
    main_src = ['@main', '#xu/types']
    expected, records = [], []
    def emit(call, val): main_src.append(' println('+call+')'); expected.append(str(int(val)))
    for cid, c in enumerate(cases):
        first = len(expected)+1; support += emit_fixture(c, cid)
        main_src += [f'fn dump_select_{cid}() {{', f' m := types.select_fixture_{cid}()', ' facts := types.new_mir_value_facts(&m, 0)',
                     f' mut p := types.new_mir_select_pair_plan(&m, 0, &facts, {c["from_"]}, {c["join"]})']
        emit('m.fns.len', 1)
        emit('types.mir_select_pair_field(&p, 0)', c['from_'] if c['accepted'] else -1)
        if c['accepted']:
            fields = [c['from_'], c['join'], c['blocks'][c['from_']]['a'], len(c['locals']), len(c['types']), 0]
            for index, val in enumerate(fields): emit(f'types.mir_select_pair_field(&p, {index})', val)
            for output, (kind, cell) in enumerate(c['outputs']):
                ty = c['locals'][cell] if kind == 1 else c['types'][cell]
                for lane, val in enumerate((kind, cell, ty)): emit(f'types.mir_select_pair_output(&p, {output}, {lane})', val)
            for arm in (0, 1):
                expressions, path, touched = edge_symbols(c, arm)
                for output, exp in enumerate(expressions):
                    for lane, val in enumerate(exp): emit(f'types.mir_select_pair_source(&p, {output}, {arm}, {lane})', val)
                emit(f'types.mir_select_pair_block_count(&p, {arm})', len(path))
                if not c['phis']:
                    for index, bi in enumerate(path): emit(f'types.mir_select_pair_block(&p, {arm}, {index})', bi)
                    for kind, count in ((1, len(c['locals'])), (2, len(c['types']))):
                        for cell in range(count): emit(f'types.mir_select_pair_touched(&p, {arm}, {kind}, {cell})', touched[cell + (len(c['locals']) if kind == 2 else 0)])
            main_src += [f' discovered := types.new_mir_select_pair_plan_discover(&m, 0, &facts, {c["from_"]})']
            emit('types.mir_select_pair_field(&discovered, 1)', c['join'])
            for values in inputs:
                expected_values = execute(c, values)
                mapped = [0]*len(c['locals'])
                for old, at in enumerate(c['input_map']): mapped[at] = values[old]
                main_src += [' if true {', ' input := ['+', '.join(xu_int(v) for v in mapped)+']',
                             f' actual := types.select_execute_actual(&m, 0, &input, {c["outputs"][0][0]}, {c["outputs"][0][1]}, {c["outputs"][1][0]}, {c["outputs"][1][1]})',
                             ' selected := types.select_execute_plan(&m, 0, &p, &input)']
                for at, val in enumerate(expected_values):
                    emit(f'actual[{at}]', val); emit(f'selected[{at}]', val)
                main_src += [' }']
        else:
            for field in range(6): emit(f'types.mir_select_pair_field(&p, {field})', -1)
            main_src += [' p.reason = 0']; emit('types.mir_select_pair_field(&p, 0)', -1)
        for call in ('types.mir_select_pair_field(&p, -1)', 'types.mir_select_pair_field(&p, 6)',
                     'types.mir_select_pair_output(&p, 2, 0)', 'types.mir_select_pair_output(&p, 0, 3)',
                     'types.mir_select_pair_source(&p, 0, 2, 0)', 'types.mir_select_pair_source(&p, 0, 0, 4)',
                     'types.mir_select_pair_block_count(&p, 2)', 'types.mir_select_pair_block(&p, 0, 999)',
                     'types.mir_select_pair_touched(&p, 0, 2, 999)'):
            emit(call, -1)
        main_src += ['}']
        records.append(dict(name=c['name']+'-'+str(cid), accepted=c['accepted'], graph=c, first_line=first, last_line=len(expected), semantic_runs=len(inputs) if c['accepted'] else 0))
    main_src += ['fn main() int { argv := args()', ' if argv.len > 1 && argv[1] == "baseline" { << 0 }'] + [f' dump_select_{cid}()' for cid in range(len(cases))] + [' << 0', '}']
    for name, content in (('support.xu', support), ('main.xu', main_src), ('expected.txt', expected)):
        (out/name).write_text('\n'.join(content)+'\n')
    (out/'oracle.json').write_text(json.dumps(dict(cases=records, output_lines=len(expected), semantic_runs=sum(c['semantic_runs'] for c in records),
        scope='General typed simultaneous pair selection vs independent original sequential MIR/Phi interpretation; no emitter or runtime gain claim.'), indent=2)+'\n')
    print(f'generated {len(cases)} cases, {len(expected)} golden lines')


if __name__ == '__main__':
    main()
