from pathlib import Path
import argparse, json

parser = argparse.ArgumentParser(description='Generate independent ordered-definition and scalar-storage oracle cases.')
parser.add_argument('--out-dir', required=True, type=Path)
D = parser.parse_args().out_dir
D.mkdir(exist_ok=True)
# Independent opcode result roles from the MIR contract. These are event
# declarations for the oracle, rather than calls to the implementation.
no_results = {0,3,8,11,13,18,20,21,22,24,25,31,33,34,37,46,47,48}
ops = {}
for k in range(52):
    defs = [] if k in no_results else ['a']
    if k == 32: defs.append('d')
    if k == 36: defs.append('b')
    ops[k] = defs
def event(k, a=-1, b=-1, c=-1, d=-1): return dict(k=k,a=a,b=b,c=c,d=d)
cases = []
for k in range(52):
    cases.append(dict(id=k, events=[event(k,1,2,3,4)], valid=k<49 and k not in (27,28,29)))
examples = {
    100:[event(1,0,-2),event(2,1,0),event(3,0,0),event(1,2,1),event(1,1,-3),event(3,1,2),event(2,3,0),event(1,0,3)],
    101:[event(4,0,1,-2,-3),event(1,1,0),event(4,0,1,-3,-2),event(3,0,1),event(1,2,1),event(2,3,0)],
    102:[event(2,0,0),event(2,1,1),event(1,2,1),event(1,1,0),event(1,0,2),event(3,0,0),event(3,1,1)],
    103:[event(2,0,0),event(2,1,1),event(1,0,1),event(1,1,0),event(3,0,0),event(3,1,1)],
    104:[event(2,0,3),event(1,1,0)],
    105:[event(1,0,-2)],
    106:[event(1,0,-2),event(1,1,0)],
    107:[event(1,0,-2),event(1,1,0)],
    108:[event(1,0,-2)],
    109:[event(1,0,-2)],
    110:[event(1,0,-2)],
    111:[event(2,0,0),event(1,1,0)],
    112:[event(1,0,-2)],
    113:[event(1,0,-2),event(27,1,0)],
    114:[event(1,0,-2)] * 4097,
    115:[event(32,0,1,1,2),event(36,3,4,1,1)],
    124:[event(1,0,-4),event(1,1,-5)],
    125:[event(1,0,-2),event(1,1,0)],
    126:[],
    127:[event(1,0,-2)],
    128:[event(1,0,-9223372036854775808)],
    129:[event(1,0,-9223372036854775807)],
    130:[event(1,0,-2)] * 4096,
    131:[event(16,0,0,0),event(2,1,0)],
    132:[event(7,-1,1,-1),event(2,0,0)],
    133:[event(4,0,6,1,2)],
    134:[event(16,0,0,0),event(18,1,0,0,8),event(2,2,0)],
}
for key in range(116,124):
    temp_map = [(i + key - 115) % 8 for i in range(8)]
    local_map = [1,0,3,2] if key % 2 else [0,1,2,3]
    remapped = []
    for old in examples[100 if key % 2 else 102]:
        e = dict(old)
        e['a'] = local_map[e['a']] if e['k']==3 else temp_map[e['a']]
        if e['b'] >= 0:
            e['b'] = local_map[e['b']] if e['k']==2 else temp_map[e['b']]
        remapped.append(e)
    examples[key] = remapped
for key, events in examples.items():
    cases.append(dict(id=key,events=events,valid=key not in (107,108,109,113,114)))
constants = [11,22,0,1,9223372036854775807,-9223372036854775808]
unknown = (0,-1,-1,-1)
support = ['@xu/types','', 'pub fn value_plan_fixture(mode int) Mir {',
           '    mut m := empty_mir()', '    mut f := mir_fn_blank()',
           '    f.nparams = 2', '    for _ in 0:4 { f.locals.push(1); f.locals_nslots.push(1) }',
           '    for _ in 0:8 { f.temps.push(1); f.temps_nslots.push(1) }',
           '    f.consts.push(11); f.consts.push(22); f.consts.push(0); f.consts.push(1)',
           '    f.consts.push(9223372036854775807); f.consts.push(0 - 9223372036854775807 - 1)',
           '    f.blocks.push(MBlock{head: -1, tail: -1, tkind: 3, ta: -1, tb: -1, tc: -1, line: 0})']
for case in cases:
    key = case['id']
    support.append(f'    if mode == {key} {{')
    events = case['events']
    if key in (114,130):
        support.extend([f'        for _ in 0:{len(events)} {{', '            mut ins := mkinstr(1)',
                        '            ins.a = 0; ins.b = -2', '            mir_cfg_append(mut &f, 0, ins)', '        }'])
    else:
        for e in events:
            b = '(0 - 9223372036854775807 - 1)' if e['b']==-9223372036854775808 else str(e['b'])
            extra = ' ins.sval = "str_cmp";' if key==133 else ''
            support.append(f"        {{ mut ins := mkinstr({e['k']}); ins.a = {e['a']}; ins.b = {b}; ins.c = {e['c']}; ins.d = {e['d']};{extra} mir_cfg_append(mut &f, 0, ins) }}")
    support.append('    }')
