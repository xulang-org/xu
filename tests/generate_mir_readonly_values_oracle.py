#!/usr/bin/env python3
"""Independent sets of reaching definitions for exact-point descriptor roots."""
from pathlib import Path
import argparse
import copy
import json
import random

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out-dir', required=True, type=Path)
out = parser.parse_args().out_dir
out.mkdir(parents=True, exist_ok=True)

def ins(k, a=0, b=0, c=0, d=0, **kw):
    return dict(k=k, a=a, b=b, c=c, d=d, **kw)

def block(es=(), tk=3, a=-1, b=-1, c=-1):
    return dict(es=list(es), tk=tk, a=a, b=b, c=c)

def case(name, blocks, reason=0, **kw):
    return dict(name=name, blocks=blocks, reason=reason,
                locals=kw.pop('locals', [1200, 1200, 1]),
                temps=kw.pop('temps', [1200, 1200, 200, 1, 1, 2]), **kw)

base = [block([ins(2, 0, 0), ins(26, 2, 0, 0, 3),
               ins(26, 3, 0, 8, 1), ins(14, 4, 2, -2, 8)])]
cases = [case('descriptor-and-length', copy.deepcopy(base))]
cases.append(case('renumbered-array-type-table', copy.deepcopy(base), arrays=2,
                  locals=[1201,1201,1], temps=[1201,1201,201,1,1,2]))
x = copy.deepcopy(base)
x[0]['es'].insert(2,ins(1,6,2))
x[0]['es'][-1]['b']=6
cases.append(case('copied-descriptor',x,temps=[1200,1200,200,1,1,2,200]))
x = copy.deepcopy(base)
x[0]['es'].insert(1,ins(2,1,1))
x[0]['es'].insert(2,ins(1,0,1))
cases.append(case('typed-reference-copy-mismatch',x,reason=5,arrays=2,
                  locals=[1200,1201,1],temps=[1200,1201,200,1,1,2]))
x = copy.deepcopy(base)
x[0]['es'][-1]['b'] = 1073741824
cases.append(case('direct-local-reference-index', x))
x = copy.deepcopy(base)
for e in x[0]['es']:
    if e['k'] == 26:
        e['k'] = 17
cases.append(case('frame-pointer-descriptor', x))
x = [block([ins(2,0,0), ins(1,1,0), ins(2,0,1),
            ins(26,2,1,0,3), ins(26,3,0,8,1), ins(14,4,2,-2,8)])]
cases.append(case('old-temp-snapshot-distinct-roots', x))
cases.append(case('cross-block-root', [block(base[0]['es'][:1], 1, 1),
                                      block(base[0]['es'][1:])]))
cases.append(case('dead-uninitialized-read', [block(), block(base[0]['es'][1:])]))
cases.append(case('dead-call-remains-barrier',[block(),block([ins(7,-1,1,-1)])],reason=5))
cases.append(case('loop-invariant-descriptor', [block(base[0]['es'][:2],1,1),
    block([ins(14,4,2,-2,8)],2,-3,1,2),block()]))
for same in (False, True):
    # Definitions on both arms differ even when the formal provenance agrees.
    # This first reader refuses that merge rather than equating dynamic values.
    cases.append(case('merge-same-root' if same else 'merge-distinct-roots',
        [block([],2,-3,1,2),block([ins(2,0,0)],1,3),
         block([ins(2,0,0 if same else 1)],1,3),
         block([ins(26,2,0,0,3),ins(14,4,2,-2,8)])], reason=10))
cases.append(case('first-iteration-uninitialized', [block([],1,1),
    block([ins(14,4,2,-2,8)],2,-3,2,3),
    block(base[0]['es'][:2],1,1),block()], reason=6))
for name, e in [
    ('pointer-write', ins(25,-2,0,8,1)),
    ('index-write', ins(20,2,-2,-2,8)),
    ('growth', ins(13,2,2,0,8)), ('opaque-call', ins(7,-1,1,-1)),
    ('address-taking', ins(16,1,0,0)), ('drop',ins(8,2)),
    ('unknown-opcode',ins(49)), ('reference-formal-rebinding',ins(3,0,1)),
    ('hidden-string-compare',ins(4,5,6,3,4,sval='str_cmp')),
]:
    x = copy.deepcopy(base)
    x[0]['es'].append(e)
    cases.append(case(name, x, reason=5))
for name, index, field, value in [
    ('length-offset',2,'c',0), ('length-width',2,'d',2),
    ('descriptor-offset',1,'c',8), ('descriptor-width',1,'d',1),
    ('element-width',3,'d',4), ('unchecked-index',3,'d',-8),
    ('scalar-pointer',2,'b',3), ('invalid-index-constant',3,'c',-9223372036854775808),
]:
    x = copy.deepcopy(base)
    x[0]['es'][index][field] = value
    cases.append(case(name, x, reason=5))
