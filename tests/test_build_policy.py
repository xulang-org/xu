"""Exercise the product CLI's automatic optimization and debugging policy."""
from __future__ import annotations

import hashlib
import os
import platform
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get("XU", ROOT / "bin/xu")).resolve()
WRAPPER = ROOT / "scripts/run_product_compiler.sh"


def invoke(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(WRAPPER), str(XU), *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


@pytest.fixture
def program(tmp_path: Path) -> Path:
    source = tmp_path / "main.xu"
    source.write_text("""@main
fn bump(x int) int { << x * 3 + 1 }
fn known() int { << 7 }
fn tally(n int) int {
    mut sum := 0
    for i in 0:n {
        if (i & 1) == 0 { sum += bump(i) } else { sum -= i }
    }
    << sum
}
fn main() int {
    assert(known() == 7)
    println(tally(100))
    println(known())
    << 0
}
""")
    (tmp_path / "test.policy.xu").write_text("""@main
fn test_tally() {
    assert(tally(100) == 4900)
    assert(known() == 7)
}
""")
    version = (ROOT / "VERSION").read_text().strip()
    (tmp_path / "xu.xun").write_text(
        f"module: build/policy\nversion: !ver 0.1.0\nxu: !ver {version}\n")
    # The expected value is computed independently of Xu compilation.
    assert sum(i * 3 + 1 if i % 2 == 0 else -i for i in range(100)) == 4900
    return source


PROFILES = [
    ([], ["-O1"]),
    (["--no-opt"], ["-O0"]),
    (["--debug-build"], ["-O0", "--debug"]),
    (["--debug"], ["-O1", "--debug"]),
    (["--no-opt", "-O2"], ["-O2"]),
    (["-O2", "--no-opt"], ["-O0"]),
    (["--debug-build", "-O3"], ["-O3", "--debug"]),
    (["-O3", "--debug-build"], ["-O0", "--debug"]),
    (["--ra=2", "--no-opt"], ["-O0", "--ra=2"]),
    (["--debug-build", "--ra=1"], ["-O0", "--debug", "--ra=1"]),
    (["--no-opt", "--ra=2", "--no-regcache"], ["-O0", "--no-regcache"]),
]


@pytest.mark.parametrize("command", ["build", "run", "test"])
@pytest.mark.parametrize("flags,reference", PROFILES,
                         ids=["default", "no-opt", "debug-build", "debug-info",
                              "opt-last", "no-opt-last", "optimized-debug",
                              "debug-last", "ra-first", "ra-last", "ra-disabled"])
def test_profiles_match_existing_controls(program: Path, tmp_path: Path,
                                          command: str, flags: list[str],
                                          reference: list[str]) -> None:
    binaries = []
    for index, options in enumerate((flags, reference)):
        binary = tmp_path / f"{command}-{index}"
        input_path = program.parent if command == "test" else program
        result = invoke(command, *options, str(input_path), "-o", str(binary))
        assert result.returncode == 0, result.stdout + result.stderr
        assert not result.stderr
        assert binary.is_file()
        binaries.append(binary.read_bytes())
        if command == "run":
            assert result.stdout == "4900\n7\n"
            assert not result.stderr
        elif command == "test":
            assert "FAIL" not in result.stdout + result.stderr
        if command != "test":
            executed = subprocess.run([str(binary)], capture_output=True,
                                      text=True, timeout=30)
            assert executed.returncode == 0
            assert executed.stdout == "4900\n7\n"
            assert not executed.stderr
    assert hashlib.sha256(binaries[0]).digest() == hashlib.sha256(binaries[1]).digest()


def test_default_optimizes_and_no_opt_disables(program: Path, tmp_path: Path) -> None:
    records = []
    for flags in ([], ["--no-opt"]):
        result = invoke("build", *flags, "--timings", str(program),
                        "-o", str(tmp_path / "observed"))
        assert result.returncode == 0, result.stderr
        lines = result.stderr.splitlines()
        opt = next(line for line in lines if line.startswith("opt-stats: "))
        ra = next(line for line in lines if line.startswith("ra-stats: "))
        records.append(({k: int(v) for k, v in
                         (token.split("=") for token in opt.split()[1:])}, ra))
    assert records[0][0]["commit"] > 0
    assert records[1][0]["commit"] == 0
    assert "vreg=0" in records[1][1] and "rc=0" in records[1][1]


def test_debug_build_has_source_line_information(program: Path, tmp_path: Path) -> None:
    if platform.system() != "Darwin":
        pytest.skip("this DWARF reader gate uses macOS dwarfdump")
    binary = tmp_path / "debug"
    result = invoke("build", "--debug-build", str(program), "-o", str(binary))
    assert result.returncode == 0, result.stderr
    dump = subprocess.run(["dwarfdump", "--debug-line", str(binary)],
                          capture_output=True, text=True, timeout=30, check=True)
    assert "main.xu" in dump.stdout and "debug_line" in dump.stdout


def test_run_forwards_compiler_looking_program_arguments(tmp_path: Path) -> None:
    source = tmp_path / "args.xu"
    source.write_text("""@main
#os
fn main() int {
    argv := os.argv()
    println(argv[1])
    println(argv[2])
    << 17
}
""")
    result = invoke("run", str(source), "--", "--debug-build", "--no-opt")
    assert result.returncode == 17, result.stderr
    assert result.stdout == "--debug-build\n--no-opt\n" and not result.stderr


def test_help_is_concise_and_omits_advanced_controls_and_examples() -> None:
    result = invoke("--help")
    assert result.returncode == 0
    assert "--debug-build" in result.stdout and "--no-opt" in result.stdout
    assert "advanced optimization controls" not in result.stdout
    assert "-O0 -O1 -O2 -O3" not in result.stdout
    assert "Examples:" not in result.stdout


@pytest.mark.parametrize("flag", ["--no-opt", "--debug-build"])
def test_desktop_rejects_unsupported_profile(flag: str) -> None:
    result = invoke("build", "--desktop", flag, "missing-app")
    assert result.returncode == 1
    assert "--desktop conflicts" in result.stderr


@pytest.mark.parametrize("target", ["macos-arm64", "macos-x64", "linux-arm64",
                                   "linux-x64", "linux-loongarch64", "linux-riscv64",
                                   "windows-x64", "windows-arm64"])
@pytest.mark.parametrize("flags,reference", PROFILES[:3],
                         ids=["default", "no-opt", "debug-build"])
def test_policy_across_hosted_targets(program: Path, tmp_path: Path, target: str,
                                     flags: list[str], reference: list[str]) -> None:
    products = []
    for index, options in enumerate((flags, reference)):
        binary = tmp_path / f"{target}-{index}"
        result = invoke("build", "--target", target, *options, str(program),
                        "-o", str(binary))
        assert result.returncode == 0 and not result.stderr, result.stderr
        if target.startswith("windows-"):
            binary = Path(str(binary) + ".exe")
        products.append(binary.read_bytes())
    assert products[0] == products[1]
    if target.startswith("macos-"):
        assert products[0][:4] == bytes.fromhex("cffaedfe")
    elif target.startswith("linux-"):
        assert products[0][:4] == b"\x7fELF"
    else:
        assert products[0][:2] == b"MZ"
    if "--debug-build" in flags and not target.startswith("windows-"):
        assert b"debug_line" in products[0]
