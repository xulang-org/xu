"""NaN-sensitive comparisons at the SSA simplifier and product seams."""
from pathlib import Path
import os
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get("XU", ROOT / "bin/xu")).resolve()
FIXTURE = ROOT / "tests/fixtures/f64_unordered_cmp"


def build_and_run(source, binary, flags=(), cwd=ROOT):
    built = subprocess.run(
        [str(ROOT / "scripts/run_product_compiler.sh"), "--cwd", str(cwd),
         str(XU), "build", *flags, str(source), "-o", str(binary)],
        cwd=cwd, capture_output=True, text=True, timeout=180,
    )
    assert built.returncode == 0, built.stderr
    return subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize("flags", [(), ("--no-opt",), ("--ra=0",),
                                  ("--no-regcache",), ("-O1",), ("-O2",), ("-O3",)])
def test_product_nan_relations(tmp_path, flags):
    run = build_and_run(FIXTURE / "main.xu", tmp_path / "program", flags)
    assert (run.returncode, run.stdout, run.stderr) == (
        0, (FIXTURE / "expected.txt").read_text(), "",
    )


STAGE_SUPPORT = """@xu/types
pub fn unordered_cmp_stage(op int, ty int) bool {
    mut f := mir_fn_blank()
    f.nparams = 1
    f.ret = 2
    f.ret_nslots = 1
    f.locals.push(ty)
    f.locals_nslots.push(1)
    f.locals_owning.push(false)
    f.temps.push(ty)
    f.temps_nslots.push(1)
    f.temps.push(2)
    f.temps_nslots.push(1)
    f.blocks.push(MBlock{head: -1, tail: -1, tkind: 3, ta: 1, tb: -1, tc: -1, line: 0})
    mut load := mkinstr(2)
    load.a = 0
    load.b = 0
    mir_cfg_append(mut &f, 0, load)
    mut cmp := mkinstr(4)
    cmp.a = 1
    cmp.b = op
    cmp.c = 0
    cmp.d = 0
    mir_cfg_append(mut &f, 0, cmp)
    if mir_verify_mfn_f(&f, true) != 0 { << false }
    if mir_ssa_simplify_f(mut &f) < 0 { << false }
    if mir_verify_mfn_f(&f, true) != 0 { << false }
    if ty == 4 {
        // A bool result does not grant integer semantics to its f64 operands.
        << f.blocks[0].ta == 1 && mfn_ikind(&f.instrs, 1) == 4 && mfn_ib(&f.instrs, 1) == op
    }
    mut expected := 0
    if op == 6 || op == 9 || op == 11 { expected = 1 }
    result := f.blocks[0].ta
    << result <= -2 && f.val_const(result) == expected
}
"""


def test_ssa_self_comparison_operand_types(tmp_path):
    shutil.copytree(ROOT / "src", tmp_path / "src")
    (tmp_path / "src/xu/types/unordered_cmp_test.xu").write_text(STAGE_SUPPORT)
    source = tmp_path / "main.xu"
    source.write_text("""@main
#xu/types
fn main() int {
    for op in 6:12 {
        assert(types.unordered_cmp_stage(op, 4))
        assert(types.unordered_cmp_stage(op, 1))
    }
    println("SSA comparison types PASS: 12 cases")
    << 0
}
""")
    # Run the actual pass explicitly; disable optimization of the test harness.
    run = build_and_run(source, tmp_path / "stage", ("--no-opt",), tmp_path)
    assert (run.returncode, run.stdout, run.stderr) == (
        0, "SSA comparison types PASS: 12 cases\n", "",
    )
