#!/usr/bin/env python3
"""Audit selected homes and execute actual ARM64 pair instruction words."""
from pathlib import Path
import argparse
import copy
import hashlib
import json
import os
import shutil
import struct
import subprocess
import tempfile

import generate_mir_select_pair_oracle as oracle

ROOT = Path(__file__).resolve().parents[1]
MASK = (1 << 64) - 1
PHYS = [8, 9, 10, 11, 12, 13, 14, 15, 19, 20, 21, 22, 23, 24, 0, 29, 31, 30]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def fixtures():
    cases = [oracle.fixture(storage=k) for k in ('Local', 'Temp', 'Mixed')]
    for c in cases:
        c['bool_scratch_reuse'] = True
    pressure = oracle.fixture(storage='Temp')
    pressure['name'] = 'seven-live-through-pressure'
    pressure['blocks'][0]['es'] += [oracle.ins(1, t, -4) for t in range(14, 21)]
    pressure['blocks'][3]['es'] += [oracle.ins(4, 23, 1, 23, t) for t in range(14, 21)]
    cases.append(pressure)
    cases += [oracle.fixture(n, k) for n, k in (
        ('wrap-plus-one', 'Temp'), ('commuted-plus-one', 'Mixed'),
        ('constant-wrap', 'Local'), ('constant-pair', 'Temp'),
        ('cross-cell-swap', 'Local'), ('old-temp-snapshot', 'Temp'),
        ('condition-copy', 'Temp'), ('real-phi', 'Temp'),
        ('direct-true', 'Mixed'), ('bool-pair', 'Mixed'))]
    for name in ('load-local-witness', 'stale-local-witness', 'stale-temp-witness',
                 'store-local-witness', 'store-temp-redefined', 'cross-block-witness', 'repeated-local-witness'):
        c = oracle.fixture(storage='Local')
        c['name'] = name
        for arm, cells in ((1, (1,1) if name == 'repeated-local-witness' else (1,2)),
                           (2, (2,2) if name == 'repeated-local-witness' else (3,4))):
            c['blocks'][arm]['es'] = [oracle.ins(2, 11, cells[0]), oracle.ins(2, 12, cells[1]),
                                     oracle.ins(3, 5, 11), oracle.ins(3, 6, 12)]
        if name == 'stale-local-witness':
            c['blocks'][0]['es'].append(oracle.ins(3, 1, -4))
        if name == 'stale-temp-witness':
            c['blocks'][0]['es'].append(oracle.ins(1, 1, -4))
        if name in ('store-local-witness', 'store-temp-redefined'):
            c['blocks'][0]['es'] += [oracle.ins(4, 7, 1, 2, -3), oracle.ins(3, 1, 7)]
            if name == 'store-temp-redefined':
                c['blocks'][0]['es'].append(oracle.ins(1, 7, -4))
        if name == 'cross-block-witness':
            c['from_'] = len(c['blocks'])
            c['blocks'].append(oracle.block([], 2, 0, 1, 2))
            c['blocks'][0].update(tk=1, a=c['from_'], b=-1, c=-1)
        cases.append(c)
    for name in ('scratch-dead-before', 'scratch-defined-after'):
        c = oracle.fixture(storage='Local')
        c['name'] = name
        # A genuine seven-value clique has enough pressure to exercise VM6/7
        # outside the selected terminator, even with deterministic coloring.
        clique = [oracle.ins(1, t, -4) for t in range(7, 14)]
        clique += [oracle.ins(4, 14, 1, 7, 8)]
        clique += [oracle.ins(4, 14, 1, 14, t) for t in range(9, 14)]
        if name == 'scratch-dead-before':
            c['blocks'][0]['es'] = clique + c['blocks'][0]['es']
        else:
            c['blocks'][3]['es'] += clique + [oracle.ins(4, 23, 1, 23, 14)]
        c['scratch_reuse'] = [7, 8]
        cases.append(c)
    arm_only = oracle.fixture(storage='Local')
    arm_only['name'] = 'scratch-arm-only-live'
    arm_only['blocks'][0]['es'].append(oracle.ins(1, 14, -4))
    arm_only['blocks'][1]['es'].insert(0, oracle.ins(1, 7, 14))
    # This use is dead at join but remains in OUT[from]. It is not a
    # selected source or witness, so only the independent CFG check sees it.
    arm_only['scratch_guard'] = 14
    cases.append(arm_only)
    live_bool = oracle.fixture(storage='Local')
    live_bool['name'] = 'scratch-bool-live-through'
    live_bool['types'][7] = 2
    live_bool['blocks'][3]['es'].append(oracle.ins(1, 7, 0))
    live_bool['bool_live_through'] = True
    cases.append(live_bool)
    for storage in ('Temp', 'Local'):
        c = oracle.fixture(storage=storage)
        c['name'] = 'repeated-base-increment-' + storage
        if storage == 'Temp':
            c['blocks'][1]['es'] = [oracle.ins(4, 11, 1, 1, -3), oracle.ins(1, 5, 11), oracle.ins(1, 6, 2)]
            c['blocks'][2]['es'] = [oracle.ins(4, 11, 1, 2, -3), oracle.ins(1, 5, 11), oracle.ins(1, 6, 1)]
        else:
            for arm, cells in ((1, (1, 2)), (2, (2, 1))):
                c['blocks'][arm]['es'] = [oracle.ins(2, 11, cells[0]), oracle.ins(4, 12, 1, 11, -3),
                                         oracle.ins(3, 5, 12), oracle.ins(2, 13, cells[1]), oracle.ins(3, 6, 13)]
        cases.append(c)
    one = oracle.fixture(storage='Local')
    one['name'] = 'one-local-base-increments'
    one['blocks'][1]['es'] = [oracle.ins(2, 11, 1), oracle.ins(4, 12, 1, 11, -3),
                            oracle.ins(3, 5, 12), oracle.ins(3, 6, 11)]
    one['blocks'][2]['es'] = [oracle.ins(2, 11, 1), oracle.ins(4, 12, 1, 11, -3),
                            oracle.ins(3, 5, 11), oracle.ins(3, 6, 12)]
    cases.append(one)
    constant = oracle.fixture('constant-pair', 'Temp')
    constant['name'] = 'repeated-constant-base-increments'
    constant['blocks'][1]['es'] = [oracle.ins(4, 11, 1, -5, -3), oracle.ins(1, 5, 11), oracle.ins(1, 6, -6)]
    constant['blocks'][2]['es'] = [oracle.ins(4, 11, 1, -6, -3), oracle.ins(1, 5, 11), oracle.ins(1, 6, -5)]
    cases.append(constant)
    distinct = oracle.fixture(storage='Mixed')
    distinct['name'] = 'same-home-distinct-canonical-kind'
    # Local1 has the same prefix value and fixed witness home as Temp1. Their
    # canonical identities still differ: equality of bound homes is not the
    # authority for copying a snapshot, even when the bindings are valid.
    distinct['blocks'][1]['es'] = [oracle.ins(2, 11, 1), oracle.ins(3, 5, 11),
                                 oracle.ins(4, 12, 1, 1, -3), oracle.ins(1, 6, 12)]
    distinct['blocks'][2]['es'] = [oracle.ins(4, 12, 1, 1, -3), oracle.ins(3, 5, 12),
                                 oracle.ins(2, 11, 1), oracle.ins(1, 6, 11)]
    cases.append(distinct)
    typed = oracle.fixture('bool-pair', 'Mixed')
    typed['name'] = 'same-constant-word-distinct-type'
    typed['locals'][7] = typed['types'][21] = 1
    typed['blocks'][0]['es'][-2:] = [oracle.ins(3, 7, -2), oracle.ins(1, 18, -2)]
    typed['blocks'][1]['es'] = [oracle.ins(3, 7, -2), oracle.ins(1, 18, -3)]
    typed['blocks'][2]['es'] = [oracle.ins(3, 7, -3), oracle.ins(1, 18, -2)]
    cases.append(typed)
    witnesses = copy.deepcopy(one)
    witnesses['name'] = 'two-legitimate-local-witnesses'
    witnesses['blocks'][0]['es'].append(oracle.ins(2, 7, 1))
    witnesses['multi_witnesses'] = True
    cases.append(witnesses)
    return cases


