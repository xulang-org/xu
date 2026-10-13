#!/usr/bin/env python3
"""Independent set-of-definitions and sequential symbolic edge oracle."""
from pathlib import Path
import argparse, copy, json, random
p=argparse.ArgumentParser();p.add_argument('--out-dir',required=True,type=Path);D=p.parse_args().out_dir;D.mkdir(parents=True,exist_ok=True)
C=[11,1,22,0,9223372036854775807,-9223372036854775808]
def ins(k,a=0,b=0,c=0,d=0,**kw):return dict(k=k,a=a,b=b,c=c,d=d,**kw)
def block(es=(),tk=3,a=-1,b=-1,c=-1):return dict(es=list(es),tk=tk,a=a,b=b,c=c)
def case(name,bs,nl=2,nt=4,np=2,ret=0,reason=0,**kw):return dict(name=name,bs=bs,nl=nl,nt=nt,np=np,ret=ret,reason=reason,**kw)
entry=[ins(2,0,0),ins(2,1,1)]
base=[block(entry,2,-3,1,2),block([ins(1,0,1),ins(1,1,0)],1,3),block([],1,3),block()]
cases=[case('serial-copy',copy.deepcopy(base))]
x=copy.deepcopy(base);x[1]['es']=[ins(1,2,1),ins(1,1,0),ins(1,0,2)];cases.append(case('scratch-swap',x))
x=copy.deepcopy(base);x[1]['es']=[ins(2,2,0),ins(3,0,1),ins(1,3,2)];cases.append(case('old-local-snapshot',x))
x=copy.deepcopy(base);x[1]['es']=[ins(1,0,-2),ins(1,0,-4),ins(1,3,0)];cases.append(case('repeated-temp',x))
x=copy.deepcopy(base);x[1]['es']=[ins(4,2,1,0,-3),ins(1,3,2)];cases.append(case('wrap-plus-one',x))
x=copy.deepcopy(base);x[1]['es']=[ins(4,2,1,-3,0)];cases.append(case('commuted-plus-one',x))
x=copy.deepcopy(base);x[1]['es']=[ins(4,2,1,-6,-3)];cases.append(case('constant-max-plus-one',x))
x=copy.deepcopy(base);x[1]['es']=[ins(4,2,1,0,-3),ins(4,3,1,2,-3)];cases.append(case('double-increment',x))
x=copy.deepcopy(base);x[1]['es']=[ins(4,2,3,0,-3)];cases.append(case('multiply-no-speculate',x))
x=copy.deepcopy(base);x[1]['es']=[ins(4,2,1,0,-4)];cases.append(case('add-other-no-speculate',x))
x=copy.deepcopy(base);x[0]['c']=1;cases.append(case('duplicate-successor',x))
x=copy.deepcopy(base);x.append(block([],1,1));cases.append(case('unreachable-predecessor',x))
x=copy.deepcopy(base);x[2]['a']=1;cases.append(case('shared-arm-entry',x))
x=copy.deepcopy(base);x[1]['a']=1;cases.append(case('arm-cycle',x))
cases.append(case('empty-direct-edge',[block(entry,2,-3,1,1),block()],start=1,join=1))
for length in (8,9):
 bs=[block(entry,2,-3,1,length+1)]+[block([],1,i+2) for i in range(length)]+[block()]
 cases.append(case(f'path-{length}',bs,join=length+1))
for size in (128,129):
 x=copy.deepcopy(base);x[1]['es']=[ins(0)]*size;cases.append(case(f'path-instructions-{size}',x))