support.extend([
    '    if mode == 105 { f.temps[0] = 2 }',
    '    if mode == 106 { f.temps[1] = 2 }',
    '    if mode == 124 { f.temps[0] = 2; f.temps[1] = 2 }',
    '    if mode == 125 { f.temps_nslots[0] = 2 }',
    '    if mode == 127 { f.nparams = 5 }',
    '    if mode == 133 { f.temps[0] = 2 }',
    '    if mode == 107 { last := f.instrs.len - 1; mfn_set_inext(mut &f.instrs, last, 0) }',
    '    if mode == 108 { last := f.instrs.len - 1; mfn_set_inext(mut &f.instrs, last, -2) }',
    '    if mode == 109 { mut b := f.blocks[0]; b.tail = 999; mfn_set_block(mut &f.blocks, 0, b) }',
    '    if mode == 110 {',
    '        f.blocks.push(MBlock{head: -1, tail: -1, tkind: 3, ta: -1, tb: -1, tc: -1, line: 0})',
    '        mut ins := mkinstr(1); ins.a = 1; ins.b = -3; mir_cfg_append(mut &f, 1, ins)',
    '    }',
    '    if mode == 111 { mut b := f.blocks[0]; b.tkind = 1; b.ta = 0; mfn_set_block(mut &f.blocks, 0, b) }',
    '    if mode == 112 { f.temps_nslots = []int{} }',
    '    m.fns.push(f); m.superseded.push(0)', '    << m', '}',
])
(D / 'support.xu').write_text(('\n'.join(support)+'\n').replace(';', '\n').replace('{ mut ins', 'if true { mut ins'))
lines = ['@main','#xu/types','fn main() int {']
expected = []
rows = []
for case in cases:
    key = case['id']; es = case['events']; n = len(es)
    point_loop = 'for point in -2:ni + 1 {'
    point_expr = 'point'
    if key in (114,130):
        point_loop = 'mut points := []int{}\n      points.push(-2)\n      points.push(-1)\n      points.push(0)\n      points.push(4095)\n      points.push(4096)\n      points.push(4097)\n      for pi in 0:points.len {'
        point_expr = 'points[pi]'
    lines.extend([f'    if true {{ m := types.value_plan_fixture({key})', '      ni := types.mir_nins(&m, 0)',
                  '      '+point_loop, '        for kind in 1:3 {', '          for cell in -1:9 {',
                  f'            println(types.mir_value_def_before(&m, 0, 0, {point_expr}, kind, cell))',
                  '          }', '        }', '      }'])
    points = [-2,-1,0,4095,4096,4097] if key in (114,130) else range(-2, n+1+(key==110))
    for point in points:
        for kind in (1,2):
            for cell in range(-1,9):
                valid = case['valid'] and -1 <= point < n and 0 <= cell < (4 if kind==1 else 8)
                if not valid: result = -2
                else:
                    prefix = n if point==-1 else point
                    definitions = [i for i,e in enumerate(es[:prefix])
                                   if (kind==1 and e['k']==3 and e['a']==cell) or
                                      (kind==2 and any(e[field]==cell for field in ops[e['k']]))]
                    result = definitions[-1] if definitions else -1
                expected.append(str(result)); rows.append(dict(case=key,point=point,kind=kind,cell=cell,expected=result))
    if key < 100:
        lines.append('    }')
        continue
    lines.extend(['      for sample in 0:3 {',
                  '        mut point := -1', '        if sample == 1 { point = 0 }',
                  '        if sample == 2 { point = ni / 2 }',
                  '        for kind in 1:3 { for cell in 0:4 {',
                  '          v := types.mir_scalar_value_before(&m, 0, 0, point, kind, cell)',
                  '          println(v.kind); println(v.id); println(v.ty); println(v.version)',
                  '        } }', '      }', '    }'])
    # Independent sequential storage interpreter for the scalar examples.
    tys = [1] * 8
    if key==105: tys[0]=2
    if key==106: tys[1]=2
    if key==124: tys[0]=2; tys[1]=2
    if key==133: tys[0]=2
    def source(value, ty):
        if value <= -2:
            ci = -value-2
            cv = constants[ci] if ci < len(constants) else None
            return (3,cv,ty,-1) if cv is not None and (ty==1 or cv in (0,1)) else unknown
        if 0<=value<8 and env_temp[value][2]==ty: return env_temp[value]
        return unknown
    for point in (-1,0,(n+(key==110))//2):
        env_local = [(1,l,1,-1) if l<2 and key!=111 else unknown for l in range(4)]
        env_temp = [unknown] * 8
        valid_scalar = case['valid'] and key not in (112,127) and -1 <= point < n
        prefix = n if point==-1 else max(0,point)
        for i,e in enumerate(es[:prefix]):
            k=e['k'];a=e['a'];b=e['b']
            if k>5 or (key==125 and a==0) or key==133:
                valid_scalar = False
                break
            if k==1: env_temp[a]=source(b,tys[a])
            elif k==2: env_temp[a]=env_local[b] if env_local[b][2]==tys[a] else unknown
            elif k==3: env_local[a]=source(b,1)
            elif k>0:
                env_temp[a]=(2,a,tys[a],i)
        if not valid_scalar:
            env_local = [unknown]*4;env_temp=[unknown]*8
        for kind in (1,2):
            for cell in range(4):
                v = (env_local if kind==1 else env_temp)[cell]
                expected.extend(str(x) for x in v)
lines.extend(['    << 0', '}'])
(D / 'main.xu').write_text(('\n'.join(lines)+'\n').replace(';', '\n'))
(D / 'expected.txt').write_text('\n'.join(expected)+'\n')
(D / 'oracle.json').write_text(json.dumps(dict(cases=cases,definition_queries=len(rows),output_lines=len(expected)),indent=2)+'\n')
print('prepared',len(cases),'cases',len(rows),'definition queries',len(expected),'golden lines')