def cfg_live_out(c):
    """Independent set-based CFG analysis, with Phi uses on their own edges.

    The product uses dense bit cells and its MIR operand reader. This oracle
    reads the fixture's semantic instructions and solves set equations; it
    does not inspect allocator flags, homes or the edge matrix.
    """
    uses, defs, successors = [], [], []
    for bi, block in enumerate(c['blocks']):
        used, defined = set(), set()
        defined.update(d for d, _ in c['phis'].get(bi, []))
        for e in block['es']:
            k, a, b = e['k'], e['a'], e['b']
            operands = ([b] if k in (1, 3) else [e['c'], e['d']] if k == 4 else [])
            used.update(t for t in operands if t >= 0 and t not in defined)
            if k in (1, 2, 4):
                defined.add(a)
        if block['tk'] in (2, 3) and block['a'] >= 0 and block['a'] not in defined:
            used.add(block['a'])
        uses.append(used)
        defs.append(defined)
        successors.append([block['a']] if block['tk'] == 1 else
                          [block['b'], block['c']] if block['tk'] == 2 else [])
    live_in = [set() for _ in uses]
    live_out = [set() for _ in uses]
    while True:
        changed = False
        for bi in reversed(range(len(uses))):
            outgoing = set()
            for successor in successors[bi]:
                outgoing.update(live_in[successor])
                for _, args in c['phis'].get(successor, []):
                    if args[bi] >= 0:
                        outgoing.add(args[bi])
            incoming = uses[bi] | (outgoing - defs[bi])
            if outgoing != live_out[bi] or incoming != live_in[bi]:
                live_out[bi], live_in[bi] = outgoing, incoming
                changed = True
        if not changed:
            return live_out


