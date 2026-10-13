#!/usr/bin/env python3
"""Exercise an actual SDK archive from an unrelated, space-containing directory."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile


def run(args, *, cwd, env):
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError(f"{args}: exit {result.returncode}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def activate(prefix, cwd, env):
    if os.name == "nt":
        # Use native PowerShell, including for installations containing spaces.
        script = cwd / "activate.ps1"
        script.write_text('param($Root)\n. "$Root\\env.ps1"\n. "$Root\\env.ps1"\n'
                          'Write-Output ("XU_ENV_JSON=" + (@{XU_ROOT=$env:XU_ROOT; '
                          'XU_STDLIB_ROOT=$env:XU_STDLIB_ROOT; XUPATH=$env:XUPATH; '
                          'PATH=$env:Path} | ConvertTo-Json -Compress))\n')
        output = run(["pwsh", "-NoProfile", "-File", str(script), str(prefix)], cwd=cwd, env=env)
    else:
        script = 'source "$1/env.sh"; source "$1/env.sh"; "$2" -c \'import json,os; print("XU_ENV_JSON=" + json.dumps({k: os.environ[k] for k in ("XU_ROOT", "XU_STDLIB_ROOT", "XUPATH", "PATH")}))\''
        output = run(["bash", "-c", script, "sdk-activation", str(prefix), sys.executable], cwd=cwd, env=env)
    values = json.loads(next(line[len("XU_ENV_JSON="):] for line in output.splitlines() if line.startswith("XU_ENV_JSON=")))
    return env | values


def smoke(archive: Path, work: Path):
    extract = work / "unpacked SDK"
    extract.mkdir()
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as source:
            source.extractall(extract)
    else:
        with tarfile.open(archive) as source:
            source.extractall(extract, filter="data")
    bundle, = (p for p in extract.iterdir() if p.is_dir())
    manifest = json.loads((bundle / "bundle.json").read_text())
    prefix = work / "installed Xu SDK"
    project = work / "user project with spaces"
    project.mkdir()
    extra = work / "custom package search root"
    (extra / "sdk_probe").mkdir(parents=True)
    (extra / "sdk_probe/mod.xu").write_text('@sdk_probe\npub fn answer() int { << 42 }\n')
    env = dict(os.environ)
    for key in ("XU_ROOT", "XU_STDLIB_ROOT", "XUOS", "XUARCH", "XU_PACKAGES_ROOT", "XU_VSCODE_ROOT", "XU_BOOT_EXTRA"):
        env.pop(key, None)
    env.update(XU_SKIP_EDITOR_INSTALL="1", XUPATH=str(extra), XU_CACHE=str(work / "package cache"))
    if os.name == "nt":
        run(["pwsh", "-NoProfile", "-File", str(bundle / "install.ps1"), "-Prefix", str(prefix), "-NoModifyPath"], cwd=project, env=env)
    else:
        run(["bash", str(bundle / "install.sh"), "--prefix", str(prefix), "--no-modify-path", "--yes"], cwd=project, env=env)
    active = activate(prefix, project, env)
    entries = active["XUPATH"].split(os.pathsep)
    assert entries.count(str(extra)) == 1, entries
    assert entries.count(str(prefix / "src")) == 1, entries
    assert active["PATH"].split(os.pathsep).count(str(prefix / "bin")) == 1
    xu = shutil.which("xu", path=active["PATH"])
    assert xu and Path(xu).parent == prefix / "bin", xu
    assert manifest["version"] in run([xu, "--version"], cwd=project, env=active)
    (project / "main.xu").write_text('''@main
#strings
#sdk_probe
fn main() int {
    word := "installed"
    println(strings.to_upper(&word))
    println(sdk_probe.answer())
    << 0
}
''')
    (project / "xu.xun").write_text('module: main\nversion: !ver 0.1.0\nrequire:\n  sdk_probe: file:../custom package search root\n')
    assert run([xu, "run", "main.xu"], cwd=project, env=active).splitlines() == ["INSTALLED", "42"]
    program = project / ("user program.exe" if os.name == "nt" else "user program")
    run([xu, "build", "main.xu", "-o", str(program)], cwd=project, env=active)
    assert run([str(program)], cwd=project, env=active).splitlines() == ["INSTALLED", "42"]
    # Executable-relative stdlib discovery must work without activation.
    clean = active.copy()
    clean.pop("XU_STDLIB_ROOT", None)
    clean.pop("XU_ROOT", None)
    assert run([xu, "run", "main.xu"], cwd=project, env=clean).splitlines() == ["INSTALLED", "42"]
    # PATH lookup finds the compiler and its sibling tools from outside the SDK.
    run([xu, "fmt", "main.xu"], cwd=project, env=active)
    (project / "exit.xu").write_text('@main\nfn main() int { << 7 }\n')
    child = subprocess.run([xu, "run", "exit.xu"], cwd=project, env=active, capture_output=True, text=True, timeout=90)
    assert child.returncode == 7, (child.returncode, child.stderr)
    (project / "args.xu").write_text('@main\n#os\nfn main() int {\n    args := os.argv()\n    println(args[1])\n    println(args[2])\n    << 0\n}\n')
    assert run([xu, "run", "args.xu", "--", "argument with spaces", 'quote"value\\'], cwd=project, env=active).splitlines() == ["argument with spaces", 'quote"value\\']
    # Canonical bundled modules resolve from their installed manifest root.
    if (prefix / "packages/xu.xun").is_file():
        (project / "xu.xun").write_text('module: main\nversion: !ver 0.1.0\nrequire:\n  "github.com/xulang-org/packages": file:' + (prefix / "packages").as_posix() + '\n')
        (project / "main.xu").write_text('@main\nredis #"github.com/xulang-org/packages/redis"\nfn main() int {\n    value := redis.int_value(42)\n    answer := value.as_int() or (err) { << 1 }\n    println(answer)\n    << 0\n}\n')
        assert run([xu, "run", "main.xu"], cwd=project, env=active).strip() == "42"
        example = prefix / "examples/21_standalone_redis/main.xu"
        if example.is_file():
            run([xu, "check", str(example)], cwd=project, env=active)
    print(f"installed-sdk: PASS target={manifest['target']} lane={manifest['lane']} version={manifest['version']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="xu-sdk-smoke-") as directory:
        smoke(args.archive.resolve(), Path(directory).resolve())


if __name__ == "__main__":
    main()