x=copy.deepcopy(base);x[1]['es']=[ins(1,2,-3)];cases.append(case('bool-copy',x,tys={2:2}))
x=copy.deepcopy(base);x[1]['es']=[ins(1,2,-2)];cases.append(case('bool-invalid-constant',x,tys={2:2},reason=5))
x=copy.deepcopy(base);x[1]['es']=[ins(1,2,-9223372036854775808)];cases.append(case('min-constant-index',x,reason=5))
x=copy.deepcopy(base);x[1]['es']=[ins(1,2,-9223372036854775807)];cases.append(case('large-constant-index',x,reason=5))
x=copy.deepcopy(base);x[1]['es']=[ins(1,2,0)];x[3]['es']=[ins(1,3,2)];cases.append(case('one-arm-uninitialized',x,reason=6))
x=[block([],1,1),block([ins(1,1,0)],2,-3,2,3),block([ins(1,0,-2)],1,1),block()];cases.append(case('loop-first-iteration',x,reason=6))
x=copy.deepcopy(base);x[0]['es']=[ins(1,0,0)];cases.append(case('self-read-before-def',x,reason=6))
x=copy.deepcopy(base);x[0]['es']=[ins(1,0,-2),ins(1,0,0),ins(1,1,0)];cases.append(case('self-read-after-def',x))
x=[block([ins(2,0,0)],2,-3,1,2),block([ins(3,0,-4)],1,0),block()];cases.append(case('entry-formal-backedge',x,start=1,join=0))
x=[block([ins(1,1,0)],2,-3,1,2),block([ins(1,0,-2)],1,0),block()];cases.append(case('entry-temp-backedge',x,reason=6,start=1,join=0))
for name,e in [('address',ins(16,2,0,0)),('call',ins(7,2,1,-1)),('pointer-write',ins(18,0,1,0,8)),('unknown-op',ins(49))]:
 x=copy.deepcopy(base);x[1]['es']=[e];cases.append(case(name,x,reason=5))
x=copy.deepcopy(base);x[1]['es']=[ins(4,2,6,0,1,sval='str_cmp')];cases.append(case('hidden-string-call',x,tys={2:2},reason=5))
x=copy.deepcopy(base);x[1]['es']=[ins(1,2,0)];cases.append(case('copy-type-mismatch',x,tys={2:2},reason=5))
x=copy.deepcopy(base);x[0]['a']=0;cases.append(case('integer-condition',x,reason=4))
x=copy.deepcopy(base);x[3]['a']=0;cases.append(case('void-return-value',x,reason=4))
x=copy.deepcopy(base);x[3]['tk']=4;cases.append(case('unknown-terminator',x,reason=4))
x=copy.deepcopy(base);x[1]['a']=999;cases.append(case('out-of-bounds-successor',x,reason=4))
for name,extra in [
 ('cycle-chain','mfn_set_inext(mut &f.instrs, 1, 0)'),
 ('invalid-next','mfn_set_inext(mut &f.instrs, 1, -2)'),
 ('invalid-tail','mut q := f.blocks[0]\n        q.tail = 0\n        mfn_set_block(mut &f.blocks, 0, q)'),
 ('shared-instruction-owner','mut q := f.blocks[2]\n        q.head = 0\n        q.tail = 1\n        mfn_set_block(mut &f.blocks, 2, q)'),
 ('orphan-executable','mut q := mkinstr(1)\n        q.a = 3\n        q.b = -2\n        f.instrs.push(q)')]:
 cases.append(case(name,copy.deepcopy(base),reason=4,extra=extra))
cases.append(case('orphan-noop',copy.deepcopy(base),extra='f.instrs.push(mkinstr(0))',orphan=ins(0)))
for name,extra in [('wide-slot','f.temps_nslots[0] = 2'),('owning-local','f.locals_owning[0] = true'),('bad-formals','f.nparams = 9'),('missing-metadata','f.temps_nslots = []int{}'),('retained-phi','f.phis.push(MPhi{block: 3, local: 0, dest: 2, ty: 1, arg_head: 0, arg_count: 0})')]:
 cases.append(case(name,copy.deepcopy(base),reason=3,extra=extra))
cases.append(case('block-budget',[block([],1,i+1) for i in range(32)]+[block()],reason=2))
cases.append(case('cell-budget',[block()],nt=255,reason=2))
for size in (1024,1025):cases.append(case(f'instruction-budget-{size}',[block([ins(0)]*size)],reason=2 if size>1024 else 0))
cases.append(case('zero-storage',[block()],nl=0,nt=0,np=0,start=0,join=0))
cases.append(case('block-budget-exact',[block([],1,i+1) for i in range(31)]+[block()],start=1,join=31))
cases.append(case('cell-budget-exact',[block()],nt=254,start=0,join=0))
cases.append(case('local-budget-exact',[block()],nl=48,start=0,join=0))
cases.append(case('local-budget-excess',[block()],nl=49,reason=2,start=0,join=0))
for op in (1,5):
 x=copy.deepcopy(base);x[1]['es']=[ins(5,2,op,0)];cases.append(case(f'word-unary-{op}',x))