def selected_scratch_live(row, c):
    outgoing = cfg_live_out(c)
    guarded = set()
    for index in range(row['count']):
        at = 5 + index * 30
        guarded.update(outgoing[row['action'][at]])
        # Bool is consumed into its non-allocatable register before snapshots.
        # Original OUT, semantic source/witness and output roles still protect
        # the same TempId when it has an additional live/data role.
        for pos in range(4):
            off = at + 9 + pos * 4
            if row['action'][off] == 2:
                guarded.add(row['action'][off + 1])
            witness = row['action'][at + 26 + pos]
            if witness >= 0:
                guarded.add(witness)
        for output in range(2):
            off = at + 3 + output * 3
            if row['action'][off] == 2:
                guarded.add(row['action'][off + 1])
    return guarded


def check_scratch_bindings(row, c):
    guarded = selected_scratch_live(row, c)
    for temp in guarded:
        assert row['temps'][temp] not in (-106, -107), (c['name'], temp, row)
    if row['mutations']:
        expected = [0] * 23
        expected[4] = int(7 not in guarded)
        expected[18] = int(7 not in guarded and
                           (c['name'] != 'seven-live-through-pressure' or 16 not in guarded))
        expected[19] = expected[20] = int(14 not in guarded)
        assert row['mutations'] == expected, (c['name'], guarded, row['mutations'], expected)
    if 'scratch_reuse' in c:
        assert not guarded.intersection(c['scratch_reuse']), (c['name'], guarded)
        if row['mode'] == 4:
            assert [row['temps'][t] for t in c['scratch_reuse']] == [-106, -107]
        if row['mode'] == 1:
            assert any(row['temps'][t] in (-106, -107) for t in range(7, 15)), row
    if 'scratch_guard' in c:
        assert c['scratch_guard'] in guarded
    if 'bool_scratch_reuse' in c:
        cond = row['action'][7]
        assert cond not in guarded
        if row['mode'] in (5, 6):
            assert row['temps'][cond] == (-106 if row['mode'] == 5 else -107)
    cond = row['action'][7]
    assert row['bool_bindings'] == [int(cond not in guarded)] * 2, (c['name'], guarded, row)
    if c.get('bool_live_through') or c['name'] == 'bool-pair':
        assert cond in guarded and row['bool_bindings'] == [0, 0]
    row['scratch_live_temps'] = sorted(guarded)


def scratch_fixture_source():
    """Typed test records built inside the existing @xu/types fixture unit."""
    return '''fn select_scratch_instr(kind int) MInstr {
 mut q := mkinstr(kind)
 if kind != 0 { q.a = 1
  q.b = 1
  q.c = -1
  q.d = 0 }
 << q
}

pub fn select_scratch_fixture(case int) Mir {
 mut m := select_fixture_0()
 mut f := mir_cfg_clone_fn(&m, 0, true)
 if case > 0 {
  mut kind := 0
  if case == 3 || case == 4 { kind = 99 }
  if case == 5 { kind = 14 }
  if case == 6 { kind = 8 }
  if case == 7 { kind = 7 }
  if case == 1 || case == 3 || case == 5 || case == 6 {
   mir_cfg_append(mut &f, 0, select_scratch_instr(kind))
  } else { f.instrs.push(select_scratch_instr(kind)) }
 }
 m.fns[0] = f
 << m
}'''


def parse_dump(text):
    rows, scratch = [], []
    lines = iter(text.splitlines())
    def number():
        return int(next(lines))
    for tag in lines:
        if tag == 'SCRATCH':
            case, kind, linked, uses_s, ncalls = [number() for _ in range(5)]
            assert next(lines) == 'ENDSCRATCH'
            scratch.append(dict(case=case, kind=kind, linked=linked,
                                uses_s=uses_s, ncalls=ncalls))
            continue
        if tag != 'CASE':
            raise ValueError('unexpected harness output ' + tag)
        case, mode, size = number(), number(), number()
        if size == 0:
            raise ValueError(f'case {case}/mode {mode}: no production collector action')
        count = number()
        action = [number() for _ in range(size)]
        valid, profitable, fixed, frame = number(), number(), number(), number()
        locals_ = [number() for _ in range(number())]
        temps = [number() for _ in range(number())]
        emitted, flags = number(), number()
        words = [number() for _ in range(number())]
        mutations = [number() for _ in range(number())]
        witnesses = [number() for _ in range(number())]
        pressure = [number() for _ in range(number())]
        bool_bindings = [number() for _ in range(number())]
        assert next(lines) == 'END'
        rows.append(dict(case=case, mode=mode, count=count, action=action,
                         valid=valid, profitable=profitable, fixed=fixed, frame=frame, locals=locals_,
                         temps=temps, emitted=emitted, flags=flags, words=words,
                         mutations=mutations, witness_mutations=witnesses, pressure_mutations=pressure,
                         bool_bindings=bool_bindings))
    return rows, scratch