for name, changes in [
    ('fixed-array',dict(fixed_len=4)), ('byte-elements',dict(elem_bytes=1)),
    ('bool-elements',dict(elem_ty=2)), ('mutable-ref',dict(locals=[2200,2200,1],temps=[2200,2200,200,1,1,2])),
    ('nested-ref',dict(locals=[3200,3200,1],temps=[3200,3200,200,1,1,2])),
    ('nonformal-reference',dict(np=1)), ('owning-local',dict(owning=0)),
    ('bad-descriptor-slots',dict(slots={2:1})),
    ('missing-reference-array',dict(arrays=0)),
]:
    cases.append(case(name,copy.deepcopy(base),reason=3,**changes))
for count in (30,31):
    ts=[1200]*(count+1)+[200,1]
    es=[ins(2,0,0)]+[ins(1,t,t-1) for t in range(1,count+1)]
    es += [ins(26,count+1,count,0,3),ins(14,count+2,count+1,-2,8)]
    # The descriptor itself consumes one provenance step on the element read.
    cases.append(case(f'root-depth-{count}',[block(es)],reason=10,
                      temps=ts))
for count in (29,):
    ts=[1200]*(count+1)+[200,1]
    es=[ins(2,0,0)]+[ins(1,t,t-1) for t in range(1,count+1)]
    es += [ins(26,count+1,count,0,3),ins(14,count+2,count+1,-2,8)]
    cases.append(case(f'root-depth-{count}',[block(es)],temps=ts))
for count in (128,129):
    cases.append(case(f'read-budget-{count}',[block([ins(2,0,0)]+[ins(26,3,0,8,1)]*count)],reason=2 if count>128 else 0))
rng=random.Random(20261004)
for i in range(16):
    temp_map=list(range(5))
    rng.shuffle(temp_map)
    locals_=[1200,1200,1]
    if i%2:
        local_map=[1,0,2]
    else:
        local_map=[0,1,2]
    bs=copy.deepcopy(base)
    types=[0]*6
    for t,ty in enumerate([1200,1200,200,1,1]):
        types[temp_map[t]]=ty
    types[5]=2
    for e in bs[0]['es']:
        e['a']=temp_map[e['a']]
        if e['k']==2:
            e['b']=local_map[e['b']]
        else:
            e['b']=temp_map[e['b']]
    cases.append(case(f'renumbered-{i}',bs,temps=types,locals=locals_))

support=['@xu/types','']
main=['@main','#xu/types','']
expected=[]
records=[]

def emit(values):
    expected.extend(str(v) for v in values)

def successors(b):
    return [b['a']] if b['tk']==1 else list(dict.fromkeys([b['b'],b['c']])) if b['tk']==2 else []