x=copy.deepcopy(base);x[0]['es'].append(ins(1,2,-3));x[1]['es']=[ins(5,3,2,2)];cases.append(case('bool-not',x,tys={2:2,3:2}))
for op in (3,4):
 x=copy.deepcopy(base);x[1]['es']=[ins(5,2,op,0)];cases.append(case(f'float-conversion-refused-{op}',x,reason=5))
x=copy.deepcopy(base);x[1]['es']=[ins(4,2,6,0,1)];cases.append(case('word-comparison',x,tys={2:2}))
x=copy.deepcopy(base);x[0]['es'].append(ins(1,2,-3));x[0]['es'].append(ins(1,3,-5));x[1]['es']=[ins(4,2,6,2,3)];cases.append(case('bool-equality',x,tys={2:2,3:2}))
# Deterministic renumberings, mixed empty blocks and random Copy schedules.
rng=random.Random(20261004)
for index in range(24):
 x=copy.deepcopy(base);mapping=list(range(4));rng.shuffle(mapping)
 for b in x:
  for e in b['es']:
   if e['k']==2:e['a']=mapping[e['a']]
 x[1]['es']=[ins(1,mapping[2],mapping[0])]
 for _ in range(3+index%5):x[1]['es'].append(ins(1,mapping[rng.randrange(4)],mapping[rng.randrange(3)]))
 cases.append(case(f'renumbered-sequence-{index}',x))
# Reverse block numbering stresses convergence and makes numerical ID order irrelevant.
for length in (3,7,16,30):
 bs=[block(entry,1,length)]+[block([],1,i-1) for i in range(1,length+1)]
 bs[1]=block([ins(1,2,0)],3)
 cases.append(case(f'reverse-chain-{length}',bs,start=length,join=1))
# Instruction IDs are only storage indices; point order follows next links.
x=copy.deepcopy(base);x[1]['es']=[ins(1,2,0),ins(1,0,1),ins(1,1,2)];cases.append(case('non-monotonic-linked-order',x,reverse=True))

support=['@xu/types','']
main=['@main','#xu/types','fn dump_point(m &types.Mir, f &types.MirValueFacts, bi int, pt int, nl int, nt int) {','    for kind in 1:3 {','        mut count := nl','        if kind == 2 { count = nt }','        if count > 8 { count = 8 }','        for cell in -1:count + 1 { println(types.mir_value_facts_version(m, 0, f, bi, pt, kind, cell)) }','    }','}',];expected=[];records=[]
def emit(*values):expected.extend(str(v) for v in values)
def succ(b):return [b['a']] if b['tk']==1 else list(dict.fromkeys([b['b'],b['c']])) if b['tk']==2 else []
def dcell(e,nl):return None if e['k']==0 else e['a'] if e['k']==3 else nl+e['a']
def readcells(e,nl):
 if e['k']==2:return [e['b']]
 vs=[e['b']] if e['k'] in (1,3) else [e['c'],e['d']] if e['k']==4 else [e['c']] if e['k']==5 else []
 return [nl+v for v in vs if v>=0]