def check_scratch_classifier(rows):
    """Explicit semantic expectations, independent of product whitelists.

    NoOp is harmless in a live chain and as a retired pool record. Unknown
    nonzero records and real Index/Drop operations remain scratch hazards.
    An unproven orphan Call is still counted by the existing pool policy;
    this regression does not authorize broader orphan-code admission.
    """
    expected = [(-1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 0, 0),
                (99, 1, 1, 0), (99, 0, 1, 0), (14, 1, 1, 0),
                (8, 1, 1, 0), (7, 0, 0, 1)]
    assert len(rows) == len(expected), rows
    for case, (row, want) in enumerate(zip(rows, expected)):
        assert row['case'] == case, row
        assert tuple(row[k] for k in ('kind', 'linked', 'uses_s', 'ncalls')) == want, row
    return len(rows)


def canonical_sources(row, c):
    """Recover branch-end expressions from fixture semantics, not the product."""
    true_sources = oracle.edge_symbols(c, 0)[0]
    false_sources = oracle.edge_symbols(c, 1)[0]
    expected = [source for output in range(2)
                for source in (true_sources[output], false_sources[output])]
    assert row['count'] == 1
    actual = [row['action'][14 + pos * 4:18 + pos * 4] for pos in range(4)]
    assert actual == expected, (c['name'], actual, expected)
    return expected


def binding_source_cost(row, c):
    """Count actual bound frame sources independently of the product gate.

    Every snapshot remains distinct, but a repeated semantic (kind,id,type)
    base is copied from its first snapshot before increments. Count the first
    bound read of each base, regardless of increment or home equality. Compare
    with each arm's unique original cells; constants and verified fixed homes
    do not read the frame. This is only the memory
    materialization policy, not a total instruction or spill profitability proof.
    """
    action = row['action']
    sources = canonical_sources(row, c)
    costs = []
    for index in range(row['count']):
        at = 5 + index * 30
        arms = [0, 0]
        selected = 0
        unique = [set(), set()]
        first = set()
        for output in range(2):
            for arm in range(2):
                off = at + 9 + (output * 2 + arm) * 4
                kind, cell = action[off:off+2]
                if kind == 3:
                    continue
                assert kind in (1, 2), row
                slots = row['locals' if kind == 1 else 'temps']
                assert 0 <= cell < len(slots), row
                slot = slots[cell]
                witness = action[at + 26 + output * 2 + arm]
                actual = row['temps'][witness] if witness >= 0 and row['temps'][witness] < 0 else slot
                base = tuple(sources[output * 2 + arm][:3])
                if base not in first:
                    selected += int(actual >= 0)
                    first.add(base)
                if slot >= 0:
                    assert slot < row['frame'] // 8, row
                    unique[arm].add((kind, cell))
                else:
                    assert -113 <= slot <= -102, row
        arms = [len(values) for values in unique]
        costs.append(dict(arm_frame_loads=arms, selected_frame_loads=selected,
                          profitable=selected <= min(arms)))
    return costs


def check_base_materialization(row, c):
    """Decode actual snapshot writes and their sources independently.

    The fixture's symbolic interpreter provides canonical identity. Machine
    words must retain all four distinct destinations, sample repeated bases
    from their first unincremented snapshot, and perform all increments only
    after the fourth snapshot. Physical address helpers use x17 and are not
    treated as base copies or frame data reads.
    """
    sources = canonical_sources(row, c)
    words = row['words']
    compare = words.index(0xf100001f)
    physical = [8, 9, 14, 15]
    writes = [[] for _ in physical]
    sequence, increments = [], []
    for index, word in enumerate(words[:compare]):
        dest = word & 31
        if dest not in physical:
            continue
        pos = physical.index(dest)
        if word & 0xff000000 == 0x91000000 and ((word >> 5) & 31) == dest:
            assert ((word >> 10) & 4095) == 1 and not ((word >> 22) & 1), (c['name'], word)
            increments.append((index, pos))
        else:
            writes[pos].append((index, word))
            sequence.append(pos)
    assert sequence == sorted(sequence) and set(sequence) == set(range(4)), (c['name'], row)
    assert [pos for _, pos in increments] == [pos for pos, source in enumerate(sources) if source[3]], (c['name'], row)
    assert all(index > max(i for group in writes for i, _ in group) for index, _ in increments), (c['name'], row)
    first = {}
    repeated_copies, constant_words, first_frame_loads = 0, 0, 0
    for pos, source in enumerate(sources):
        kind, cell, ty, _ = source
        base = (kind, cell, ty)
        group = [word for _, word in writes[pos]]
        if base in first:
            assert len(group) == 1 and group[0] & 0xffe0ffe0 == 0xaa0003e0, (c['name'], pos, group)
            assert ((group[0] >> 16) & 31) == physical[first[base]], (c['name'], pos, group, first)
            repeated_copies += 1
            continue
        first[base] = pos
        if kind == 3:
            assert all(word & 0xff800000 in (0xd2800000, 0xf2800000) for word in group), (c['name'], pos, group)
            value = 0
            for index, word in enumerate(group):
                shift = ((word >> 21) & 3) * 16
                bits = (word >> 5) & 65535
                assert (word & 0xff800000 == 0xd2800000) == (index == 0), (c['name'], group)
                value = (value & ~(65535 << shift)) | (bits << shift)
            assert value == cell & MASK, (c['name'], pos, value, cell)
            constant_words += len(group)
            continue
        home = row['locals' if kind == 1 else 'temps'][cell]
        witness = row['action'][31 + pos]
        if witness >= 0 and row['temps'][witness] < 0:
            home = row['temps'][witness]
        assert len(group) == 1, (c['name'], pos, group)
        if home < 0:
            assert group[0] & 0xffe0ffe0 == 0xaa0003e0 and ((group[0] >> 16) & 31) == PHYS[-100-home], (c['name'], pos, group, home)
        else:
            assert group[0] & 0xffc00000 == 0xf9400000 or group[0] & 0xffe00c00 == 0xf8400000, (c['name'], pos, group)
            first_frame_loads += 1
    if c['name'] in ('constant-pair-Temp', 'repeated-constant-base-increments'):
        # MaxInt and MinInt each appear twice. Only two distinct constants
        # are synthesized: four MOVZ/MOVK for Max and two for Min.
        assert repeated_copies == 2 and constant_words == 6, (c['name'], row)
    if c['name'] == 'same-home-distinct-canonical-kind' and row['mode'] == 1:
        assert tuple(sources[0][:3]) != tuple(sources[1][:3])
        assert ((writes[0][0][1] >> 16) & 31) == ((writes[1][0][1] >> 16) & 31)
        assert repeated_copies == 2
    if c['name'] == 'repeated-local-witness':
        if row['mode'] == 3:
            assert first_frame_loads == row['profitable'] == 1, row
        if row['mode'] in (0, 2):
            assert first_frame_loads == 2 and row['profitable'] == 0, row
    if c.get('multi_witnesses') and row['mode'] in (7, 8):
        assert row['action'][31:35] == [1, 7, 7, 7], row
        # A later fixed witness cannot eliminate the first frame read. The
        # reversed layout proves that later frame bindings add no reread.
        assert first_frame_loads == (1 if row['mode'] == 7 else 0), row
        assert repeated_copies == 3
    return dict(repeated_base_copies=repeated_copies, constant_materialization_words=constant_words,
                first_frame_loads=first_frame_loads, snapshot_destinations=physical)


