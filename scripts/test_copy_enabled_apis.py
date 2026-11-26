#!/usr/bin/env python3
"""Smoke: copy_enabled gates RichDocument.selected_text for clipboard export."""
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
    doc.append_span(p0, widgets.text_span("Hello World", widgets.SPAN_NORMAL)) >>> (err) {
        println("FAIL: append")
        << 1
    }
    if !doc.is_copy_enabled() {
        println("FAIL: copy_enabled should default true")
        << 1
    }
    doc.set_selection(0, 5)
    selected := doc.selected_text()
    if selected != "Hello" {
        println("FAIL: selected_text got '" + selected + "'")
        << 1
    }
    doc.set_copy_enabled(false)
    if doc.is_copy_enabled() {
        println("FAIL: copy_enabled should be false")
        << 1
    }
    blocked := doc.selected_text()
    if blocked != "" {
        println("FAIL: selected_text must be empty when copy disabled, got '" + blocked + "'")
        << 1
    }
    if !doc.has_selection() {
        println("FAIL: selection should remain with copy disabled")
        << 1
    }
    doc.set_copy_enabled(true)
    restored := doc.selected_text()
    if restored != "Hello" {
        println("FAIL: selected_text after re-enable got '" + restored + "'")
        << 1
    }
    println("copy-enabled-apis: PASS")
    << 0
}
'''


def main() -> None:
    compiler = Path(os.environ.get("XU", str(ROOT / "bin" / "xu")))
    env = os.environ.copy()
    env.setdefault("XU_ROOT", str(ROOT))
    env.setdefault("XU_STDLIB_ROOT", str(ROOT / "src"))
    env["XUPATH"] = str(ROOT / "src") + ((":" + env["XUPATH"]) if env.get("XUPATH") else "")
    with tempfile.TemporaryDirectory(prefix="xu-copy-enabled-") as tmp:
        source = Path(tmp) / "main.xu"
        binary = Path(tmp) / "smoke"
        source.write_text(SOURCE)
        subprocess.run([str(compiler), "build", str(source), "-o", str(binary)], check=True, env=env)
        subprocess.run([str(binary)], check=True, env=env)


if __name__ == "__main__":
    main()
