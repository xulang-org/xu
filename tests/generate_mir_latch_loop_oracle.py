#!/usr/bin/env python3
"""Initial guard/body/latch plans with simultaneous Phi and independent MIR execution."""
from pathlib import Path
import argparse, bisect, copy, json, random
from generate_mir_loop_plan_oracle import ins, block, xu_int, wrap


def fixture(ssa=False, variant='plain', seed=None, chain=1, copies=0):
    bs = [block([ins(2,0,0), ins(2,2,1), ins(26,12,0,8,1),
                 ins(1,14,-2), ins(1,15,12), ins(4,16,8,14,15)],2,16,1,2),
          block([ins(4,6,2,4,3), ins(4,7,18,6,-3), ins(4,8,1,3,7),
                 ins(26,1,0,0,3), ins(14,9,1,8,8), ins(4,10,8,9,2)],2,10,4,5),
          block([],3,22), block([ins(4,19,8,17,18)],2,19,1,2),
          block([ins(4,11,1,8,-3)],1,3), block([ins(1,20,8)],1,3)]
    types = [1]*32
    types[0],types[1] = 1200,200
    for i in (10,16,19,27,28,29): types[i]=2
    locals_=[1200,1,1,1,1]
    phis={1:[(3,{0:14,3:17}),(4,{0:15,3:18})],
          3:[(17,{4:11,5:3}),(18,{4:4,5:20})],2:[(22,{0:14,3:17})]} if ssa else {}
    if not ssa:
        bs[0]['es'][-1:-1]=[ins(3,2,14),ins(3,3,15)]
        bs[1]['es'][:0]=[ins(2,3,2),ins(2,4,3)]
        bs[3]['es'][:0]=[ins(2,17,2),ins(2,18,3)]
        bs[4]['es'].append(ins(3,2,11)); bs[5]['es'].append(ins(3,3,20))
        bs[2]['es'].append(ins(2,22,2))
    accepted=True
    if variant=='copy-chain':
        bs[0]['es'][2:2]=[ins(1,23,2),ins(1,24,23)]
        bs[1]['es'][-1]['d']=24
    elif variant=='old-needle-snapshot':
        bs[0]['es'][2:2]=[ins(1,23,2),ins(1,24 if ssa else 2,-4)]
        bs[1]['es'][-1]['d']=23
    elif variant=='old-formal-snapshot':
        bs[0]['es'].insert(-1,ins(3,1,-4))
    elif variant=='old-mid-snapshot':
        at=next(i for i,e in enumerate(bs[1]['es']) if e['k']==26)
        bs[1]['es'][at:at]=[ins(1,23,8),ins(1,24 if ssa else 8,-2)]
        next(e for e in bs[1]['es'] if e['k']==14)['c']=23
        bs[4]['es'][0]['c']=23;bs[5]['es'][0]['b']=23
    elif variant=='mid-local':
        at=next(i for i,e in enumerate(bs[1]['es']) if e['k']==26)
        bs[1]['es'].insert(at,ins(3,4,8))
    elif variant=='frame-layout':
        for bb in bs:
            for e in bb['es']:
                if e['k']==26:e['k']=17
    elif variant=='type-table-one':
        types[0]=locals_[0]=1201;types[1]=201
    elif variant=='tagged-local-index':
        bs[1]['es']=[e for e in bs[1]['es'] if e['k']!=26]
        next(e for e in bs[1]['es'] if e['k']==14)['b']=1073741824
    elif variant=='condition-copies':
        for bi,t in ((0,27),(1,28),(3,29)):
            bs[bi]['es'].append(ins(1,t,bs[bi]['a']));bs[bi]['a']=t
    elif variant=='entry-prefix':
        guard=len(bs); es=bs[0]['es'];bs.append(block(es[-1:],2,16,1,2))
        bs[0]=block(es[:-1],1,guard)
        for rows in phis.values():
            for _,args in rows:
                if 0 in args:args[guard]=args.pop(0)
    elif variant=='wrong-back-lo' and ssa:
        phis[1][0][1][3]=3;accepted=False
    elif variant=='wrong-back-hi' and ssa:
        phis[1][1][1][3]=4;accepted=False
    elif variant=='wrong-initial-lo' and ssa:
        phis[1][0][1][0]=15;accepted=False
    elif variant=='wrong-zero-exit' and ssa:
        phis[2][0][1][0]=15;accepted=False
    elif variant=='wrong-latch-exit' and ssa:
        phis[2][0][1][3]=18;accepted=False
    elif variant=='wrong-latch-condition':
        bs[3]['es'][-1]['c'],bs[3]['es'][-1]['d']=3,4;accepted=False
    elif variant=='wrong-entry-condition':
        bs[0]['es'][-1]['d']=-2;accepted=False
    elif variant=='entry-rebind-after-test':
        bs[0]['es'].append(ins(1,14,-4))
    elif variant=='state-rebind-after-test':
        bs[0]['es'].append(ins(3,2,-4));accepted=False
    elif variant=='latch-polarity':
        bs[3]['b'],bs[3]['c']=2,1;accepted=False
    elif variant=='entry-polarity':
        bs[0]['b'],bs[0]['c']=2,1;accepted=False
    elif variant=='reverse-difference':
        e=next(e for e in bs[1]['es'] if e['k']==4 and e['b']==2)
        e['c'],e['d']=e['d'],e['c'];accepted=False
    elif variant=='wrong-shift':
        next(e for e in bs[1]['es'] if e['k']==4 and e['b']==18)['d']=-2;accepted=False
    elif variant=='wrong-mid':
        next(e for e in bs[1]['es'] if e['k']==4 and e['b']==1)['b']=2;accepted=False
    elif variant=='wrong-update':
        bs[4]['es'][0]['d']=-2;accepted=False
    elif variant=='wrong-element-predicate':
        bs[1]['es'][-1]['c'],bs[1]['es'][-1]['d']=2,9;accepted=False
    elif variant=='extra-read':
        bs[1]['es'].insert(-1,ins(14,23,1,8,8));accepted=False
    elif variant=='extra-length':
        bs[1]['es'].insert(-1,ins(26,23,0,8,1));accepted=False
    elif variant=='extra-unary':
        bs[1]['es'].append(ins(5,23,1,-3));accepted=False
    elif variant=='extra-div':
        bs[1]['es'].insert(-1,ins(4,23,4,-3,-2));accepted=False
    elif variant=='latch-extra-op':
        bs[3]['es'].insert(-1,ins(4,23,1,17,18));accepted=False
    elif variant=='side-effect':
        bs[1]['es'].append(ins(7,-1,1,-1));accepted=False
    elif variant=='extra-local-write':
        bs[4]['es'].append(ins(3,4,-3));accepted=False
    elif variant=='mutable-root':
        types[0]=locals_[0]=2200;accepted=False
    elif variant=='dead-barrier':
        bs.append(block([ins(7,-1,1,-1)],3,-1));accepted=False
    elif variant=='bad-exit' and not ssa:
        bs[2]['es'][0]['b']=3;accepted=False
    elif variant!='plain':raise ValueError((ssa,variant))
    tail=4
    for _ in range(chain-1):
        to=len(bs);bs[tail]['a']=to;bs.append(block([],1,3));tail=to
    if ssa and tail!=4:
        for _,args in phis[3]:args[tail]=args.pop(4)
    bs[4]['es'] += [ins(1,31,8)]*copies
    if chain>8 or len(bs[4]['es'])>128:accepted=False
    tm=list(range(len(types)));lm=list(range(len(locals_)));bm=list(range(len(bs)))
    if seed is not None:
        r=random.Random(seed);r.shuffle(tm)
        form=[0,1];state=[2,3,4];r.shuffle(form);r.shuffle(state);lm=form+state
        rest=list(range(1,len(bs)));r.shuffle(rest);bm=[0]+rest
    out=[None]*len(bs)
    for bi,bb in enumerate(bs):
        b=copy.deepcopy(bb)
        if b['tk']==1:b['a']=bm[b['a']]
        else:
            if b['a']>=0:b['a']=tm[b['a']]
            if b['tk']==2:b['b'],b['c']=bm[b['b']],bm[b['c']]
        for e in b['es']:
            k=e['k']
            if k in (0,7):continue
            e['a']=lm[e['a']] if k==3 else tm[e['a']]
            if k==2:e['b']=lm[e['b']]
            elif k in (1,3,17,26) and e['b']>=0:e['b']=tm[e['b']]
            elif k==14:
                e['b']=1073741824+lm[e['b']-1073741824] if e['b']>=1073741824 else tm[e['b']]
                if e['c']>=0:e['c']=tm[e['c']]
            elif k==4:
                for key in ('c','d'):
                    if e[key]>=0:e[key]=tm[e[key]]
        out[bm[bi]]=b
    rt=[0]*len(types);rl=[0]*len(locals_)
    for i,t in enumerate(types):rt[tm[i]]=t
    for i,t in enumerate(locals_):rl[lm[i]]=t
    rp={bm[b]:[(tm[d],{bm[p]:tm[v] for p,v in args.items()}) for d,args in rows] for b,rows in phis.items()}
    return dict(blocks=out,types=rt,locals=rl,phis=rp,tm=tm,lm=lm,bm=bm,
                accepted=accepted,ssa=ssa,variant=variant,chain=chain,copies=copies)