def witness_candidates(c, local):
    from_ = c['from_']
    defs = [None] * len(c['types'])
    local_defs = [('entry', i) for i in range(len(c['locals']))]
    history = {}
    for point, e in enumerate(c['blocks'][from_]['es']):
        k, a, b = e['k'], e['a'], e['b']
        if k == 0:
            continue
        if k == 3:
            history[point] = (e, defs[b] if b >= 0 else None)
            local_defs[a] = point
        else:
            history[point] = (e, local_defs[b] if k == 2 else None)
            defs[a] = point
    answers = []
    for temp, point in enumerate(defs):
        if point is None or c['types'][temp] != c['locals'][local]:
            continue
        e, snapshot = history[point]
        if e['k'] == 2 and e['b'] == local and snapshot == local_defs[local]:
            answers.append(temp)
        elif isinstance(local_defs[local], int):
            store, source_def = history[local_defs[local]]
            if store['k'] == 3 and store['b'] == temp and source_def == point:
                answers.append(temp)
    return answers


def check_witnesses(row, c):
    for index in range(row['count']):
        at = 5 + index * 30
        for pos in range(4):
            kind, cell = row['action'][at + 9 + pos*4:at + 11 + pos*4]
            actual = row['action'][at + 26 + pos]
            expected = witness_candidates(c, cell) if kind == 1 else []
            if c.get('multi_witnesses') and row['mode'] in (7, 8):
                assert actual == (1 if pos == 0 else 7) and actual in expected, (c['name'], pos, actual, expected)
            else:
                assert actual == (expected[0] if expected else -1), (c['name'], pos, actual, expected)
    assert not any(row['witness_mutations']), row
    if row['mode'] == 1:
        assert row['pressure_mutations'] == [1, 0, 0, 0, 0], row


def before_join(c, inputs):
    """Independent original MIR, with simultaneous Phi assignment at join."""
    local = [None] * len(c['locals'])
    temp = [None] * len(c['types'])
    for i, value in enumerate(inputs):
        local[c['input_map'][i]] = value
    writes = []
    def value(v):
        return temp[v] if v >= 0 else c['consts'][-(v + 2)]
    def run(block):
        for e in c['blocks'][block]['es']:
            k, a, b = e['k'], e['a'], e['b']
            if k == 0:
                continue
            if k == 1:
                v = value(b)
            elif k == 2:
                v = local[b]
            elif k == 3:
                v = value(b)
                local[a] = v
                writes.append(('L', a, v))
                continue
            elif k == 4 and b == 1:
                v = oracle.wrap(value(e['c']) + value(e['d']))
            else:
                raise ValueError('unsupported oracle instruction')
            temp[a] = v
            writes.append(('T', a, v))
    bi = 0
    for _ in range(32):
        run(bi)
        if bi == c['from_']:
            break
        assert c['blocks'][bi]['tk'] == 1
        bi = c['blocks'][bi]['a']
    initial = dict(locals=local[:], temps=temp[:], writes=writes[:])
    cond = value(c['blocks'][bi]['a'])
    bi = c['blocks'][bi]['b' if cond else 'c']
    pred = c['from_']
    for _ in range(32):
        if bi == c['join']:
            phi = [(d, value(args[pred])) for d, args in c['phis'].get(bi, [])]
            for d, v in phi:
                temp[d] = v
            return initial, local, temp
        run(bi)
        pred, bi = bi, c['blocks'][bi]['a']
    raise ValueError('oracle did not reach join')


