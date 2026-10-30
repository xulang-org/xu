#!/usr/bin/env python3
"""Run typed dispatcher, fallback and appearance assertions with product Xu."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''@main

#ui/widgets
#errors

struct Counts { exact int
    wildcard int
    fallback int }
fn exact(c $&Counts,s $&widgets.Screen,a &widgets.Action) string { c.exact += 1
    << "" }
fn replacement(c $&Counts,s $&widgets.Screen,a &widgets.Action) string { c.exact += 10
    << "" }
fn any_action(c $&Counts,s $&widgets.Screen,a &widgets.Action) string { c.wildcard += 1
    << "" }
fn fallback(c $&Counts,s $&widgets.Screen,a &widgets.Action) string { c.fallback += 1
    << "" }
fn failure(c $&Counts,s $&widgets.Screen,a &widgets.Action) string { << "handler failure" }
fn view_action(c $&Counts,v $&widgets.View,a &widgets.Action) string {
    c.exact += 1
    << ""
}
fn control_action(c $&Counts,s $&widgets.StyleSwitcher,a &widgets.Action) string {
    c.wildcard += 1
    << ""
}
fn action(id int,kind int) widgets.Action {
    << widgets.Action{id: id,kind: kind,needs_paint: false,request_focus: false,consumed: false,value: 0.0}
}
fn reject_exact(id int,kind int,d $&widgets.ActionDispatcher#Counts,widgets.Screen,widgets.Action) bool {
    d.on(id,kind,exact) or (err) { << true }
    << false
}
fn reject_any(id int,d $&widgets.ActionDispatcher#Counts,widgets.Screen,widgets.Action) bool {
    d.on_any(id,any_action) or (err) { << true }
    << false
}
fn handler_failure(ctx $&Counts,s $&widgets.Screen,d &widgets.ActionDispatcher#Counts,widgets.Screen,widgets.Action) bool {
    d.dispatch_or_fallback(&action(14,widgets.ACTION_CHANGE),ctx,s) or (err) {
        assert(err.msg() == "handler failure")
        << true }
    << false
}
fn smoke() int {
    // No native resources are attached: these callbacks only count calls.
    $screen := widgets.Screen{}
    $ctx := Counts{exact: 0,wildcard: 0,fallback: 0}
    $d := widgets.action_dispatcher(&ctx,&screen)
    d.on_any(12,any_action) or >>
    d.on(12,widgets.ACTION_ACTIVATE,exact) or >>
    assert(d.dispatch(&action(12,widgets.ACTION_ACTIVATE),$&ctx,$&screen) or >>)
    assert(ctx.exact == 1 && ctx.wildcard == 0)
    d.on(12,widgets.ACTION_ACTIVATE,replacement) or >>
    assert(d.dispatch(&action(12,widgets.ACTION_ACTIVATE),$&ctx,$&screen) or >>)
    assert(ctx.exact == 11 && ctx.wildcard == 0)
    assert(d.dispatch(&action(12,widgets.ACTION_CHANGE),$&ctx,$&screen) or >>)
    assert(ctx.wildcard == 1)
    assert(!(d.dispatch(&action(13,widgets.ACTION_ACTIVATE),$&ctx,$&screen) or >>))
    d.set_fallback(fallback)
    assert(d.dispatch_or_fallback(&action(13,widgets.ACTION_ACTIVATE),$&ctx,$&screen) or >>)
    assert(ctx.fallback == 1)
    assert(d.dispatch_or_fallback(&action(12,widgets.ACTION_ACTIVATE),$&ctx,$&screen) or >>)
    assert(ctx.fallback == 1 && ctx.exact == 21)
    d.on(14,widgets.ACTION_CHANGE,failure) or >>
    assert(handler_failure($&ctx,$&screen,&d))
    assert(ctx.fallback == 1)
    for id in [-1,0,2147483648] {
        assert(reject_exact(id,widgets.ACTION_CHANGE,$&d))
        assert(reject_any(id,$&d))
        assert(!(d.dispatch(&action(id,widgets.ACTION_CHANGE),$&ctx,$&screen) or >>))
    }
    for kind in [-1,widgets.ACTION_NONE,10,29,34,39,44,2147483647] {
        assert(reject_exact(12,kind,$&d))
        assert(!(d.dispatch(&action(12,kind),$&ctx,$&screen) or >>))
    }
    d.on(2147483647,widgets.ACTION_CHART_LEGEND,exact) or >>
    assert(d.dispatch(&action(2147483647,widgets.ACTION_CHART_LEGEND),$&ctx,$&screen) or >>)
    // Appearance is independent of the table, including registered fallback.
    styles := widgets.dark_styles()
    appearance := widgets.screen_appearance(&styles,true) or >>
    screen.apply_appearance(&appearance) or >>
    screen.apply_appearance(&appearance) or >>
    assert(screen.styles().same_as(&styles) && screen.reduced_motion())
    assert(screen.take_actions().len == 0)
    assert(ctx.exact == 22 && ctx.wildcard == 1 && ctx.fallback == 1)
    d.clear_fallback()
    assert(!(d.dispatch_or_fallback(&action(99,widgets.ACTION_CHANGE),$&ctx,$&screen) or >>))
    // The same typed table serves retained View and standalone-control loops.
    $view := widgets.View{}
    $vd := widgets.action_dispatcher(&ctx,&view)
    vd.on(1,widgets.ACTION_SUBMIT,view_action) or >>
    assert(vd.dispatch(&action(1,widgets.ACTION_SUBMIT),$&ctx,$&view) or >>)
    $switcher := widgets.style_switcher()
    $cd := widgets.action_dispatcher(&ctx,&switcher)
    cd.on_any(2,control_action) or >>
    assert(cd.dispatch(&action(2,widgets.ACTION_CHANGE),$&ctx,$&switcher) or >>)
    assert(!(cd.dispatch(&action(2,widgets.ACTION_NONE),$&ctx,$&switcher) or >>))
    assert(ctx.exact == 23 && ctx.wildcard == 2)
    println("ui-action-dispatcher: PASS")
    << 0
}
fn main() int { << smoke() or (err) { eprintln(err.msg())
    << 1 } }
'''


def main():
    compiler = Path(os.environ.get("XU", str(ROOT / "bin/xu"))).resolve()
    env = dict(os.environ, XU_ROOT=str(ROOT), XU_STDLIB_ROOT=str(ROOT / "src"), XUPATH="", XU_UI_SIM="1")
    with tempfile.TemporaryDirectory(prefix="xu-ui-actions-") as tmp:
        source = Path(tmp) / "main.xu"
        binary = Path(tmp) / "smoke"
        source.write_text(SOURCE)
        subprocess.run([str(compiler), "build", str(source), "-o", str(binary)],
                       cwd=ROOT, env=env, check=True, timeout=180)
        subprocess.run([str(binary)], cwd=ROOT, env=env, check=True, timeout=20)


if __name__ == "__main__":
    main()