for cid,c in enumerate(cases):
 nl,nt,np=c['nl'],c['nt'],c['np'];n=nl+nt;bs=c['bs'];nb=len(bs);reason=c['reason'];tys=[c.get('tys',{}).get(i,1) for i in range(nt)]
 support_start=len(support)
 main_start=len(main)
 ids=[];ni=0
 for b in bs:
  ids.append(list(range(ni,ni+len(b['es']))));ni+=len(b['es'])
 if c.get('orphan'):ni+=1
 if c.get('reverse'):
  perm=list(reversed(range(ni)))
  ids=[[perm[i] for i in row] for row in ids]
 support.extend([f'    if mode == {cid} {{',f'        f.nparams = {np}',f'        f.ret = {c["ret"]}',f'        for _ in 0:{nl} {{ f.locals.push(1)\n            f.locals_nslots.push(1)\n            f.locals_owning.push(false) }}',f'        for _ in 0:{nt} {{ f.temps.push(1)\n            f.temps_nslots.push(1) }}'])
 for i,t in enumerate(tys):
  if t!=1:support.append(f'        f.temps[{i}] = {t}')
 for v in C:support.append('        f.consts.push('+('0 - 9223372036854775807 - 1' if v==-9223372036854775808 else str(v))+')')
 for b in bs:support.append(f'        f.blocks.push(MBlock{{head: -1, tail: -1, tkind: {b["tk"]}, ta: {b["a"]}, tb: {b["b"]}, tc: {b["c"]}, line: 0}})')
 if c.get('reverse'):
  es={ii:e for b,row in zip(bs,ids) for ii,e in zip(row,b['es'])}
  for ii in range(ni):
   e=es[ii];support.extend(['        if true {',f'            mut q := mkinstr({e["k"]})',f'            q.a = {e["a"]}',f'            q.b = {e["b"]}',f'            q.c = {e["c"]}',f'            q.d = {e["d"]}','            f.instrs.push(q)','        }'])
  for bi,row in enumerate(ids):
   if not row:continue
   support.extend(['        if true {',f'            mut q := f.blocks[{bi}]',f'            q.head = {row[0]}',f'            q.tail = {row[-1]}',f'            mfn_set_block(mut &f.blocks, {bi}, q)','        }'])
   for a,b in zip(row,row[1:]):support.append(f'        mfn_set_inext(mut &f.instrs, {a}, {b})')
 else:
  for bi,b in enumerate(bs):
   if len(b['es'])>100 and all(e['k']==0 for e in b['es']):support.append(f'        for _ in 0:{len(b["es"])} {{ mir_cfg_append(mut &f, {bi}, mkinstr(0)) }}');continue
   for e in b['es']:
    val='0 - 9223372036854775807 - 1' if e['b']==-9223372036854775808 else str(e['b'])
    support.extend(['        if true {',f'            mut q := mkinstr({e["k"]})',f'            q.a = {e["a"]}',f'            q.b = {val}',f'            q.c = {e["c"]}',f'            q.d = {e["d"]}'])
    if 'sval' in e:support.append(f'            q.sval = "{e["sval"]}"')
    support.extend([f'            mir_cfg_append(mut &f, {bi}, q)','        }'])
 if c.get('extra'):support.append('        '+c['extra'])
 support.append('    }')
 # Reachability via queue, predecessors via explicit deduplicated edges.
 reach={0};queue=[0]
 if reason==0 or reason==6:
  for bi in queue:
   for to in succ(bs[bi]):
    if to not in reach:reach.add(to);queue.append(to)
  preds=[[bi for bi in queue if to in succ(bs[bi])] for to in range(nb)]
  incoming=[[set() for _ in range(n)] for _ in bs];outgoing=copy.deepcopy(incoming)
  for _ in range(max(1,(ni+1)*nb*n+nb)):
   changed=False
   for bi in queue:
    new=[]
    for cell in range(n):
     defs=set().union(*(outgoing[p][cell] for p in preds[bi]))
     if bi==0:defs.add(ni+cell if cell<np else -1)
     new.append(defs)
    out=copy.deepcopy(new)
    for ii,e in zip(ids[bi],bs[bi]['es']):
     dc=dcell(e,nl)
     if dc is not None:out[dc]={ii}
    if new!=incoming[bi] or out!=outgoing[bi]:changed=True;incoming[bi]=new;outgoing[bi]=out
   if not changed:break
  else:raise AssertionError('independent set oracle did not converge')
  bad=False
  for bi in queue:
   state=copy.deepcopy(incoming[bi])
   for ii,e in zip(ids[bi],bs[bi]['es']):
    if any(not state[cell] or -1 in state[cell] for cell in readcells(e,nl)):bad=True
    dc=dcell(e,nl)
    if dc is not None:state[dc]={ii}
   if bs[bi]['tk'] in (2,3) and bs[bi]['a']>=0 and (-1 in state[nl+bs[bi]['a']] or not state[nl+bs[bi]['a']]):bad=True
  assert bad==(reason==6),(c['name'],bad,reason)
 def version(bi,point,kind,cell):
  if reason or bi not in reach or not (0<=cell<(nl if kind==1 else nt)):return -2
  if point<-1 or point>=ni or (point!=-1 and point not in ids[bi]):return -2
  dc=cell if kind==1 else nl+cell;defs=set(incoming[bi][dc])
  for ii,e in zip(ids[bi],bs[bi]['es']):
   if ii==point:break
   if dcell(e,nl)==dc:defs={ii}
  if not defs or -1 in defs:return -1
  return next(iter(defs)) if len(defs)==1 else ni+n+bi*n+dc
 from_=c.get('from',0);start=c.get('start',1);join=c.get('join',3)
 er=reason or 8;env=[];touched=[0]*n;path=[]
 if reason==0 and from_ in reach and start in reach and join in reach and start in succ(bs[from_]) and from_!=start:
  env=[('s',cell,0) if version(from_,-1,1 if cell<nl else 2,cell if cell<nl else cell-nl)>=0 else None for cell in range(n)]
  bi=start;pred=from_;steps=0
  for _ in range(9):
   if bi==join:er=0;break
   if bi==from_ or preds[bi]!=[pred] or bs[bi]['tk']!=1 or bi in path:break
   if len(path)>=8:er=2;break
   path.append(bi)
   for e in bs[bi]['es']:
    if steps>=128:er=2;break
    steps+=1
    if e['k']==0:continue
    def source(v):return env[nl+v] if v>=0 else ('c',C[-v-2],0)
    add=0;k=e['k']
    if k in (1,3):s=source(e['b'])
    elif k==2:s=env[e['b']]
    elif k==4 and e['b']==1:
     if e['d']< -1 and C[-e['d']-2]==1:s=source(e['c'])
     elif e['c']< -1 and C[-e['c']-2]==1:s=source(e['d'])
     else:er=9;break
     add=1
    else:er=9;break
    if s is None:er=6;break
    if s[2]+add>1:er=9;break
    dc=dcell(e,nl);env[dc]=(s[0],s[1],s[2]+add);touched[dc]=1
   else:pred=bi;bi=bs[bi]['a'];continue
   break
  else:er=2
 main.extend([f'    if true {{ m := types.scalar_edge_fixture({cid})','        f := types.new_mir_value_facts(&m, 0)','        println(f.reason)',f'        for bi in 0:{nb} {{','            if types.mir_value_facts_reachable(&f, bi) { println(1) } else { println(0) }','            println(types.mir_value_facts_pred_count(&f, bi))','        }'])
 emit(reason)
 for bi in range(nb):emit(int(not reason and bi in reach),len(preds[bi]) if not reason and bi in reach else -1)
 if ni<=160:
  main.extend([f'        for ii in -1:{ni+1} {{','            println(types.mir_value_facts_owner(&f, ii))','            println(types.mir_value_facts_ordinal(&f, ii))','        }'])
  for ii in range(-1,ni+1):
   owner=next((bi for bi,row in enumerate(ids) if ii in row),-1) if not reason else -1
   emit(owner,ids[owner].index(ii) if owner>=0 else -1)
 # Sample every exact point (and terminator), with bad cross-block and cell queries.
 for bi in range(min(nb,5)):
  points=[-2,-1,*ids[bi],ni] if ni<=160 else [-2,-1,0,ni-1,ni]
  main.extend(['        if true {', '            points := ['+', '.join(map(str,points))+']', f'            for pi in 0:points.len {{ dump_point(&m, &f, {bi}, points[pi], {nl}, {nt}) }}','        }'])
  for pt in points:
   for kind in (1,2):
    count=nl if kind==1 else nt
    cells=list(range(-1,min(count,8)+1))
    for cell in cells:
     emit(version(bi,pt,kind,cell))
 main.extend([f'        e := types.mir_read_scalar_edge(&m, 0, &f, {from_}, {start}, {join})','        println(e.reason)','        println(types.mir_scalar_edge_block_count(&e))','        for kind in 1:3 {', '            mut count := '+str(nl),f'            if kind == 2 {{ count = {nt} }}','            for cell in 0:count { for lane in 0:4 { println(types.mir_scalar_edge_value(&e, kind, cell, lane)) } }','        }','    }'])
 emit(er,len(path) if er==0 else -1)
 for cell in range(n):
  if er:emit(-1,-1,-1,-1)
  else:
   s=env[cell];emit(0 if s is None else 1 if s[0]=='s' else 2,cell if s is None else s[1],0 if s is None else s[2],touched[cell])
 support_part=support[support_start:];del support[support_start:]
 support_part[0]=f'pub fn scalar_edge_fixture_{cid}() Mir {{'
 support_part[1:1]=['    mut m := empty_mir()', '    mut f := mir_fn_blank()']
 support_part[-1:]=['    m.fns.push(f)','    m.superseded.push(0)','    << m','}']
 support.extend(support_part)
 main_part=main[main_start:];del main[main_start:]
 main_part[0]=f'fn dump_case_{cid}() {{ m := types.scalar_edge_fixture_{cid}()'
 main.extend(main_part)
 records.append(dict(id=cid,name=c['name'],facts_reason=reason,edge_reason=er,ni=ni,nb=nb,nl=nl,nt=nt))