def execute_words(row, c, inputs):
    initial, expected_local, expected_temp = before_join(c, inputs)
    regs, mem = [0] * 32, {}
    regs[29] = 0x1000000
    def put(kind, cell, value):
        slot = row['locals' if kind == 'L' else 'temps'][cell]
        if -113 <= slot <= -102:
            regs[PHYS[-100 - slot]] = value & MASK
        elif 0 <= slot < (1 << 50):
            mem[regs[29] - 8 * (slot + 1)] = value & MASK
    for cell, value in enumerate(initial['locals']):
        if value is not None:
            put('L', cell, value)
    for kind, cell, value in initial['writes']:
        put(kind, cell, value)
    zero = False
    def read(reg):
        return 0 if reg == 31 else regs[reg]
    for w in row['words']:
        rd, rn, rm = w & 31, (w >> 5) & 31, (w >> 16) & 31
        if w & 0xfc000000 == 0x14000000:  # final unpatched direct join branch
            break
        if w & 0xffe0ffe0 == 0xaa0003e0:  # MOV register / ORR XZR
            regs[rd] = read(rm)
        elif w & 0xff800000 in (0xd2800000, 0xf2800000, 0x92800000):
            shift = ((w >> 21) & 3) * 16
            imm = ((w >> 5) & 65535) << shift
            op = w & 0xff800000
            regs[rd] = ((~imm) & MASK if op == 0x92800000 else imm if op == 0xd2800000
                        else (regs[rd] & ~(65535 << shift)) | imm)
        elif w & 0xff000000 in (0x91000000, 0xd1000000, 0xf1000000):
            imm = ((w >> 10) & 4095) << (12 if (w >> 22) & 1 else 0)
            op = w & 0xff000000
            result = (read(rn) + imm if op == 0x91000000 else read(rn) - imm) & MASK
            if op == 0xf1000000:
                zero = result == 0
            if rd != 31:
                regs[rd] = result
        elif w & 0xffe00c00 == 0x9a800000:
            assert (w >> 12) & 15 == 1  # own NE condition
            regs[rd] = read(rn if not zero else rm)
        elif w & 0xffc00000 in (0xf9400000, 0xf9000000):
            addr = read(rn) + (((w >> 10) & 4095) * 8)
            if w & 0xffc00000 == 0xf9400000:
                regs[rd] = mem[addr]
            else:
                mem[addr] = read(rd)
        elif w & 0xffe00c00 in (0xf8400000, 0xf8000000):
            offset = (w >> 12) & 511
            if offset >= 256:
                offset -= 512
            addr = read(rn) + offset
            if w & 0xffe00c00 == 0xf8400000:
                regs[rd] = mem[addr]
            else:
                mem[addr] = read(rd)
        else:
            raise ValueError('unexpected selected instruction ' + hex(w))
    for output in range(2):
        off = 5 + 3 + output * 3
        kind, cell = row['action'][off:off+2]
        slot = row['locals' if kind == 1 else 'temps'][cell]
        actual = (regs[PHYS[-100-slot]] if slot < 0 else mem[regs[29]-8*(slot+1)])
        expected = (expected_local if kind == 1 else expected_temp)[cell]
        assert oracle.wrap(actual) == expected, (c['name'], row['mode'], inputs, output, actual, expected)
    # Seven independent values must survive the newly introduced scratch.
    if c['name'] == 'seven-live-through-pressure':
        for cell in range(14, 21):
            slot = row['temps'][cell]
            actual = regs[PHYS[-100-slot]] if slot < 0 else mem[regs[29]-8*(slot+1)]
            assert oracle.wrap(actual) == initial['temps'][cell]
    if c.get('bool_live_through'):
        cell = c['blocks'][c['from_']]['a']
        slot = row['temps'][cell]
        actual = regs[PHYS[-100-slot]] if slot < 0 else mem[regs[29]-8*(slot+1)]
        assert oracle.wrap(actual) == initial['temps'][cell]


