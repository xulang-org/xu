#!/usr/bin/env python3
"""Exercise an actual SDK archive from an unrelated, space-containing directory."""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile


def run(args, *, cwd, env):
    try:
        result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, timeout=180)
    except subprocess.TimeoutExpired as error:
        def text(value):
            return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
        raise RuntimeError(f"{args}: timed out after {error.timeout}s\n"
                           f"{text(error.stdout)}\n{text(error.stderr)}") from error
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


def smoke(archive: Path | None, work: Path, native_setup: bool = False, installer: Path | None = None):
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

    if installer:
        run([str(installer), "--prefix", str(prefix), "--yes"], cwd=project, env=env)
        manifest_file = prefix / "bundle.json"
        manifest = json.loads(manifest_file.read_text()) if manifest_file.is_file() else {"version": "", "target": "host", "lane": "product"}
    else:
        assert archive is not None, "archive must be provided when installer is None"
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
        if native_setup:
            setup = bundle / ("xu-setup.exe" if os.name == "nt" else "xu-setup")
            run([str(setup), "--prefix", str(prefix), "--yes"], cwd=project, env=env)
        elif os.name == "nt":
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
    # SDK root discovery is independent of external GUI toolchain availability.
    # Doctor may report missing GTK/Swift/MinGW here, but must locate this SDK
    # before probing those host dependencies. Exercise direct PATH and CLI use.
    for command in ([xu, "doctor"], ["xu-doctor"]):
        doctor = subprocess.run([*command, "--target", manifest["target"]], cwd=project,
                                env=clean, text=True, capture_output=True, timeout=90)
        match = re.search(r"(?m)^  \[ok\]\s+Xu SDK root\s+(.+)$", doctor.stdout)
        assert match, (doctor.returncode, doctor.stdout, doctor.stderr)
        assert Path(match.group(1).strip()).resolve() == prefix.resolve(), doctor.stdout
    # Exercise the actual desktop entry and sibling Doctor invocation. The small
    # project deliberately has no icon, so it stops before external GUI builds.
    desktop = subprocess.run([xu, "build", str(project), "--desktop", "--no-webview",
                              "--target", manifest["target"]], cwd=project,
                             env=clean, text=True, capture_output=True, timeout=90)
    match = re.search(r"(?m)^  \[ok\]\s+Xu SDK root\s+(.+)$", desktop.stdout)
    assert match, (desktop.returncode, desktop.stdout, desktop.stderr)
    assert Path(match.group(1).strip()).resolve() == prefix.resolve(), desktop.stdout
    stale = work / "stale checkout"
    (stale / "src/ui/host").mkdir(parents=True)
    for marker in ("macos_host.swift", "xu_content_abi.h"):
        (stale / "src/ui/host" / marker).write_text("")
    doctor = subprocess.run([xu, "doctor", "--target", manifest["target"]], cwd=project,
                            env=clean | {"XU_ROOT": str(stale)}, text=True, capture_output=True, timeout=90)
    match = re.search(r"(?m)^  \[ok\]\s+Xu SDK root\s+(.+)$", doctor.stdout)
    assert match and Path(match.group(1).strip()).resolve() == prefix.resolve(), doctor.stdout
    # PATH lookup finds the compiler and its sibling tools from outside the SDK.
    run([xu, "fmt", "main.xu"], cwd=project, env=active)
    (project / "exit.xu").write_text('@main\nfn main() int { << 7 }\n')
    child = subprocess.run([xu, "run", "exit.xu"], cwd=project, env=active, capture_output=True, text=True, timeout=90)
    assert child.returncode == 7, (child.returncode, child.stderr)
    (project / "args.xu").write_text('@main\n#os\nfn main() int {\n    args := os.argv()\n    println(args[1])\n    println(args[2])\n    << 0\n}\n')
    for arguments in (["argument with spaces", 'quote"value\\'], ["", ""], ['space and \\', 'two\\\\"quotes']):
        actual = run([xu, "run", "args.xu", "--", *arguments], cwd=project, env=active).splitlines()
        assert actual == arguments, (arguments, actual)
    # Exercise optimized compilation and child execution in the installed CLI.
    # All input is created in the user's temporary project, independent of tests/.
    (project / "loop.xu").write_text('@main\nfn main() int {\n    mut total := 0\n    mut i := 0\n    while i < 32768 {\n        total = total + i\n        i = i + 1\n    }\n    println(total)\n    << 0\n}\n')
    for level in ("-O0", "-O2", "-O3"):
        run([xu, "build", "loop.xu", level, "-o", str(program)], cwd=project, env=active)
        assert run([str(program)], cwd=project, env=active).strip() == "536854528"
    # Native map adapters must preserve the coroutine context when calling
    # ordinary Xu hashing and growth policy functions with entry stack guards.
    (project / "map_worker.xu").write_text('''@main
fn worker(done chan int) {
    mut integers := map[int]int{}
    mut names := map[string]int{}
    for i in 0:128 {
        integers[i] = i * 3
        names[str(i)] = i * 5
    }
    mut total := 0
    for i in 0:128 {
        total += integers[i]
        total += names[str(i)]
    }
    done <- total
}
fn main() {
    done := chan int{cap: 1}
    xu worker(done)
    println(<-done)
}
''')
    for level in ("-O0", "-O2", "-O3"):
        run([xu, "build", "map_worker.xu", level, "-o", str(program)], cwd=project, env=active)
        assert run([str(program)], cwd=project, env=active).strip() == "65024"
    # Canonical bundled modules resolve from their installed manifest root.
    if (prefix / "packages/xu.xun").is_file():
        (project / "xu.xun").write_text('module: main\nversion: !ver 0.1.0\nrequire:\n  "github.com/xulang-org/packages": file:' + (prefix / "packages").as_posix() + '\n')
        (project / "main.xu").write_text('@main\nredis #"github.com/xulang-org/packages/redis"\nfn main() int {\n    value := redis.int_value(42)\n    answer := value.as_int() or (err) { << 1 }\n    println(answer)\n    << 0\n}\n')
        assert run([xu, "run", "main.xu"], cwd=project, env=active).strip() == "42"
        example = prefix / "examples/21_standalone_redis/main.xu"
        if example.is_file():
            run([xu, "check", str(example)], cwd=project, env=active)
    # Imported constant names are checked through real installed examples.
    # Declaration-only migration can leave the compiler and hello-world smoke
    # green while the bundled UI and service examples no longer type-check.
    if (prefix / "examples").is_dir():
        examples = [
            "16_ui_webview/draw/main.xu",
            "16_ui_webview/widgets/main.xu",
            "16_ui_webview/style_gallery/main.xu",
            "16_ui_webview/component_workshop/main.xu",
        ]
        if (prefix / "packages/xu.xun").is_file():
            examples += ["47_standalone_websocket/main.xu", "49_standalone_dns/main.xu"]
        for relative in examples:
            example = prefix / "examples" / relative
            if not example.is_file():
                raise RuntimeError(f"SDK example is missing: {relative}")
            run([xu, "check", str(example)], cwd=project, env=active)
            print(f"installed-sdk: example-check PASS {relative}")
    print(f"installed-sdk: PASS target={manifest['target']} lane={manifest['lane']} version={manifest['version']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="path to SDK archive (.tar.gz or .zip)")
    parser.add_argument("--installer", type=Path, help="path to standalone setup installer executable")
    parser.add_argument("--native-setup", action="store_true", help="verify the native installer instead of the shell script")
    args = parser.parse_args()
    if not args.archive and not args.installer:
        parser.error("either --archive or --installer is required")
    with tempfile.TemporaryDirectory(prefix="xu-sdk-smoke-") as directory:
        smoke(
            args.archive.resolve() if args.archive else None,
            Path(directory).resolve(),
            args.native_setup,
            installer=args.installer.resolve() if args.installer else None,
        )


if __name__ == "__main__":
    main()
