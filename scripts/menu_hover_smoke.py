#!/usr/bin/env python3
"""Verify menu hover accent styling and contrast in dark, light, and contrast themes."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''@main

#ui
#ui/draw
#ui/layout
#ui/widgets
#time
#errors

fn box(x f64,y f64,w f64,h f64) layout.Rect {
    << layout.Rect{x: x,y: y,width: w,height: h}
}

fn smoke() int {
    // 1. Theme-level menu_style assertions
    dark := widgets.dark_styles()
    dark_menu := dark.menu_style()
    assert((dark_menu.palette.normal.value() & 255) == 0)
    assert(dark_menu.palette.hovered.value() == dark.button.palette.accent.value())

    dark_normal := dark_menu.resolve(0)
    assert((dark_normal.background.value() & 255) == 0)
    assert(dark_normal.foreground.value() == dark.button.palette.foreground.value())

    dark_hover := dark_menu.resolve(widgets.STATE_HOVERED)
    assert(dark_hover.background.value() == dark.button.palette.accent.value())
    assert(dark_hover.foreground.value() == dark.button.palette.on_accent.value())
    // Contrast guarantee: accent background must NOT match card normal background
    assert(dark_hover.background.value() != dark.card_style().palette.normal.value())

    dark_press := dark_menu.resolve(widgets.STATE_PRESSED)
    assert(dark_press.foreground.value() == dark.button.palette.on_accent.value())

    dark_disabled := dark_menu.resolve(widgets.STATE_DISABLED | widgets.STATE_HOVERED)
    assert(dark_disabled.foreground.value() == dark.button.palette.muted.value())

    // 2. Light theme
    light := widgets.light_styles()
    light_menu := light.menu_style()
    light_hover := light_menu.resolve(widgets.STATE_HOVERED)
    assert(light_hover.background.value() == light.button.palette.accent.value())
    assert(light_hover.foreground.value() == light.button.palette.on_accent.value())
    assert(light_hover.background.value() != light.card_style().palette.normal.value())

    // 3. Contrast theme
    contrast := widgets.contrast_styles()
    contrast_menu := contrast.menu_style()
    contrast_hover := contrast_menu.resolve(widgets.STATE_HOVERED)
    assert(contrast_hover.background.value() == contrast.button.palette.accent.value())
    assert(contrast_hover.foreground.value() == contrast.button.palette.on_accent.value())

    // 4. Menu instance popup_style integration
    context := draw.default_context()
    identity := ui.CanvasEvent{window_id: 1,canvas_id: 1,generation: 1}
    bounds := box(20.0,20.0,120.0,36.0)
    items := [widgets.menu_item(1,"Open"),widgets.menu_item(2,"Save"),widgets.menu_item(3,"Exit")]
    $m := widgets.menu(&context,&identity,1,&bounds,"File",&items,widgets.MENU_DROPDOWN,0) or >>
    assert(!m.is_open())
    m.apply_styles(&dark) or >>

    println("menu-hover-smoke: PASS")
    << 0
}

fn main() int {
    << smoke() or (err) {
        eprintln(err.msg())
        << 1
    }
}
'''


def main():
    compiler = Path(os.environ.get("XU", str(ROOT / "bin/xu"))).resolve()
    env = dict(os.environ, XU_ROOT=str(ROOT), XU_STDLIB_ROOT=str(ROOT / "src"), XUPATH="", XU_UI_SIM="1")
    with tempfile.TemporaryDirectory(prefix="xu-menu-hover-") as tmp:
        source = Path(tmp) / "main.xu"
        binary = Path(tmp) / "smoke"
        source.write_text(SOURCE)
        subprocess.run([str(compiler), "build", str(source), "-o", str(binary)],
                       cwd=ROOT, env=env, check=True, timeout=180)
        subprocess.run([str(binary)], cwd=ROOT, env=env, check=True, timeout=20)


if __name__ == "__main__":
    main()
