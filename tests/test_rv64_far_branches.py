#!/usr/bin/env python3
"""Execute far RV64 calls and both conditional paths using the real assembler."""
from pathlib import Path
import argparse,hashlib,json,re,shutil,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
HARNESS='''@main
fn main() int {
    argv := args()
    mut a := DEFAULTS
    a.arch = 5
    e := new_elf_riscv64()
    a.code_vaddr = e.code_vaddr()
    a.label("entry")
    a.v_mov_imm(10, 0)
    a.r_bcond_jal(true, 10, 0, "far_start")
    a.v_mov_imm(10, 9)
    a.v_mov_imm(17, 93)
    a.v_ecall()
    a.label("back")
    a.v_mov_imm(10, 0)
    // Untaken far branch must skip both words, including JALR.
    a.r_bcond_jal(false, 10, 0, "far_fail")
    a.r_jal("forward_call")
    a.v_mov_imm(17, 93)
    a.v_ecall()
    a.label("back_call")
    a.v_mov_imm(10, 0)
    a.r_jalr(0, 1, 0)
    // More than JAL's reach, using executable NOPs, not source padding.
    for i in 0:270000 { a.r_emit32(19) }
    a.label("far_start")
    a.r_j("back")
    a.label("forward_call")
    a.r_mov(8, 1)
    a.r_jal("back_call")
    a.r_mov(1, 8)
    a.r_jalr(0, 1, 0)
    a.label("far_fail")
    a.v_mov_imm(10, 7)
    a.v_mov_imm(17, 93)
    a.v_ecall()
    a.data_vaddr = e.data_vaddr(a.code.len)
    a.v_fixup_all()
    mut out := []int{}
    e.generate(&a, 0, mut &out)
    write_file(argv[1], string_from_bytes(out)) or (err) { << 1 }
    println("assembled")
    << 0
}
'''
def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--xu',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--source-root',type=Path,default=ROOT);args=ap.parse_args();xu=args.xu.resolve();srcroot=args.source_root.resolve();rows=[];identity=hashlib.sha256(xu.read_bytes()).hexdigest()
 if not shutil.which('qemu-system-riscv64'):raise RuntimeError('QEMU required for the execution gate')
 args.out.parent.mkdir(parents=True,exist_ok=True)
 paths=subprocess.check_output(['bash','-c','. scripts/gen1_sources.sh; printf "%s\\n" "$GEN1_SRCS"'],cwd=srcroot,text=True).split()
 with tempfile.TemporaryDirectory(prefix='xu-rv64-far-') as td:
  work=Path(td)/'main';work.mkdir();driver=work/'driver_entry.xu';s=(srcroot/'src/cmd/compile/driver_entry.xu').read_text();assert s.count('fn main() int {')==1;driver.write_text(s.replace('fn main() int {','fn compiler_entry() int {'))
  defaults=re.search(r'mut a := (Assembler\{.*?^    \})',(srcroot/'src/cmd/compile/driver_build.xu').read_text(),re.S|re.M);assert defaults;harness=work/'far_test.xu';harness.write_text(HARNESS.replace('DEFAULTS',defaults[1]));inputs=[driver if p=='src/cmd/compile/driver_entry.xu' else srcroot/p for p in paths]+[harness]
  for opt in ('-O0','-O1'):
   native=work/f'assembler{opt}';built=subprocess.run([str(srcroot/'scripts/run_product_compiler.sh'),str(xu),'build',opt,*map(str,inputs),'-o',str(native)],cwd=srcroot,capture_output=True,text=True,timeout=240);assert built.returncode==0,built.stderr
   guest=work/f'far{opt}.elf';assembled=subprocess.run([str(native),str(guest)],capture_output=True,text=True,timeout=60);assert assembled.returncode==0 and assembled.stdout=='assembled\n' and not assembled.stderr,assembled
   run=subprocess.run(['python3',str(ROOT/'scripts/riscv64_qemu_run.py'),str(guest),'3'],capture_output=True,text=True,timeout=30);row=dict(profile=opt,status='PASS' if run.returncode==0 and not run.stdout and run.stderr=='__EXIT_CODE__=0\n' else 'FAIL',stdout=run.stdout,stderr=run.stderr,rc=run.returncode,binary_sha256=hashlib.sha256(guest.read_bytes()).hexdigest(),bytes=guest.stat().st_size);rows.append(row);args.out.write_text(json.dumps(dict(status='PASS' if all(x['status']=='PASS' for x in rows) else 'FAIL',compiler_sha256=identity,source_root=str(srcroot),cases='forward/backward calls, backward jump, taken/untaken far conditionals',rows=rows),indent=2)+'\n');print(opt,row,flush=True);assert row['status']=='PASS',row
 assert hashlib.sha256(xu.read_bytes()).hexdigest()==identity
if __name__=='__main__':main()
