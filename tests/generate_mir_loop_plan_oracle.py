#!/usr/bin/env python3
"""Canonical lower-bound plans and an independent executable MIR oracle.

The Python interpreter executes simultaneous Phi semantics. The Xu interpreter
executes the actual production Phi destruction output. Neither interpreter
consults the plan reader. Algorithm results are checked against bisect_left,
including the lower-bound interval invariant at every header visit.
"""
from pathlib import Path
import argparse
import bisect
import copy
import json
import random


def ins(k, a=0, b=0, c=0, d=0):
    return dict(k=k, a=a, b=b, c=c, d=d)


def block(es=(), tk=1, a=1, b=-1, c=-1):
    return dict(es=list(es), tk=tk, a=a, b=b, c=c)


def fixture(ssa=False, variant='plain', seed=None, chain=1, copies=0):
    bs = [block([ins(2, 0, 0), ins(2, 2, 1), ins(26, 12, 0, 8, 1),
                 ins(1, 14, -2), ins(1, 15, 12)]),
          block([] if ssa else [ins(2, 3, 2), ins(2, 4, 3)], 2, 5, 2, 5),
          block([ins(4, 6, 2, 4, 3), ins(4, 7, 18, 6, -3),
                 ins(4, 8, 1, 3, 7), ins(26, 1, 0, 0, 3),
                 ins(14, 9, 1, 8, 8), ins(4, 10, 8, 9, 2)], 2, 10, 3, 4),
          block([ins(4, 11, 1, 8, -3)], 1, 1),
          block([], 1, 1),
          block([ins(1, 13, 3)] if ssa else [ins(2, 13, 2)], 3, 13)]
    bs[1]['es'].append(ins(4, 5, 8, 3, 4))
    if not ssa:
        bs[0]['es'] += [ins(3, 2, 14), ins(3, 3, 15)]
        bs[3]['es'].append(ins(3, 2, 11))
        bs[4]['es'].append(ins(3, 3, 8))
    types = [1200, 200, 1, 1, 1, 2, 1, 1, 1, 1, 2] + [1] * 9
    locals_ = [1200, 1, 1, 1, 1]
    accept = True
    semantic = True
    if variant == 'copy-chain':
        bs[0]['es'][2:2] = [ins(1, 16, 2), ins(1, 17, 16)]
        bs[2]['es'][-1]['d'] = 17
        bs[2]['es'].insert(3, ins(1, 18, 8))
        bs[2]['es'][-2]['c'] = 18
        bs[3]['es'][0]['c'] = 18
        if not ssa:
            bs[4]['es'][0]['b'] = 18
    elif variant in ('old-needle-snapshot', 'new-needle-definition'):
        # A genuine SSA value cannot be statically redefined. Its new current
        # value has a fresh destination; the Local graph exercises real reuse.
        bs[0]['es'][2:2] = [ins(1, 16, 2), ins(1, 18 if ssa else 2, -4)]
        bs[2]['es'][-1]['d'] = 16 if variant.startswith('old') else 2
        accept = variant.startswith('old')
        semantic = accept
    elif variant == 'old-formal-needle-snapshot':
        bs[0]['es'].append(ins(3, 1, -4))
    elif variant == 'type-table-one':
        locals_[0] = types[0] = 1201
        types[1] = 201
    elif variant == 'frame-layout':
        for bb in bs:
            for e in bb['es']:
                if e['k'] == 26:
                    e['k'] = 17
    elif variant == 'tagged-local-index':
        bs[2]['es'].pop(3)
        bs[2]['es'][-2]['b'] = 1073741824
    elif variant == 'mid-local-snapshot':
        bs[2]['es'].insert(3, ins(3, 4, 8))
    elif variant == 'old-mid-snapshot':
        bs[2]['es'][3:3] = [ins(1, 16, 8), ins(1, 19 if ssa else 8, -2)]
        bs[2]['es'][-2]['c'] = 16
        bs[3]['es'][0]['c'] = 16
        if not ssa:
            bs[4]['es'][0]['b'] = 16
    elif variant == 'condition-copies':
        types[18] = types[19] = 2
        bs[1]['es'].append(ins(1, 18, 5))
        bs[1]['a'] = 18
        bs[2]['es'].append(ins(1, 19, 10))
        bs[2]['a'] = 19
    elif variant == 'extra-state-write':
        bs[3]['es'].append(ins(3, 4, -3))
        accept = False
    elif variant == 'exit-mid-use':
        bs[5]['es'] = [ins(4, 13, 1, 3, 8)]
        accept = semantic = False
    elif variant == 'initialized-mid-escape':
        bs[0]['es'].append(ins(1, 8, -2))
        bs[5]['es'] = [ins(1, 13, 8)]
        accept = semantic = False
    elif variant == 'extra-division':
        bs[2]['es'].insert(-1, ins(4, 18, 4, -3, -2))
        accept = semantic = False
    elif variant == 'shared-exit':
        bs[1]['c'] = 4
        accept = semantic = False
    elif variant == 'extra-element-read':
        bs[2]['es'].insert(-1, ins(14, 18, 1, 8, 8))
        accept = False
    elif variant == 'side-effect':
        bs[2]['es'].append(ins(7, -1, 1, -1))
        accept = semantic = False
    elif variant == 'bad-midpoint':
        bs[2]['es'][2]['b'] = 2
        accept = semantic = False
    elif variant == 'bad-update':
        bs[3]['es'][0]['d'] = -2
        accept = semantic = False
    elif variant == 'wrong-header-condition':
        types[18] = 2
        bs[1]['es'].append(ins(4, 18, 8, -2, -3))
        bs[1]['a'] = 18
        accept = semantic = False
    elif variant == 'wrong-body-condition':
        bs[2]['a'] = 5
        accept = semantic = False
    elif variant == 'reverse-difference':
        bs[2]['es'][0]['c'], bs[2]['es'][0]['d'] = 3, 4
        accept = semantic = False
    elif variant == 'wrong-shift':
        bs[2]['es'][1]['d'] = -2
        accept = semantic = False
    elif variant == 'opposite-update-arms':
        bs[2]['b'], bs[2]['c'] = 4, 3
        accept = semantic = False
    elif variant == 'extra-length-read':
        bs[2]['es'].insert(-1, ins(26, 18, 0, 8, 1))
        accept = False
    elif variant == 'state-rebind-after-mid':
        bs[2]['es'].insert(3, ins(3, 2, -2))
        accept = semantic = False
    elif variant == 'opposite-element-compare':
        bs[2]['es'][-1]['c'], bs[2]['es'][-1]['d'] = 2, 9
        accept = semantic = False
    elif variant == 'bad-exit':
        bs[5]['es'][0]['b'] = 4 if ssa else 3
        accept = semantic = False
    elif variant == 'mutable-root':
        locals_[0] = types[0] = 2200
        accept = semantic = False
    elif variant == 'dead-barrier':
        bs.append(block([ins(7, -1, 1, -1)], 3, -1))
        accept = semantic = False
    elif variant == 'post-test-latch':
        # Genuine while lowering can have an initial guard and a separate
        # latch. It stays outside the deliberately closed pre-test grammar.
        types[18] = 2
        bs[0]['es'].append(ins(4, 18, 8, 14, 15))
        bs[0].update(tk=2, a=18, b=1, c=5)
        bs[1]['es'].pop()
        bs[1].update(tk=1, a=2)
        bs[3]['a'] = bs[4]['a'] = 6
        bs.append(block([ins(2, 3, 2), ins(2, 4, 3), ins(4, 5, 8, 3, 4)], 2, 5, 1, 5))
        accept = semantic = False
    elif variant != 'plain':
        raise ValueError(variant)

    # Additional private true-edge Jump blocks carry no hidden operations.
    true_tail = 3
    true_path = [3]
    for _ in range(chain - 1):
        to = len(bs)
        bs[true_tail]['a'] = to
        bs.append(block([], 1, 1))
        true_tail = to
        true_path.append(to)
    if copies:
        bs[3]['es'] += [ins(1, 19, 8)] * copies
    if chain > 8 or len(bs[3]['es']) > 128:
        accept = False
    if chain > 1 or copies:
        semantic = accept

    # Simultaneous Phi arguments refer to predecessor edge values, not a
    # simulated sequence of production Copies.
    phis = []
    if ssa:
        phis = [(3, {0: 14, true_tail: 11, 4: 3}),
                (4, {0: 15, true_tail: 4, 4: 18 if variant == 'copy-chain' else 16 if variant == 'old-mid-snapshot' else 8})]
    tm = list(range(len(types)))
    lm = list(range(len(locals_)))
    bm = list(range(len(bs)))
    if seed is not None:
        rng = random.Random(seed)
        rng.shuffle(tm)
        formal = [0, 1]
        state = [2, 3, 4]
        rng.shuffle(formal)
        rng.shuffle(state)
        lm = formal + state
        rest = list(range(1, len(bs)))
        rng.shuffle(rest)
        bm = [0] + rest
    remapped = [None] * len(bs)
    for bi, bb in enumerate(bs):
        nb = copy.deepcopy(bb)
        if nb['tk'] == 1:
            nb['a'] = bm[nb['a']]
        elif nb['tk'] == 2:
            nb['a'] = tm[nb['a']] if nb['a'] >= 0 else nb['a']
            nb['b'], nb['c'] = bm[nb['b']], bm[nb['c']]
        elif nb['a'] >= 0:
            nb['a'] = tm[nb['a']]
        for e in nb['es']:
            k = e['k']
            if k == 0 or k == 7:
                continue
            e['a'] = lm[e['a']] if k == 3 else tm[e['a']]
            if k == 2:
                e['b'] = lm[e['b']]
            elif k in (1, 3, 17, 26) and e['b'] >= 0:
                e['b'] = tm[e['b']]
            elif k == 14:
                e['b'] = (1073741824 + lm[e['b'] - 1073741824]
                          if e['b'] >= 1073741824 else tm[e['b']])
                if e['c'] >= 0:
                    e['c'] = tm[e['c']]
            elif k == 4:
                for key in ('c', 'd'):
                    if e[key] >= 0:
                        e[key] = tm[e[key]]
        remapped[bm[bi]] = nb
    rtypes = [0] * len(types)
    rlocals = [0] * len(locals_)
    for i, ty in enumerate(types):
        rtypes[tm[i]] = ty
    for i, ty in enumerate(locals_):
        rlocals[lm[i]] = ty
    phis = [(tm[dest], {bm[p]: tm[v] for p, v in args.items()}) for dest, args in phis]
    return dict(blocks=remapped, types=rtypes, locals=rlocals, phis=phis,
                tm=tm, lm=lm, bm=bm, true_path=[bm[b] for b in true_path],
                accept=accept, semantic=semantic, ssa=ssa, variant=variant)


