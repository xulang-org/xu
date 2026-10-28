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
    # Windows CreateProcess does not use the supplied child environment for
    # bare-command lookup. Resolve the activated PATH explicitly on every OS.
    path_doctor = shutil.which("xu-doctor", path=clean["PATH"])
    assert path_doctor and Path(path_doctor).resolve().parent == (prefix / "bin").resolve(), path_doctor
    for command in ([xu, "doctor"], [path_doctor]):
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
    # Aggregate container borrows cross an ascending-buffer / descending-frame
    # ABI boundary. Verify shared calls, mutable methods, function values and
    # exceptional writeback without corrupting adjacent packed records.
    (project / "borrow_record.xu").write_text('''@main
#errors
struct Record { value int
 guard int
 label string }
fn read(r &Record) int { << r.value + r.guard + r.label.len }
fn change(r &mut Record) int { r.value += 11
 r.label = "new" + "-field"
 << 0 }
fn (r &mut Record) bump() int { r.value += 7
 << r.value }
fn fail_after_change(r &mut Record) int { r.value += 3
 >> errors.new("expected") }
struct Packed { a i32
 b i32
 c u8 }
fn (p &mut Packed) bump() int { p.a += i32(2)
 p.c += u8(1)
 << int(p.a) + int(p.b) + int(p.c) }
struct@ Mutator { fn change(&mut Record) int }
struct Worker { n int }
fn (w Worker) change(r &mut Record) int { << change(r) }
struct Tiny { a u8
 b u8 }
fn main() int {
 mut records := [Record{value: 1,guard: 100,label: "old"},Record{value: 2,guard: 200,label: "old"}]
 i := 1
 r := mut &records[i]
 println(read(&*r))
 println(r.bump())
 f := change
 _ := f(r)
 for once in 0:1 { _ := fail_after_change(r) or (err) { println(err.msg())
 -> } }
 println(read(&*r))
 println(records[0].value)
 println(records[0].guard)
 println(records[0].label)
 mut packed := [Packed{a: 1,b: 2,c: 3},Packed{a: 10,b: 20,c: 30}]
 p := mut &packed[i]
 println(p.bump())
 println(int(packed[0].a))
 println(int(packed[0].c))
 println(int(packed[1].a))
 println(int(packed[1].c))
 mut values := map[int]Record{}
 values[3] = Record{value: 4,guard: 50,label: "map"}
 m := mut &values[3]
 println(m.bump())
 println(read(&*m))
 dynamic := Mutator(Worker{n: 1})
 println(dynamic.change(m))
 read_fn := read
 println(read_fn(&*m))
 packed[1] = Packed{a: 20,b: 30,c: 40}
 copy := packed[1]
 println(int(copy.c))
 packed[1] = copy
 packed.push(Packed{a: 50,b: 60,c: 70})
 println(packed.len)
 mut last := mut &packed[2]
 println(last.bump())
 println(int(last.c))
 println(int(packed[1].c))
 mut tiny := [Tiny{a: 1,b: 2},Tiny{a: 3,b: 4},Tiny{a: 5,b: 6}]
 tiny[1] = Tiny{a: 7,b: 8}
 copied := tiny[1]
 println(int(copied.b))
 println(int(tiny[0].a))
 println(int(tiny[0].b))
 println(int(tiny[2].a))
 println(int(tiny[2].b))
 << 0
}
''')
    for level in ("-O0", "-O2", "-O3"):
        run([xu, "build", "borrow_record.xu", level, "-o", str(program)], cwd=project, env=active)
        actual = run([str(program)], cwd=project, env=active).splitlines()
        assert actual == ["205", "9", "expected", "232", "1", "100", "old", "63", "1", "3", "12", "31", "11", "64", "0", "81", "40", "3", "183", "71", "40", "8", "1", "2", "5", "6"], actual
    # A frame view cannot be returned as a borrowed container identity.
    (project / "borrow_escape.xu").write_text('''@main
fn identity(s &string) &string { << s }
fn main() int {
    words := ["one", "two"]
    i := 1
    r := identity(&words[i])
    println(r.len)
    << 0
}
''')
    rejected = subprocess.run([xu, "build", "borrow_escape.xu", "-o", str(program)], cwd=project,
                              env=active, text=True, capture_output=True, timeout=90)
    assert rejected.returncode != 0 and "container aggregate borrow cannot escape" in rejected.stderr, (rejected.stdout, rejected.stderr)
    # Passive help has deterministic hover delay, dismissal and edge placement;
    # this exercises the installed widgets without opening a native GUI.
    (project / "tooltip_state.xu").write_text('''@main
#ui
#ui/widgets
#ui/layout
#time
#errors
fn expect(value bool,message string) int {
    if !value { >> errors.new(message) }
    << 0
}
fn input(kind int,x f64,y f64,now time.Instant) ui.InputEvent {
    << ui.InputEvent{kind: kind,window_id: 1,canvas_id: 1,generation: 1,x: x,y: y,dx: 0.0,dy: 0.0,
        button: ui.BUTTON_LEFT,buttons: 0,modifiers: 0,key: 0,scan: 0,repeat: 0,click_count: 0,time_ns: now.nanoseconds()}
}
fn verify() int {
    identity := ui.CanvasEvent{window_id: 1,canvas_id: 1,generation: 1}
    anchor := layout.Rect{x: 140.0,y: 180.0,width: 80.0,height: 40.0}
    size := layout.Size{width: 120.0,height: 60.0}
    viewport := layout.Rect{x: 0.0,y: 0.0,width: 400.0,height: 400.0}
    mut tip := widgets.tooltip(&identity,10,&anchor,&size,&viewport) or >>
    start := time.instant()
    move := input(ui.EV_POINTER_MOVE,160.0,200.0,start)
    _ := tip.input(&move) or >>
    expect(!tip.is_open(),"hover opened before delay") or >>
    _ := tip.tick(start.add(time.milliseconds(499) or >>) or >>,true) or >>
    expect(!tip.is_open(),"hover opened at 499ms") or >>
    shown := start.add(time.milliseconds(500) or >>) or >>
    _ := tip.tick(shown,true) or >>
    expect(tip.is_open(),"hover did not open at 500ms") or >>
    bounds := tip.bounds()
    expect(bounds.y + bounds.height <= anchor.y && bounds.x == 120.0,"default top/center placement") or >>
    click := input(ui.EV_POINTER_DOWN,160.0,200.0,shown)
    _ := tip.input(&click) or >>
    expect(!tip.is_open(),"click did not dismiss") or >>
    _ := tip.input(&move) or >>
    _ := tip.tick(shown.add(time.seconds(1) or >>) or >>,true) or >>
    expect(!tip.is_open(),"click suppression lost before leaving") or >>
    leave := input(ui.EV_POINTER_MOVE,380.0,380.0,shown)
    _ := tip.input(&leave) or >>
    _ := tip.input(&move) or >>
    _ := tip.tick(shown.add(time.seconds(1) or >>) or >>,true) or >>
    expect(tip.is_open(),"hover did not reset after leaving") or >>
    _ := tip.input(&leave) or >>
    expect(!tip.is_open(),"hover leave did not close") or >>
    tip.set_focus(true,shown) or >>
    expect(tip.is_open(),"keyboard focus did not open") or >>
    mut escape := input(ui.EV_KEY_DOWN,0.0,0.0,shown)
    escape.key = ui.KEY_ESCAPE
    _ := tip.input(&escape) or >>
    expect(!tip.is_open(),"Escape did not dismiss") or >>
    tip.set_focus(true,shown) or >>
    expect(!tip.is_open(),"Escape suppression lost") or >>
    tip.set_focus(false,shown) or >>
    tip.set_focus(true,shown) or >>
    expect(tip.is_open(),"refocus did not reset suppression") or >>
    for side in 0:4 {
        mut placement := widgets.overlay_placement()
        placement.side = side
        placement.align = widgets.OVERLAY_CENTER
        tip.set_placement(&placement) or >>
        b := tip.bounds()
        if side == widgets.OVERLAY_BOTTOM { expect(b.y >= anchor.y + anchor.height,"bottom placement") or >> }
        if side == widgets.OVERLAY_TOP { expect(b.y + b.height <= anchor.y,"top placement") or >> }
        if side == widgets.OVERLAY_LEFT { expect(b.x + b.width <= anchor.x,"left placement") or >> }
        if side == widgets.OVERLAY_RIGHT { expect(b.x >= anchor.x + anchor.width,"right placement") or >> }
    }
    mut placement := widgets.overlay_placement()
    placement.side = widgets.OVERLAY_TOP
    tip.set_placement(&placement) or >>
    edge := layout.Rect{x: 4.0,y: 4.0,width: 80.0,height: 40.0}
    tip.set_geometry(&edge,&size,&viewport) or >>
    flipped := tip.bounds()
    expect(flipped.y >= edge.y + edge.height,"edge did not flip") or >>
    tip.set_enabled(false) or >>
    expect(!tip.is_open() && !tip.is_visible(),"disabled tooltip stayed visible") or >>
    println("tooltip state and placement PASS")
    << 0
}
fn main() int { << verify() or (err) { eprintln(err.msg())
    << 1 } }
''')
    run([xu, "build", "tooltip_state.xu", "-O2", "-o", str(program)], cwd=project, env=active)
    assert run([str(program)], cwd=project, env=active).strip() == "tooltip state and placement PASS"
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
