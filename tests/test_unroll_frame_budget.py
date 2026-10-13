"""Keep O3 expansion from allocating unused scalar homes before SIMD selection."""
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get("XU", ROOT / "bin/xu")).resolve()


class UnrollFrameBudgetTests(unittest.TestCase):
    def build(self, source, mode, out):
        result = subprocess.run(
            [str(ROOT / "scripts/run_product_compiler.sh"), str(XU), "build",
             str(source), mode, "--timings", "-o", str(out)],
            cwd=ROOT, capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        line = next(line for line in result.stderr.splitlines()
                    if line.startswith("ra-fn: label=_xu_main "))
        fields = dict(re.findall(r"(\w+)=([^ ]+)", line))
        run = subprocess.run([str(out)], capture_output=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        return fields, run.stdout

    def test_vec3_reduction_does_not_grow_o3_frame(self):
        with tempfile.TemporaryDirectory(prefix="xu-unroll-frame-") as td:
            rows = []
            for mode in ("-O2", "-O3"):
                fields, stdout = self.build(ROOT / "tests/data/compiler_workloads/sroa_vec3.xu", mode,
                                            Path(td) / mode)
                self.assertEqual(stdout, b"537600000\n")
                rows.append(fields)
            self.assertLessEqual(int(rows[1]["frame"]), int(rows[0]["frame"]))
            self.assertLessEqual(int(rows[1]["temps"]), int(rows[0]["temps"]))

    def test_small_integer_loop_still_unrolls(self):
        with tempfile.TemporaryDirectory(prefix="xu-unroll-integer-") as td:
            source = Path(td) / "main.xu"
            source.write_text("""@main
fn values() []int {
    mut v := []int{}
    for i in 0:8 { v.push(i) }
    << v
}
fn main() int {
    v := values()
    mut s := 0
    mut i := 0
    while i < 64 {
        s += v[i & 7]
        i += 1
    }
    println(s)
    << 0
}
""")
            rows = []
            for mode in ("-O2", "-O3"):
                fields, stdout = self.build(source, mode, Path(td) / mode)
                self.assertEqual(stdout, b"224\n")
                rows.append(fields)
            self.assertGreater(int(rows[1]["temps"]), int(rows[0]["temps"]))


if __name__ == "__main__":
    unittest.main()