def wrap(x):
    return (x + 2**63) % 2**64 - 2**63


def interpret(c, values, needle):
    loc = [None] * len(c['locals'])
    tmp = [None] * len(c['types'])
    for l in range(2):
        loc[l] = ('array', l) if c['locals'][l] != 1 else needle
    consts = [0, 1, 99]
    def value(x):
        return tmp[x] if x >= 0 else consts[-x - 2]
    bi, pred = 0, -1
    truth = bisect.bisect_left(values, needle)
    for _ in range(8192):
        if bi == c['bm'][1]:
            writes = [(d, value(args[pred])) for d, args in c['phis']]
            for d, v in writes:
                tmp[d] = v
        for e in c['blocks'][bi]['es']:
            k, a, b, x, y = (e[v] for v in ('k', 'a', 'b', 'c', 'd'))
            if k == 1:
                tmp[a] = value(b)
            elif k == 2:
                tmp[a] = loc[b]
            elif k == 3:
                loc[a] = value(b)
            elif k == 4:
                vx, vy = value(x), value(y)
                tmp[a] = {1: lambda: wrap(vx + vy), 2: lambda: wrap(vx - vy),
                          18: lambda: vx >> vy, 8: lambda: int(vx < vy)}[b]()
            elif k in (17, 26):
                tmp[a] = len(values) if x == 8 else value(b)
            elif k == 14:
                index = value(x)
                assert 0 <= index < len(values), (c['variant'], values, needle, index)
                tmp[a] = values[index]
            elif k != 0:
                raise ValueError(k)
        if bi == c['bm'][1]:
            lo = tmp[c['tm'][3]] if c['ssa'] else loc[c['lm'][2]]
            hi = tmp[c['tm'][4]] if c['ssa'] else loc[c['lm'][3]]
            assert 0 <= lo <= truth <= hi <= len(values), (lo, truth, hi, values, needle)
        bb = c['blocks'][bi]
        if bb['tk'] == 3:
            result = value(bb['a'])
            assert result == truth, (result, truth, values, needle)
            return result
        pred = bi
        bi = bb['a'] if bb['tk'] == 1 else bb['b'] if value(bb['a']) else bb['c']
    raise AssertionError('nonterminating test MIR')