# Independent semantic contract for actual strict-SSA -> deSSA fixtures.
phi_support=Path(__file__).with_name('mir_scalar_edges_phi.xu').read_text()
support.append(phi_support.split('\n',1)[1])
main.extend(['fn dump_phi_cases() {','    for mode in 0:2 {','        m := types.scalar_phi_loop_fixture(mode)','        println(m.fns.len)','        f := types.new_mir_value_facts(&m, 0)','        println(f.reason)','        e := types.mir_read_scalar_edge(&m, 0, &f, 2, 4, 1)','        println(e.reason)','        println(types.mir_scalar_edge_block_count(&e))','        for role in 0:2 {','            mut kind := 1','            mut cell := role','            if mode == 1 { kind = 2','                cell += 2 }','            println(types.mir_scalar_edge_value(&e, kind, cell, 0))','            mut source := types.mir_scalar_edge_value(&e, kind, cell, 1)','            if mode == 1 { source -= 4 }','            println(source)','            println(types.mir_scalar_edge_value(&e, kind, cell, 2))','            println(types.mir_scalar_edge_value(&e, kind, cell, 3))','        }','        for role in 0:2 {','            mut kind := 1','            mut cell := role','            if mode == 1 { kind = 2','                cell += 2 }','            v := types.mir_value_facts_version(&m, 0, &f, 1, -1, kind, cell)','            if v >= types.mir_nins(&m, 0) + types.mir_nlocals(&m, 0) + types.mir_ntemps(&m, 0) { println(1) } else { println(0) }','        }','    }','    for mode in 0:2 {','        m := types.scalar_phi_diamond_fixture(mode)','        println(m.fns.len)','        f := types.new_mir_value_facts(&m, 0)','        println(f.reason)','        for arm in 1:3 {','            e := types.mir_read_scalar_edge(&m, 0, &f, 0, arm, 3)','            println(e.reason)','            mut kind := 1','            mut cell := 2','            if mode == 1 { kind = 2','                cell = 4 }','            for lane in 0:4 { println(types.mir_scalar_edge_value(&e, kind, cell, lane)) }','        }','    }','}'])
for mode in range(2):emit(1,0,0,1,1,1,0,1,1,0,0,1,1,1)
for mode in range(2):emit(1,0,0,1,3,1,1,0,1,4,0,1)
bad_id=next(i for i,c in enumerate(cases) if c['name']=='block-budget')
main.extend(['fn dump_invalid_owners() {',f'    m := types.scalar_edge_fixture_{bad_id}()', '    mut f := types.new_mir_value_facts(&m, 0)','    f.reason = 0','    println(types.mir_value_facts_owner(&f, 0))','    println(types.mir_value_facts_pred_count(&f, 0))','    println(types.mir_value_facts_version(&m, 0, &f, 0, -1, 1, 0))','    if types.mir_value_facts_reachable(&f, 0) { println(1) } else { println(0) }','    mut e := types.mir_read_scalar_edge(&m, 0, &f, 0, 1, 2)','    e.reason = 0','    println(types.mir_scalar_edge_value(&e, 1, 0, 0))','    println(types.mir_scalar_edge_block_count(&e))','}'])
emit(-1,-1,-2,0,-1,-1)
records.extend([dict(name='actual-phi-critical-loop-vs-local',facts_reason=0,edge_reason=0),dict(name='actual-phi-diamond-vs-local',facts_reason=0,edge_reason=0),dict(name='invalid-owner-public-code-mutation',facts_reason=2,edge_reason=1)])
main.extend(['fn main() int {','    argv := args()','    if argv.len > 1 && argv[1] == "baseline" { << 0 }',*[f'    dump_case_{i}()' for i in range(len(cases))],'    dump_phi_cases()','    dump_invalid_owners()','    << 0','}'])
(D/'support.xu').write_text('\n'.join(support)+'\n');(D/'main.xu').write_text('\n'.join(main)+'\n');(D/'expected.txt').write_text('\n'.join(expected)+'\n');(D/'oracle.json').write_text(json.dumps(dict(cases=records,output_lines=len(expected)),indent=2)+'\n')
print('prepared',len(records),'cases',len(expected),'golden lines')
