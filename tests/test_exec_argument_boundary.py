"""Exercise real exec argv framing and Windows CRT escaping with a child."""
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import errno

import pytest

ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get("XU", ROOT / "bin/xu"))


@pytest.mark.parametrize("target", [None, "windows-x64", "linux-x64"])
def test_real_exec_roundtrip_and_nul_rejection(tmp_path, target):
    windows = target == "windows-x64"
    linux_container = target == "linux-x64" and platform.system() != "Linux"
    image = os.environ.get("XU_LINUX_EXEC_IMAGE")
    if linux_container and not image:
        pytest.skip("Linux execution on this host requires an explicit local test image")
    wine = shutil.which("wine")
    if windows and platform.system() != "Windows" and not wine:
        pytest.skip("Windows execution requires Wine or Windows")
    child = tmp_path / "child with spaces.exe" if windows else tmp_path / "child with spaces"
    parent = tmp_path / "parent.exe" if windows else tmp_path / "parent"
    (tmp_path / "child.xu").write_text('''@main
#os
fn main() int {
    args := os.argv()
    for i in 1:args.len { println(args[i]) }
    << 0
}
''')
    child_path = str(child)
    if windows and platform.system() != "Windows":
        child_path = "Z:" + str(child).replace("/", "\\")
    # Runs of backslashes before quotes, trailing backslashes, and empty args
    # are the Windows CRT cases; Unix must preserve these literal bytes too.
    values = ['', 'space end\\', 'back\\\\"quote', '$(printf injected)', "a'b", 'tab\tend']
    arguments = ", ".join(json.dumps(x).replace("$", "$$") for x in values)
    source = '''@main
#os/exec
fn rejects_run(c &exec.Cmd) bool {
    c.run() or (err) { << true }
    << false
}
fn rejects_output(c &exec.Cmd) bool {
    c.output() or (err) { << true }
    << false
}
fn rejects_combined(c &exec.Cmd) bool {
    c.combined_output() or (err) { << true }
    << false
}
fn rejects_start(c &mut exec.Cmd) bool {
    c.start() or (err) { << true }
    << false
}
fn main() int {
    child := exec.command(CHILD, ARGUMENTS)
    output := child.output() or (err) { println(err.msg())
        << 1 }
    println(output)
    bad := string_from_bytes([97, 0, 98])
    mut reject_count := 0
    c := exec.command(CHILD, bad)
    if rejects_run(&c) { reject_count = reject_count + 1 }
    if rejects_output(&c) { reject_count = reject_count + 1 }
    if rejects_combined(&c) { reject_count = reject_count + 1 }
    mut async_cmd := exec.command(CHILD, string_from_bytes([97, 0, 98]))
    if rejects_start(mut &async_cmd) { reject_count = reject_count + 1 }
    println(reject_count)
    << 0
}
'''.replace("CHILD", json.dumps(child_path)).replace("ARGUMENTS", arguments)
    (tmp_path / "parent.xu").write_text(source)
    target_args = ["--target", target] if target else []
    for name, output in (("child", child), ("parent", parent)):
        result = subprocess.run([str(XU), "build", str(tmp_path / (name + ".xu")), *target_args, "-o", str(output)], cwd=ROOT, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
    env = dict(os.environ)
    argv = [str(parent)]
    if windows and platform.system() != "Windows":
        argv = [wine, str(parent)]
        env.update(WINEDEBUG="-all", WINEPREFIX=str(ROOT / "target/wineprefix"))
    if linux_container:
        argv = ["docker", "run", "--rm", "--pull=never", "--platform", "linux/amd64",
                "--mount", "type=bind,src=" + str(tmp_path) + ",dst=" + str(tmp_path) + ",readonly",
                "--workdir", str(tmp_path), "--entrypoint", str(parent), image]
    try:
        result = subprocess.run(argv, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    except OSError as exc:
        if windows and exc.errno in {errno.ENOEXEC, 86}:
            pytest.skip("Windows executable compiled; installed Wine has an incompatible CPU architecture")
        raise
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == values + ["", "4"], repr(result.stdout)


def test_windows_encoder_against_python_crt_reference(tmp_path):
    values = ['', 'space end\\', 'back\\\\"quote', 'tab\tend', 'plain', '"quoted"', 'a\\\\\\"b']
    literals = ", ".join(json.dumps(value) for value in values)
    # A same-package harness calls the actual stdlib encoder, including its
    # private entry point. It does not copy or reimplement the encoder.
    hook = tmp_path / "os/exec/extra.xu"
    hook.parent.mkdir(parents=True)
    hook.write_text('''@os/exec
pub fn encoding_test() {
    values := [VALUES]
    for i in 0:values.len { println(win_quote(values[i])) }
}
'''.replace("VALUES", literals))
    (tmp_path / "main.xu").write_text("@main\n#os/exec\nfn main() int { exec.encoding_test()\n << 0 }\n")
    output = tmp_path / "encoder"
    result = subprocess.run([str(XU), "build", str(tmp_path / "main.xu"), str(hook), str(ROOT / "src/os/exec/mod.xu"), "-o", str(output)], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    rows = subprocess.check_output([str(output)], text=True, timeout=10).splitlines()
    for value, encoded in zip(values, rows, strict=True):
        reference = subprocess.list2cmdline([value])
        # Python uses backslash escapes without surrounding quotes for the
        # quote-only case. Feed a space to require the same quoted CRT form.
        if '"' in value and not any(c in value for c in (' ', '\t')):
            reference = subprocess.list2cmdline([value + ' '])[:-2] + '"'
        assert encoded == reference