def xu_int(v):
    return '0 - 9223372036854775807 - 1' if v == -2**63 else str(v)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out-dir', required=True, type=Path)
    out = p.parse_args().out_dir
    out.mkdir(parents=True, exist_ok=True)
    cases = []
    for ssa in (False, True):
        for variant in ('plain', 'copy-chain', 'old-needle-snapshot', 'old-formal-needle-snapshot', 'type-table-one', 'frame-layout',
                        'tagged-local-index', 'mid-local-snapshot', 'old-mid-snapshot', 'condition-copies'):
            cases.append(fixture(ssa, variant))
        for seed in range(8):
            cases.append(fixture(ssa, seed=20261004 + seed))
        cases.append(fixture(ssa, chain=8))
    for variant in ('new-needle-definition', 'extra-state-write', 'exit-mid-use',
                    'extra-element-read', 'initialized-mid-escape', 'extra-division', 'shared-exit', 'side-effect', 'bad-midpoint', 'bad-update',
                    'opposite-element-compare', 'bad-exit', 'mutable-root', 'dead-barrier',
                    'wrong-header-condition', 'wrong-body-condition', 'reverse-difference',
                    'wrong-shift', 'opposite-update-arms', 'extra-length-read', 'state-rebind-after-mid',
                    'post-test-latch'):
        cases.append(fixture(False, variant))
    cases += [fixture(False, chain=9), fixture(False, copies=126), fixture(False, copies=127)]

    rng = random.Random(40810)
    arrays = [[], [-1], [0, 0], [-4, -4, -1, 0, 3, 3, 7],
              [-2**63, -2**63, -1, 0, 2**63 - 1]]
    arrays += [sorted(rng.randrange(-20, 21) for _ in range(n))
               for n in (3, 7, 8, 9, 15, 16, 17, 31, 32, 33, 63, 64, 65, 127, 128, 129)]
    runs = [(a, n) for a in arrays for n in (-2**63, -21, -4, -1, 0, 1, 3, 20, 21, 2**63 - 1)]
    support = ['@xu/types', '']
    support.append(Path(__file__).with_name('mir_loop_plan_phi.xu').read_text().split('\n', 1)[1])
    main_src = ['@main', '#xu/types', '']
    main_src += ['fn loop_plan_input(ai int) []int {']
    for ai, array in enumerate(arrays):
        literal = '[' + ', '.join(xu_int(v) for v in array) + ']' if array else '[]int{}'
        main_src.append(f'    if ai == {ai} {{ << {literal} }}')
    main_src += ['    << []int{}', '}']
    expected = []
    records = []
    def emit(x):
        expected.append(str(int(x)))
    for cid, c in enumerate(cases):
        first_line = len(expected) + 1
        name = ('SSA-' if c['ssa'] else 'Local-') + c['variant'] + '-' + str(cid)
        support += [f'pub fn loop_plan_fixture_{cid}() Mir {{', '    mut m := empty_mir()',
                    '    m.arrays.push(CArray{elem_ty: 1, elem_bytes: 8, fixed_len: 0})',
                    '    mut f := mir_fn_blank()', '    f.nparams = 2', '    f.ret = 1', '    f.ret_nslots = 1']
        if c['variant'] == 'type-table-one':
            support.append('    m.arrays[0] = CArray{elem_ty: 2, elem_bytes: 8, fixed_len: 0}')
            support.append('    m.arrays.push(CArray{elem_ty: 1, elem_bytes: 8, fixed_len: 0})')
        for ty in c['locals']:
            support += [f'    f.locals.push({ty})', '    f.locals_nslots.push(1)', '    f.locals_owning.push(false)']
        for ty in c['types']:
            support += [f'    f.temps.push({ty})', f'    f.temps_nslots.push({3 if 200 <= ty < 300 else 1})']
        for v in (0, 1, 99):
            support.append(f'    f.consts.push({v})')
        for b in c['blocks']:
            support.append(f'    f.blocks.push(MBlock{{head: -1, tail: -1, tkind: {b["tk"]}, ta: {b["a"]}, tb: {b["b"]}, tc: {b["c"]}, line: 0}})')
        for bi, b in enumerate(c['blocks']):
            for e in b['es']:
                support += ['    if true {', f'        mut q := mkinstr({e["k"]})']
                support += [f'        q.{key} = {xu_int(e[key])}' for key in 'abcd']
                support += [f'        mir_cfg_append(mut &f, {bi}, q)', '    }']
        if c['ssa']:
            tm, lm, bm = c['tm'], c['lm'], c['bm']
            ids = [tm[i] for i in (3, 4, 14, 15, 11, 18 if c['variant'] == 'copy-chain' else 16 if c['variant'] == 'old-mid-snapshot' else 8)] + [lm[2], lm[3]]
            bs = [bm[0], bm[1], c['true_path'][-1], bm[4]]
            support += ['    ids := [' + ', '.join(map(str, ids)) + ']',
                        '    bs := [' + ', '.join(map(str, bs)) + ']',
                        '    if !loop_plan_finish_phi(mut &f, &ids, &bs) { << m }']
        support += ['    m.fns.push(f)', '    m.superseded.push(0)', '    << m', '}']
        main_src += [f'fn dump_loop_plan_{cid}() {{', f'    m := types.loop_plan_fixture_{cid}()',
                     '    println(m.fns.len)', f'    mut p := types.new_mir_lower_bound_loop_plan(&m, 0, {c["bm"][1]})',
                     '    if p.reason == 0 { println(1) } else { println(0) }']
        emit(1); emit(c['accept'])
        # Full path roles and semantic cell roles; instruction IDs are queried
        # through MIR opcodes so production copy insertion cannot fabricate a
        # golden by depending on the elimination scheduler's instruction order.
        if c['accept']:
            bm, tm, lm = c['bm'], c['tm'], c['lm']
            fields = {0: 0, 1: bm[1], 2: bm[2], 3: bm[3], 4: bm[4], 5: bm[5],
                      6: 2 if c['ssa'] else 1, 7: tm[3] if c['ssa'] else lm[2],
                      8: 2 if c['ssa'] else 1, 9: tm[4] if c['ssa'] else lm[3],
                      10: tm[8], 11: lm[1], 12: lm[0], 13: 0 if c['variant'] == 'tagged-local-index' else 17 if c['variant'] == 'frame-layout' else 26,
                      14: -1 if c['variant'] == 'tagged-local-index' else tm[1],
                      19: c['true_path'][-1], 20: bm[4], 21: 0, 22: bm[5], 23: 0,
                      24: 2, 25: 0, 27: 3, 31: lm[0],
                      32: 17 if c['variant'] == 'frame-layout' else 26,
                      33: 1 if c['variant'] == 'tagged-local-index' else 2}
            for field, value in fields.items():
                main_src.append(f'    println(types.mir_loop_plan_field(&p, {field}))'); emit(value)
            for field, opcode in ((15, 14), (16, 17 if c['variant'] == 'frame-layout' else 26), (17, 4), (18, 4)):
                main_src.append(f'    println(types.mir_ikind(&m, 0, types.mir_loop_plan_field(&p, {field})))'); emit(opcode)
            main_src.append('    println(types.mir_ikind(&m, 0, types.mir_loop_plan_field(&p, 30)))'); emit(4)
            main_src.append('    println(types.mir_ib(&m, 0, types.mir_loop_plan_field(&p, 30)))'); emit(1)
            main_src.append('    println(types.mir_ia(&m, 0, types.mir_loop_plan_field(&p, 30)))'); emit(tm[8])
            for part, path in enumerate(([0], c['true_path'], [bm[4]], [bm[5]])):
                main_src.append(f'    println(types.mir_loop_plan_block_count(&p, {part}))'); emit(len(path))
                for index, bi in enumerate(path):
                    main_src.append(f'    println(types.mir_loop_plan_block(&p, {part}, {index}))'); emit(bi)
            kind = 2 if c['ssa'] else 1
            for state, role in ((3 if c['ssa'] else 2, 1), (4 if c['ssa'] else 3, 2)):
                cell = tm[state] if c['ssa'] else lm[state]
                main_src.append(f'    println(types.mir_loop_plan_cell_role(&p, 0, {kind}, {cell}))'); emit(role)
            for temp, role in ((6, 3), (7, 4), (8, 15 if c['variant'] == 'old-mid-snapshot' and not c['ssa'] else 5), (9, 6), (10, 11)):
                main_src.append(f'    println(types.mir_loop_plan_cell_role(&p, 1, 2, {tm[temp]}))'); emit(role)
            mid_alias = tm[18] if c['variant'] == 'copy-chain' else tm[16] if c['variant'] == 'old-mid-snapshot' else tm[8]
            if c['variant'] == 'old-mid-snapshot':
                main_src.append(f'    println(types.mir_loop_plan_cell_role(&p, 1, 2, {tm[16]}))'); emit(5)
            if c['variant'] == 'old-formal-needle-snapshot':
                main_src.append(f'    println(types.mir_loop_plan_cell_role(&p, 0, 1, {lm[1]}))'); emit(0)
                main_src.append(f'    println(types.mir_loop_plan_cell_role(&p, 0, 2, {tm[2]}))'); emit(7)
            lo_id, hi_id = (tm[3], tm[4]) if c['ssa'] else (lm[2], lm[3])
            lo_flat = len(lm) + lo_id if c['ssa'] else lo_id
            hi_flat = len(lm) + hi_id if c['ssa'] else hi_id
            # Compare ordered final edge state with simultaneous mathematical
            # updates at the branch snapshot. The SSA oracle does not predict
            # the production copy scheduler or its temporary scratch order.
            updates = [(0, lo_id, [1, len(lm) + mid_alias, 1, 1]),
                       (0, hi_id, [1, hi_flat, 0, 0]),
                       (1, lo_id, [1, lo_flat, 0, 0]),
                       (1, hi_id, [1, len(lm) + mid_alias, 0, 1])]
            for arm, cell, lanes in updates:
                for lane, value in enumerate(lanes):
                    main_src.append(f'    println(types.mir_loop_plan_edge_value(&p, {arm}, {kind}, {cell}, {lane}))'); emit(value)
            if c['semantic']:
                needles = [-2**63, -21, -4, -1, 0, 1, 3, 20, 21, 2**63 - 1]
                main_src += ['    needles := [' + ', '.join(xu_int(v) for v in needles) + ']',
                             f'    for ai in 0:{len(arrays)} {{', '        input := loop_plan_input(ai)',
                             '        for ni in 0:needles.len {',
                             '            println(types.loop_plan_interpret(&m, 0, &input, needles[ni]))',
                             '        }', '    }']
                for array, needle in runs:
                    emit(interpret(c, array, needle))
        else:
            for field in range(34):
                main_src.append(f'    println(types.mir_loop_plan_field(&p, {field}))'); emit(-1)
            main_src += ['    p.reason = 0', '    println(types.mir_loop_plan_field(&p, 1))']; emit(-1)
        if cid in (0, len(cases) - 1):
            # All storage APIs reject invalid selectors on both an accepted
            # plan and a failed plan whose public reason was reset to zero.
            calls = [
                'types.mir_loop_plan_block_count(&p, -1)',
                'types.mir_loop_plan_block_count(&p, 4)',
                'types.mir_loop_plan_block(&p, 0, -1)',
                'types.mir_loop_plan_block(&p, 99, 0)',
                'types.mir_loop_plan_block(&p, 0, 999)',
                'types.mir_loop_plan_cell_role(&p, -1, 1, 0)',
                'types.mir_loop_plan_cell_role(&p, 3, 1, 0)',
                'types.mir_loop_plan_cell_role(&p, 0, 3, 0)',
                'types.mir_loop_plan_cell_role(&p, 0, 1, -1)',
                'types.mir_loop_plan_cell_role(&p, 0, 2, 999)',
                'types.mir_loop_plan_edge_value(&p, -1, 1, 0, 0)',
                'types.mir_loop_plan_edge_value(&p, 2, 1, 0, 0)',
                'types.mir_loop_plan_edge_value(&p, 0, 1, 0, -1)',
                'types.mir_loop_plan_edge_value(&p, 0, 1, 0, 4)',
                'types.mir_loop_plan_edge_value(&p, 0, 3, 0, 0)',
                'types.mir_loop_plan_edge_value(&p, 0, 2, 999, 0)',
            ]
            for call in calls:
                main_src.append(f'    println({call})'); emit(-1)
        for bad in (-1, 99):
            main_src.append(f'    println(types.mir_loop_plan_field(&p, {bad}))'); emit(-1)
        for fi, header in ((-1, c['bm'][1]), (1, c['bm'][1]), (0, -1), (0, 999)):
            main_src += [f'    if true {{ bad := types.new_mir_lower_bound_loop_plan(&m, {fi}, {header})',
                         '        println(types.mir_loop_plan_field(&bad, 1)) }']; emit(-1)
        main_src.append('}')
        records.append(dict(name=name, accepted=c['accept'], semantic_runs=len(runs) if c['accept'] and c['semantic'] else 0,
                            first_line=first_line, last_line=len(expected), graph=c))
    main_src += ['fn main() int {', '    argv := args()', '    if argv.len > 1 && argv[1] == "baseline" { << 0 }']
    main_src += [f'    dump_loop_plan_{cid}()' for cid in range(len(cases))]
    main_src += ['    << 0', '}']
    (out / 'support.xu').write_text('\n'.join(support) + '\n')
    (out / 'main.xu').write_text('\n'.join(main_src) + '\n')
    (out / 'expected.txt').write_text('\n'.join(expected) + '\n')
    (out / 'oracle.json').write_text(json.dumps(dict(cases=records, output_lines=len(expected),
            semantic_runs=sum(r['semantic_runs'] for r in records), algorithm_oracle='bisect_left plus per-header interval invariant'), indent=2) + '\n')
    print(f'generated {len(cases)} cases, {len(expected)} golden lines')


if __name__ == '__main__':
    main()