for cid,c in enumerate(cases):
    bs=c['blocks']; nl=len(c['locals']); nt=len(c['temps']); n=nl+nt
    np=c.get('np',nl); ids=[]; instructions=[]; owners=[]
    for bi,b in enumerate(bs):
        row=list(range(len(instructions),len(instructions)+len(b['es'])))
        ids.append(row); instructions.extend(b['es']); owners.extend([bi]*len(row))
    ni=len(instructions)
    support += [f'pub fn readonly_fixture_{cid}() Mir {{','    mut m := empty_mir()',
        '    mut f := mir_fn_blank()',f'    f.nparams = {np}',
        f'    for _ in 0:{c.get("arrays",1)} {{ m.arrays.push(CArray{{elem_ty: {c.get("elem_ty",1)}, elem_bytes: {c.get("elem_bytes",8)}, fixed_len: {c.get("fixed_len",0)}}}) }}']
    for l,ty in enumerate(c['locals']):
        support += [f'    f.locals.push({ty})','    f.locals_nslots.push(1)',f'    f.locals_owning.push({str(c.get("owning")==l).lower()})']
    for t,ty in enumerate(c['temps']):
        support += [f'    f.temps.push({ty})',f'    f.temps_nslots.push({c.get("slots",{}).get(t,3 if 200<=ty<300 else 1)})']
    support += ['    f.consts.push(0)','    f.consts.push(1)']
    for b in bs:
        support += [f'    f.blocks.push(MBlock{{head: -1, tail: -1, tkind: {b["tk"]}, ta: {b["a"]}, tb: {b["b"]}, tc: {b["c"]}, line: 0}})']
    for bi,b in enumerate(bs):
        for e in b['es']:
            support += ['    if true {',f'        mut q := mkinstr({e["k"]})']
            for field in 'abcd':
                value=e[field]
                literal='0 - 9223372036854775807 - 1' if value==-9223372036854775808 else str(value)
                support.append(f'        q.{field} = {literal}')
            if 'sval' in e:
                support.append('        q.sval = '+json.dumps(e['sval']))
            support += [f'        mir_cfg_append(mut &f, {bi}, q)','    }']
    support += ['    m.fns.push(f)','    m.superseded.push(0)','    << m','}']
    # Explicit powerset lattice, including an uninitialized entry sentinel.
    reach={0}; queue=[0]
    for bi in queue:
        for to in successors(bs[bi]):
            if to not in reach:
                reach.add(to); queue.append(to)
    preds=[[bi for bi in queue if to in successors(bs[bi])] for to in range(len(bs))]
    incoming=[[set() for _ in range(n)] for _ in bs]
    outgoing=copy.deepcopy(incoming)
    for _ in range((ni+1)*len(bs)*max(1,n)+2):
        changed=False
        for bi in queue:
            new=[set().union(*(outgoing[p][cell] for p in preds[bi])) for cell in range(n)]
            if bi==0:
                for cell in range(n):
                    new[cell].add(('formal',cell) if cell<np else ('uninitialized',cell))
            last=copy.deepcopy(new)
            for ii,e in zip(ids[bi],bs[bi]['es']):
                if e['k']!=0:
                    dest=e['a'] if e['k']==3 else nl+e['a']
                    if 0<=dest<n:
                        last[dest]={('instruction',ii)}
            if new!=incoming[bi] or last!=outgoing[bi]:
                changed=True;incoming[bi]=new;outgoing[bi]=last
        if not changed:
            break
    else:
        raise AssertionError('powerset solver did not converge')
    def at(bi,point,cell):
        found=set(incoming[bi][cell])
        for ii,e in zip(ids[bi],bs[bi]['es']):
            if ii==point:
                break
            if e['k']!=0 and (e['a'] if e['k']==3 else nl+e['a'])==cell:
                found={('instruction',ii)}
        return found
    def root(bi,point,kind,cell):
        if c['reason'] or bi not in reach or kind not in (1,2) or cell<0 or cell>=(nl if kind==1 else nt):
            return -1
        flat=cell if kind==1 else nl+cell
        for _ in range(32):
            ty=c['locals'][flat] if flat<nl else c['temps'][flat-nl]
            if not (1200<=ty<1300 or 200<=ty<300):
                return -1
            defs=at(bi,point,flat)
            if len(defs)!=1:
                return -1
            tag,value=next(iter(defs))
            if tag=='formal':
                return value if value<np and 1200<=c['locals'][value]<1300 else -1
            if tag!='instruction':
                return -1
            e=instructions[value]
            if e['k']==2:
                flat=e['b']
            elif e['k']==1 or (e['k'] in (17,26) and e['c']==0 and e['d']==3):
                flat=nl+e['b']
            else:
                return -1
            bi=owners[value]; point=value
        return -1
    main += [f'fn dump_readonly_{cid}() {{','    m := types.readonly_fixture_'+str(cid)+'()',
             '    mut f := types.new_mir_readonly_value_facts(&m, 0)','    println(f.reason)']
    emit([c['reason']]); queries=[]
    for bi,b in enumerate(bs):
        for point in [*ids[bi],-1]:
            for kind in (1,2):
                count=nl if kind==1 else nt
                for cell in range(-1,count+1):
                    value=root(bi,point,kind,cell)
                    queries.append([bi,point,kind,cell,value])
                    main.append(f'    println(types.mir_readonly_value_root(&m, 0, &f, {bi}, {point}, {kind}, {cell}))')
                    emit([value])
    main += ['    f.reason = 0',
             '    println(types.mir_readonly_value_root(&m, -1, &f, 0, -1, 1, 0))',
             '    println(types.mir_readonly_value_root(&m, 0, &f, 0, -2, 1, 0))',
             '    println(types.mir_readonly_value_root(&m, 0, &f, 999, -1, 1, 0))','}']
    emit([-1,-1,-1])
    records.append(dict(name=c['name'],reason=c['reason'],queries=queries))

fixture=Path(__file__).with_name('mir_readonly_values_phi.xu').read_text()
support.append(fixture.split('\n',1)[1])
main += ['fn dump_full_loop() {','    for mode in 0:2 {',
    '        m := types.readonly_lower_bound_fixture(mode == 1)',
    '        println(m.fns.len)', '        f := types.new_mir_readonly_value_facts(&m, 0)',
    '        println(f.reason)', '        scalar := types.new_mir_value_facts(&m, 0)',
    '        println(scalar.reason)', '        mut roots := 0',
    '        for ii in 0:types.mir_nins(&m, 0) {',
    '            k := types.mir_ikind(&m, 0, ii)',
    '            if k == 14 || k == 17 || k == 26 {',
    '                bi := types.mir_value_facts_owner(&f, ii)',
    '                println(types.mir_readonly_value_root(&m, 0, &f, bi, ii, 2, types.mir_ib(&m, 0, ii)))',
    '                roots += 1','            }','        }','        println(roots)',
    '    }','}']
for _ in range(2):
    emit([1,0,3,0,0,0,3])
main += ['fn main() int {','    argv := args()','    if argv.len > 1 && argv[1] == "baseline" { << 0 }']
main += [f'    dump_readonly_{cid}()' for cid in range(len(cases))]
main += ['    dump_full_loop()','    << 0','}']
(out/'support.xu').write_text('\n'.join(support)+'\n')
(out/'main.xu').write_text('\n'.join(main)+'\n')
(out/'expected.txt').write_text('\n'.join(expected)+'\n')
(out/'oracle.json').write_text(json.dumps(dict(cases=records,output_lines=len(expected)),indent=2)+'\n')
print(f'generated {len(cases)} cases, {len(expected)} golden lines')