def check_cli_source(source, xu, data, modes):
    fixture = ROOT/'tests/drivers/select_pair_source_witness.xu'
    expected = ''.join(str(v)+'\n' for k in range(5) for v in (
        ((k+1)*11+1)*31+(k+1)*11, (k+2)*11*32+1,
        ((k+1)*11+1)*31+(k+3)*11, (k+2)*11*32+1)).encode()
    shutil.copy2(fixture, data/'cli-source.xu')
    rows = []
    for mode in modes.split(','):
        binary = data/('cli-'+mode)
        built = subprocess.run([str(source/'scripts/run_product_compiler.sh'), str(xu), 'build',
                                '-'+mode, '--timings', str(fixture), '-o', str(binary.resolve())],
                               cwd=source, capture_output=True, timeout=120)
        (data/('cli-'+mode+'.build.log')).write_bytes(built.stderr)
        assert built.returncode == 0, built.stderr.decode()
        run = subprocess.run([str(binary.resolve())], capture_output=True, timeout=20)
        assert run.returncode == 0 and not run.stderr and run.stdout == expected
        raw = binary.read_bytes()
        words = struct.unpack('<'+'I'*(len(raw)//4), raw[:len(raw)//4*4])
        pairs = [i for i in range(len(words)-2) if words[i] == 0xf100001f
                 and words[i+1] == 0x9a891108 and words[i+2] == 0x9a8f11ce]
        if mode == 'O3':
            assert len(pairs) == 2 and 'try=2 vreg=2' in built.stderr.decode()
            # Bool materialization, four register snapshots and then the two
            # wrapping increments precede each independently owned CMP.
            for index in pairs:
                snapshots = words[index-6:index-2]
                assert len(snapshots) == 4
                assert [w & 31 for w in snapshots] == [8, 9, 14, 15]
                assert all(w & 0xffe0ffe0 == 0xaa0003e0 for w in snapshots)
        rows.append(dict(mode=mode, two_csel_offsets=[i*4 for i in pairs],
                         binary_sha256=sha(binary), stdout_sha256=hashlib.sha256(run.stdout).hexdigest()))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu', type=Path, required=True)
    ap.add_argument('--source-root', type=Path, default=ROOT)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--modes', default='O0,O3')
    args = ap.parse_args()
    source, xu = args.source_root.resolve(), args.xu.resolve()
    identity = sha(xu)
    source_hashes = {str(p.relative_to(source)): sha(p) for p in (source/'src').rglob('*') if p.is_file()}
    tests = [Path(__file__), ROOT/'tests/select_pair_backend_harness.xu', ROOT/'tests/generate_mir_select_pair_oracle.py', ROOT/'tests/mir_select_pair_test.xu', ROOT/'tests/drivers/select_pair_source_witness.xu']
    test_hashes = {str(p.relative_to(ROOT)): sha(p) for p in tests}
    cases, reports = fixtures(), []
    data = args.out.with_suffix('')
    data.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='xu-select-backend-') as td:
        work = Path(td)
        shutil.copytree(source/'src', work/'src')
        shutil.copytree(source/'scripts', work/'scripts')
        support = ['@xu/types', (ROOT/'tests/mir_select_pair_test.xu').read_text().split('\n', 1)[1]]
        for cid, c in enumerate(cases):
            support += oracle.emit_fixture(c, cid)
        support.append(scratch_fixture_source())
        (work/'src/xu/types/select_backend_test.xu').write_text('\n'.join(support)+'\n')
        harness = (ROOT/'tests/select_pair_backend_harness.xu').read_text().split('#xu/types\n', 1)[1]
        # Use the product's explicit zero initializer for the large owner;
        # Assembler{} alone is intentionally outside Xu's authoring subset.
        driver = (work/'src/cmd/compile/driver_build.xu').read_text()
        begin = driver.index('mut a := Assembler{')
        end = driver.index('\n    }', begin) + len('\n    }')
        harness = harness.replace('mut a := Assembler{}', driver[begin:end])
        entry = work/'src/cmd/compile/driver_entry.xu'
        entry.write_text(entry.read_text().replace('fn main() int {', 'fn backend_unused_cli_main() int {'))
        main_src = (work/'src/cmd/compile/main.xu').read_text() + harness + '\nfn main() int {\n'
        for cid, c in enumerate(cases):
            main_src += f' if true {{ m := types.select_fixture_{cid}()\n'
            for mode in range(3):
                main_src += f' select_backend_dump(&m, {cid}, {mode}, {c["from_"]})\n'
            if c['name'] == 'repeated-local-witness':
                main_src += f' select_backend_dump(&m, {cid}, 3, {c["from_"]})\n'
            if 'scratch_reuse' in c:
                main_src += f' select_backend_dump(&m, {cid}, 4, {c["from_"]})\n'
            if 'bool_scratch_reuse' in c:
                for layout in (5, 6):
                    main_src += f' select_backend_dump(&m, {cid}, {layout}, {c["from_"]})\n'
            if c.get('multi_witnesses'):
                for layout in (7, 8):
                    main_src += f' select_backend_dump(&m, {cid}, {layout}, {c["from_"]})\n'
            main_src += ' }\n'
        main_src += ' select_backend_scratch_dump()\n << 0\n}\n'
        (work/'src/cmd/compile/main.xu').write_text(main_src)
        shutil.copy2(work/'src/cmd/compile/main.xu', data/'main.xu')
        shutil.copy2(work/'src/xu/types/select_backend_test.xu', data/'support.xu')
        srcs = [work/'src/cmd/compile/main.xu'] + sorted(p for p in (work/'src/cmd/compile').glob('*.xu') if p.name != 'main.xu')
        for mode in args.modes.split(','):
            assert mode in ('O0', 'O3')
            binary = data/mode
            built = subprocess.run([str(work/'scripts/run_product_compiler.sh'), str(xu), 'build', '-'+mode, *map(str, srcs), '-o', str(binary.resolve())], cwd=work, capture_output=True, timeout=300)
            (data/(mode+'.build.log')).write_bytes(built.stderr)
            assert built.returncode == 0, built.stderr.decode()
            run = subprocess.run([str(binary.resolve())], capture_output=True, timeout=90)
            (data/(mode+'.stdout')).write_bytes(run.stdout)
            assert run.returncode == 0 and not run.stderr, run.stderr.decode()
            rows, scratch = parse_dump(run.stdout.decode())
            assert len(rows) == len(cases) * 3 + 9 + 2 * sum(c.get('multi_witnesses', False) for c in cases)
            scratch_checks = check_scratch_classifier(scratch)
            executions = 0
            profitable = 0
            for row in rows:
                assert row['count'] == row['valid'] == row['emitted'] == 1 and row['flags'] == -1, row
                assert row['fixed'] == (1 if row['mode'] in (1,3,4,5,6,7,8) else 0), row
                check_scratch_bindings(row, cases[row['case']])
                check_witnesses(row, cases[row['case']])
                c = cases[row['case']]
                costs = binding_source_cost(row, c)
                expected_profit = all(cost['profitable'] for cost in costs)
                assert row['profitable'] == int(expected_profit), (row, costs)
                row['binding_source_cost'] = costs
                row['base_materialization'] = check_base_materialization(row, c)
                profitable += int(expected_profit)
                words = row['words']
                sels = [i for i, w in enumerate(words) if w & 0xffe00c00 == 0x9a800000]
                assert len(sels) == 2 and sels[1] == sels[0]+1 and words[sels[0]-1] == 0xf100001f
                stores = [i for i, w in enumerate(words) if w & 0xffc00000 == 0xf9000000 or w & 0xffe00c00 == 0xf8000000]
                assert all(i > sels[-1] for i in stores)
                # Cross-check the slot oracle against the actual encoder words,
                # including large-frame address helpers and the Bool load.
                loads = sum(w & 0xffc00000 == 0xf9400000 or
                            w & 0xffe00c00 == 0xf8400000 for w in words)
                condition = row['action'][5 + 2]
                condition_load = int(row['temps'][condition] >= 0)
                assert loads == costs[0]['selected_frame_loads'] + condition_load, row
                if row['mode'] == 2:
                    assert any(((w >> 5) & 31) == 17 and (w & 0xffc00000 in (0xf9400000, 0xf9000000) or w & 0xffe00c00 in (0xf8400000, 0xf8000000)) for w in words)
                for cond in (0, 1, -1, 2, -2**63):
                    for values in ((11,22,33,44), (-2**63,2**63-1,-1,0), (2**63-1,-2**63,7,-7)):
                        execute_words(row, c, [cond, *values])
                        executions += 1
            assert 0 < profitable < len(rows), (mode, profitable, len(rows))
            reports.append(dict(mode=mode, rows=rows, scratch_classifier=scratch, scratch_predicate_checks=scratch_checks, actual_instruction_executions=executions, binary_sha256=sha(binary), mutations_rejected=sum(sum(v == 0 for v in r['mutations']) + len(r['witness_mutations']) for r in rows), mutations_accepted=sum(sum(v == 1 for v in r['mutations']) for r in rows), pressure_predicate_checks=sum(len(r['pressure_mutations']) for r in rows), profitability_checks=len(rows), profitable_bindings=profitable, declined_bindings=len(rows)-profitable))
    cli_sources = check_cli_source(source, xu, data, args.modes)
    assert sha(xu) == identity and source_hashes == {str(p.relative_to(source)): sha(p) for p in (source/'src').rglob('*') if p.is_file()}
    assert test_hashes == {str(p.relative_to(ROOT)): sha(p) for p in tests}
    args.out.write_text(json.dumps(dict(status='PASS', compiler_sha256=identity, source_sha256=source_hashes, test_sha256=test_hashes, cli_source_witness=cli_sources, cases=len(cases), rows=reports, scope='Actual direct-MIR selected planner/frame binding and actual ARM64 word execution; independent bound-frame-source cost policy checked separately from resource legality. Canonical bases reconstructed by the fixture semantic interpreter, with actual snapshot MOV sources, deferred increments, constant materialization and first-base frame loads checked from encoded words. Identical homes and identical constant words with differing kind or type do not authorize base copies. Direct emission retains valid cost-declined actions and does not imply production selection or a CLI RA home hit; Same-block LoadLocal/StoreLocal witnesses checked by an independent sequential prefix-version oracle; invalid witness records are rejected. Added spills, frame growth and callee-save pairs checked separately against ordinary Frame records; no total instruction profitability claim. Real scratch classifier distinguishes scalar/NoOp records from unknown nonzero and Index/Drop hazards and preserves unproven orphan Call policy.'), indent=2)+'\n')
    print('PASS',len(cases),'cases,',sum(len(report['rows']) for report in reports),'actual layouts across',len(reports),'compiler modes; selected words, corruption, canonical bases, bound-source cost and 8 scratch predicates per mode')


if __name__ == '__main__':
    main()
