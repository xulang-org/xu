#!/usr/bin/env python3
"""Exercise pointer dispatch and Popover focus, close, and cancellation rules."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import subprocess
from test_windows_workers import WindowsTemporaryDirectory

SOURCE = r'''@main
#ui
#ui/widgets
#time
fn probe() int {
    ready := ui.Event{kind:ui.EV_CANVAS_READY,window_id:1,menu_id:"canvas_ready\t1\t1\t1",width:800,height:600}
    $screen := widgets.screen(&ready) or >>
    id := screen.button("Test") or >>
    screen.place(id,24.0,24.0,200.0,40.0) or >>
    $event := ui.InputEvent{kind:ui.EV_POINTER_DOWN,window_id:1,canvas_id:1,generation:1,x:40.0,y:40.0,dx:0.0,dy:0.0,button:1,buttons:1,modifiers:0,key:0,scan:0,repeat:0,click_count:1,time_ns:0}
    first := screen.dispatch(&event) or >>
    _ := screen.advance(time.instant()) or >>
    screen.place(id,24.0,24.0,200.0,40.0) or >>
    event.kind = ui.EV_POINTER_UP
    event.buttons = 0
    actions := screen.dispatch(&event) or >>
    println("actions=" + str(actions.len))
    for action in actions { if action.kind == widgets.ACTION_ACTIVATE && action.id == id { << 0 } }
    << 1
}
fn popover_probe() int {
    ready := ui.Event{kind:ui.EV_CANVAS_READY,window_id:1,menu_id:"canvas_ready\t1\t1\t1",width:800,height:600}
    $screen := widgets.screen(&ready) or >>
    screen.set_reduced_motion(true)
    trigger := screen.button("Open") or >>
    screen.place(trigger,24.0,24.0,200.0,40.0) or >>
    panel := screen.popover(trigger,"") or >>
    screen.place(panel,0.0,0.0,300.0,180.0) or >>
    child := screen.button("Apply") or >>
    screen.set_parent(child,panel) or >>
    screen.place(child,20.0,20.0,120.0,40.0) or >>
    screen.open(panel) or >>
    actions := screen.xacp_act(child,"click","",false) or >>
    if actions.len != 1 || actions[0].kind != widgets.ACTION_ACTIVATE || actions[0].id != child { eprintln("Popover child activation failed")
        << 3 }
    screen.close_overlay(panel) or >>
    closed := screen.xacp_act(child,"click","",false) or >>
    if closed.len != 0 { eprintln("Closed Popover received input")
        << 4 }
    screen.open(panel) or >>
    cancel := ui.InputEvent{kind:ui.EV_POINTER_CANCEL,window_id:1,canvas_id:1,generation:1,x:0.0,y:0.0,dx:0.0,dy:0.0,button:0,buttons:0,modifiers:0,key:0,scan:0,repeat:0,click_count:0,time_ns:0}
    _ := screen.dispatch(&cancel) or >>
    cancelled := screen.xacp_act(child,"click","",false) or >>
    if cancelled.len != 0 { eprintln("Cancelled Popover received input")
        << 5 }
    screen.open(panel) or >>
    reopened := screen.xacp_act(child,"click","",false) or >>
    if reopened.len != 1 || reopened[0].kind != widgets.ACTION_ACTIVATE { eprintln("Popover could not reopen")
        << 6 }
    println("Popover lifecycle regression passed")
    << 0
}
fn checks() int {
    result := probe() or >>
    if result != 0 { << result }
    << popover_probe() or >>
}
fn main() int { << checks() or (err) { eprintln(err.msg())
    << 2 } }
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--target", choices=("windows-arm64", "windows-x64"))
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("requires a Windows host")
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, XU_ROOT=str(root), XU_STDLIB_ROOT=str(root / "src"), XUPATH="", XU_UI_SIM="1", XU_UI_TRACE_INPUT="0")
    with WindowsTemporaryDirectory(prefix="xu-windows-controls-") as folder:
        workspace = Path(folder)
        source = workspace / "main.xu"
        source.write_text(SOURCE, encoding="utf-8")
        executable = workspace / "controls.exe"
        target = ["--target", args.target] if args.target else []
        subprocess.run([str(args.compiler.resolve()), "build", str(source), *target, "-o", str(executable)], env=env, check=True, timeout=180)
        subprocess.run([str(executable)], env=env, check=True, timeout=30)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
