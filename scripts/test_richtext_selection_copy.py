#!/usr/bin/env python3
"""Smoke: RichDocument.selected_text matches selection for clipboard copy."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SOURCE = r'''@main

#ui/widgets

fn main() int {
    $doc := widgets.rich_document()
    p0 := doc.append_paragraph(0)
    doc.append_span(p0, widgets.text_span("Hello ", widgets.SPAN_NORMAL)) or (err) {
        println("FAIL: append hello")
        << 1
    }
    doc.append_span(p0, widgets.text_span("World", widgets.SPAN_BOLD)) or (err) {
        println("FAIL: append world")
        << 1
    }
    p1 := doc.append_paragraph(0)
    doc.append_span(p1, widgets.text_span("Next", widgets.SPAN_NORMAL)) or (err) {
        println("FAIL: append next")
        << 1
    }
    plain := doc.to_plain_text()
    // plain == "Hello World\nNext"; select "World\nNe"
    doc.set_selection(6, 14)
    if !doc.has_selection() {
        println("FAIL: expected selection")
        << 1
    }
    selected := doc.selected_text()
    if selected != "World\nNe" {
        println("FAIL: selected_text got '" + selected + "' plain='" + plain + "'")
        << 1
    }
    range := doc.selection_range()
    if range.start != 6 || range.end != 14 {
        println("FAIL: selection_range")
        << 1
    }
    println("richtext-selection-copy: PASS")
    << 0
}
'''


def main() -> None:
    compiler = Path(os.environ.get("XU", str(ROOT / "bin" / "xu")))
    env = os.environ.copy()
    env.setdefault("XU_ROOT", str(ROOT))
    env.setdefault("XU_STDLIB_ROOT", str(ROOT / "src"))
    env["XUPATH"] = str(ROOT / "src") + ((":" + env["XUPATH"]) if env.get("XUPATH") else "")
    with tempfile.TemporaryDirectory(prefix="xu-richtext-sel-") as tmp:
        source = Path(tmp) / "main.xu"
        binary = Path(tmp) / "smoke"
        source.write_text(SOURCE)
        subprocess.run([str(compiler), "build", str(source), "-o", str(binary)], check=True, env=env)
        subprocess.run([str(binary)], check=True, env=env)


if __name__ == "__main__":
    main()