def recorded(variant='recorded-deSSA'):
    c=json.loads(Path(__file__).with_name('data').joinpath('mir_latch_lower_bound.json').read_text())
    c.update(phis={},tm=list(range(32)),lm=list(range(6)),bm=list(range(13)),
             accepted=variant=='recorded-deSSA',ssa=False,storage_temp=True,
             variant='frame-layout',recorded=variant,chain=2,copies=0)
    mapping={0:0,1:13,2:16,3:26,4:27,6:9,7:10,8:11,9:15,10:17,11:19,
             12:1,14:25,15:2,16:5,17:29,18:30,19:23,20:20,22:28}
    for k,v in mapping.items():c['tm'][k]=v
    if variant=='recorded-wrong-back-lo':c['blocks'][10]['es'][0]['b']=26
    if variant=='recorded-wrong-latch-exit':c['blocks'][12]['es'][0]['b']=30
    return c


def interpret(c, values, needle):
    loc=[None]*len(c['locals']);tmp=[None]*len(c['types']);consts=c.get('consts',[0,1,99])
    for l in range(2):loc[l]=('array',l) if c['locals'][l]!=1 else needle
    def value(v):return tmp[v] if v>=0 else consts[-v-2]
    bi,pred=0,-1;truth=bisect.bisect_left(values,needle)
    for _ in range(8192):
        writes=[(d,value(args[pred])) for d,args in c['phis'].get(bi,[])]
        for d,v in writes:tmp[d]=v
        for e in c['blocks'][bi]['es']:
            k,a,b,x,y=(e[v] for v in ('k','a','b','c','d'))
            if k==1:tmp[a]=value(b)
            elif k==2:tmp[a]=loc[b]
            elif k==3:loc[a]=value(b)
            elif k==4:
                vx,vy=value(x),value(y)
                tmp[a]={1:lambda:wrap(vx+vy),2:lambda:wrap(vx-vy),18:lambda:vx>>vy,8:lambda:int(vx<vy)}[b]()
            elif k in (17,26):tmp[a]=len(values) if x==8 else value(b)
            elif k==14:
                index=value(x);assert 0<=index<len(values),(c['variant'],index)
                tmp[a]=values[index]
            elif k!=0:raise ValueError(k)
        if bi in (c['bm'][1],c['bm'][3]):
            s=(3,4) if bi==c['bm'][1] else (17,18)
            lo,hi=(tmp[c['tm'][s[0]]],tmp[c['tm'][s[1]]]) if c['ssa'] or c.get('storage_temp') else (loc[c['lm'][2]],loc[c['lm'][3]])
            assert 0<=lo<=truth<=hi<=len(values),(lo,truth,hi)
        bb=c['blocks'][bi]
        if bb['tk']==3:
            answer=value(bb['a']);assert answer==truth,(answer,truth)
            return answer
        pred=bi;bi=bb['a'] if bb['tk']==1 else bb['b'] if value(bb['a']) else bb['c']
    raise AssertionError('nonterminating MIR')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out-dir',required=True,type=Path)
    out=parser.parse_args().out_dir;out.mkdir(parents=True,exist_ok=True)
    cases=[]
    for ssa in (False,True):
        for v in ('plain','copy-chain','old-needle-snapshot','old-formal-snapshot','old-mid-snapshot','mid-local',
                  'frame-layout','type-table-one','tagged-local-index','condition-copies','entry-prefix'):
            cases.append(fixture(ssa,v))
        cases += [fixture(ssa,seed=20261004+i) for i in range(8)]
        cases.append(fixture(ssa,chain=8))
    for v in ('wrong-back-lo','wrong-back-hi','wrong-initial-lo','wrong-zero-exit','wrong-latch-exit'):
        cases.append(fixture(True,v))
    for v in ('wrong-latch-condition','wrong-entry-condition','entry-rebind-after-test','state-rebind-after-test','latch-polarity','entry-polarity',
              'reverse-difference','wrong-shift','wrong-mid','wrong-update','wrong-element-predicate','extra-read','extra-length',
              'extra-div','extra-unary','latch-extra-op','side-effect','extra-local-write','mutable-root','dead-barrier','bad-exit'):
        cases.append(fixture(False,v))
    cases += [fixture(False,chain=9),fixture(False,copies=126),fixture(False,copies=127)]
    cases += [recorded(v) for v in ('recorded-deSSA','recorded-wrong-back-lo','recorded-wrong-latch-exit')]
    rng=random.Random(40811)
    arrays=[[],[-1],[0,0],[-4,-4,-1,0,3,3,7],[-2**63,-2**63,-1,0,2**63-1]]
    arrays += [sorted(rng.randrange(-20,21) for _ in range(n)) for n in (3,7,8,9,15,16,17,31,32,33,63,64,65,127,128,129)]
    needles=[-2**63,-21,-4,-1,0,1,3,20,21,2**63-1]
    support=['@xu/types','',Path(__file__).with_name('mir_loop_plan_phi.xu').read_text().split('\n',1)[1],
             Path(__file__).with_name('mir_latch_loop_phi.xu').read_text().split('\n',1)[1]]
    main_src=['@main','#xu/types','fn latch_input(ai int) []int {']
    for ai,a in enumerate(arrays):main_src.append(f' if ai == {ai} {{ << '+('['+', '.join(xu_int(v) for v in a)+']' if a else '[]int{}')+' }')
    main_src += [' << []int{}','}']
    expected=[];records=[]
    def emit(call,v):main_src.append(' println('+call+')');expected.append(str(int(v)))
    for cid,c in enumerate(cases):
        first=len(expected)+1;tm,lm,bm=c['tm'],c['lm'],c['bm']
        support += [f'pub fn latch_fixture_{cid}() Mir {{',' mut m := empty_mir()',
                    ' m.arrays.push(CArray{elem_ty: 1, elem_bytes: 8, fixed_len: 0})',
                    ' mut f := mir_fn_blank()',' f.nparams = 2',' f.ret = 1',' f.ret_nslots = 1']
        if c['variant']=='type-table-one':support += [' m.arrays[0] = CArray{elem_ty: 2, elem_bytes: 8, fixed_len: 0}',
            ' m.arrays.push(CArray{elem_ty: 1, elem_bytes: 8, fixed_len: 0})']
        for t in c['locals']:support += [f' f.locals.push({t})',' f.locals_nslots.push(1)',' f.locals_owning.push(false)']
        for t in c['types']:support += [f' f.temps.push({t})',f' f.temps_nslots.push({3 if 200<=t<300 else 1})']
        for v in c.get('consts',(0,1,99)):support.append(f' f.consts.push({v})')
        for b in c['blocks']:support.append(f' f.blocks.push(MBlock{{head: -1, tail: -1, tkind: {b["tk"]}, ta: {b["a"]}, tb: {b["b"]}, tc: {b["c"]}, line: 0}})')
        for bi,b in enumerate(c['blocks']):
            for e in b['es']:
                support += [' if true {',f' mut q := mkinstr({e["k"]})']+[f' q.{k} = {xu_int(e[k])}' for k in 'abcd']+[f' mir_cfg_append(mut &f, {bi}, q)',' }']
        if c['ssa']:
            for b,rows in c['phis'].items():
                for d,args in rows:
                    vals=[]
                    for pred,v in args.items():vals += [pred,v]
                    support += [' if true {',' pair := ['+', '.join(map(str,vals))+']',
                        f' latch_add_phi(mut &f, {b}, {lm[2]}, {d}, &pair)',' }']
            support += [' if !latch_finish_phi(mut &f) { << m }']
        support += [' m.fns.push(f)',' m.superseded.push(0)',' << m','}']
        main_src += [f'fn dump_latch_{cid}() {{',f' m := types.latch_fixture_{cid}()']
        emit('m.fns.len',1)
        main_src += [f' mut p := types.new_mir_latch_lower_bound_loop_plan(&m, 0, {bm[1]}, {bm[3]})']
        emit('types.mir_loop_plan_kind(&p)',2 if c['accepted'] else -1)
        if c['accepted']:
            state_temp=c['ssa'] or c.get('storage_temp',False)
            fields={0:0,1:bm[1],2:bm[1],6:2 if state_temp else 1,7:tm[3] if state_temp else lm[2],
                    8:2 if state_temp else 1,9:tm[4] if state_temp else lm[3],10:tm[8],11:lm[1],12:lm[0],
                    13:0 if c['variant']=='tagged-local-index' else 17 if c['variant']=='frame-layout' else 26,
                    14:-1 if c['variant']=='tagged-local-index' else tm[1],22:bm[2],23:0,24:2,25:0,27:3,
                    31:lm[0],32:17 if c['variant']=='frame-layout' else 26,33:1 if c['variant']=='tagged-local-index' else 2,
                    34:2,35:bm[3],41:2 if state_temp else 1,42:tm[17] if state_temp else lm[2],
                    43:2 if state_temp else 1,44:tm[18] if state_temp else lm[3],45:tm[14],46:tm[15],47:tm[22]}
            for fld,v in fields.items():emit(f'types.mir_loop_plan_field(&p, {fld})',v)
            for fld,op in ((15,14),(17,4),(18,4),(30,4),(36,4)):
                emit(f'types.mir_ikind(&m, 0, types.mir_loop_plan_field(&p, {fld}))',op)
            for phase,kind,state,role in ((0,2 if state_temp else 1,tm[3] if state_temp else lm[2],1),
                  (0,2 if state_temp else 1,tm[4] if state_temp else lm[3],2),
                  (4,2 if state_temp else 1,tm[17] if state_temp else lm[2],1),
                  (4,2 if state_temp else 1,tm[18] if state_temp else lm[3],2),
                  (4,2,tm[3],21 if state_temp else 21),(4,2,tm[4],22 if state_temp else 22),
                  (2,2,tm[22],1)):
                emit(f'types.mir_loop_plan_cell_role(&p, {phase}, {kind}, {state})',role)
            # Snapshot source and increment lanes, independent of the actual
            # Phi destruction scheduler's inserted instruction numbering.
            mid=tm[23] if c['variant']=='old-mid-snapshot' else tm[8]
            nl=len(lm);kind=2 if state_temp else 1
            for arm,state,src,inc in ((0,tm[17] if state_temp else lm[2],nl+mid,1),
                    (1,tm[18] if state_temp else lm[3],nl+tm[20],0)):
                # False edge's explicit Copy20 is evaluated inside the body
                # edge, hence resolves back to the actual mid snapshot.
                if arm==1:src=nl+mid
                for lane,v in ((0,1),(1,src),(2,inc),(3,1)):
                    emit(f'types.mir_loop_plan_edge_value(&p, {arm}, {kind}, {state}, {lane})',v)
            lo_id,hi_id=(tm[3],tm[4]) if state_temp else (lm[2],lm[3])
            initial_lo,initial_hi=(len(lm)+tm[14],len(lm)+tm[15]) if state_temp else (lm[2],lm[3])
            back_lo,back_hi=(len(lm)+tm[17],len(lm)+tm[18]) if state_temp else (lm[2],lm[3])
            exit_id=tm[22] if state_temp else lm[2]
            for arm,cell,source in ((2,lo_id,initial_lo),(2,hi_id,initial_hi),
                    (3,lo_id,back_lo),(3,hi_id,back_hi),(4,exit_id,initial_lo),(5,exit_id,back_lo)):
                for lane,v in enumerate((1,source,0,1 if state_temp else 0)):
                    emit(f'types.mir_loop_plan_edge_value(&p, {arm}, {kind}, {cell}, {lane})',v)
            emit(f'types.mir_loop_plan_cell_role(&p, 3, 2, {tm[14]})',0 if c['variant']=='entry-rebind-after-test' else 1)
            emit(f'types.mir_loop_plan_cell_role(&p, 3, 2, {tm[15]})',2)
            for part in range(8):
                count=(2 if c['variant']=='entry-prefix' else 1) if part==0 else c['chain'] if part==1 else 2 if part==2 and c.get('recorded') else 1 if part in (2,7) or state_temp else 0
                emit(f'types.mir_loop_plan_block_count(&p, {part})',count)
            main_src += [' needles := ['+', '.join(xu_int(v) for v in needles)+']',f' for ai in 0:{len(arrays)} {{ input := latch_input(ai)',
                         ' for ni in 0:needles.len { println(types.loop_plan_interpret(&m, 0, &input, needles[ni])) }',' }']
            for a in arrays:
                for n in needles:expected.append(str(interpret(c,a,n)))
        else:
            for fld in range(49):emit(f'types.mir_loop_plan_field(&p, {fld})',-1)
            main_src += [' p.reason = 0'];emit('types.mir_loop_plan_kind(&p)',-1)
        for call in ('types.mir_loop_plan_block_count(&p, -1)','types.mir_loop_plan_block_count(&p, 8)',
                     'types.mir_loop_plan_block(&p, 0, 999)','types.mir_loop_plan_cell_role(&p, 5, 1, 0)',
                     'types.mir_loop_plan_cell_role(&p, 4, 2, 999)','types.mir_loop_plan_edge_value(&p, 6, 1, 0, 0)',
                     'types.mir_loop_plan_edge_value(&p, 5, 2, 999, 0)','types.mir_loop_plan_edge_value(&p, 5, 1, 0, 4)'):
            emit(call,-1)
        for fi,b,l in ((-1,bm[1],bm[3]),(1,bm[1],bm[3]),(0,-1,bm[3]),(0,bm[1],999),(0,bm[1],bm[1])):
            main_src += [f' if true {{ bad := types.new_mir_latch_lower_bound_loop_plan(&m, {fi}, {b}, {l})']
            emit('types.mir_loop_plan_kind(&bad)',-1);main_src += [' }']
        main_src += ['}']
        records.append(dict(name=('SSA-' if c['ssa'] else 'Local-')+c.get('recorded',c['variant'])+'-'+str(cid),accepted=c['accepted'],
                            semantic_runs=len(arrays)*len(needles) if c['accepted'] else 0,first_line=first,last_line=len(expected),graph=c))
    main_src += ['fn main() int { argv := args()',' if argv.len > 1 && argv[1] == "baseline" { << 0 }']
    main_src += [f' dump_latch_{cid}()' for cid in range(len(cases))]+[' << 0','}']
    for name,lines in (('support.xu',support),('main.xu',main_src),('expected.txt',expected)):(out/name).write_text('\n'.join(lines)+'\n')
    (out/'oracle.json').write_text(json.dumps(dict(cases=records,output_lines=len(expected),semantic_runs=sum(r['semantic_runs'] for r in records),
        algorithm_oracle='bisect_left plus body/latch interval invariant and simultaneous multi-block Phi semantics'),indent=2)+'\n')
    print(f'generated {len(cases)} cases, {len(expected)} golden lines')

if __name__=='__main__':main()
