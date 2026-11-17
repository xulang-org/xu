#!/usr/bin/env python3
"""Compile and run text-selection helper smoke checks against the local stdlib."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''@main

#ui/widgets

fn main() int {
    $range := widgets.word_range_at(&"hello world", 1)
    if range.start != 0 || range.end != 5 {
        println("FAIL word hello")
        <<< 1
    }
    range = widgets.word_range_at(&"hello world", 7)
    if range.start != 6 || range.end != 11 {
        println("FAIL word world")
        <<< 1
    }
    range = widgets.line_range_at(&"ab\ncd", 1)
    if range.start != 0 || range.end != 3 {
        println("FAIL line 0")
        <<< 1
    }
    range = widgets.text_range(8, 3)
    if range.start != 3 || range.end != 8 || range.length() != 5 {
        println("FAIL normalize")
        <<< 1
    }
    println("ui-text-selection: PASS")
    << 0
}
'''


def main() -> None:
    compiler = Path(os.environ.get("XU", str(ROOT / "bin" / "xu")))
    env = os.environ.copy()
    env.setdefault("XU_ROOT", str(ROOT))
    env.setdefault("XU_STDLIB_ROOT", str(ROOT / "src"))
    env["XUPATH"] = str(ROOT / "src") + ((":" + env["XUPATH"]) if env.get("XUPATH") else "")
    with tempfile.TemporaryDirectory(prefix="xu-ui-text-sel-") as tmp:
        source = Path(tmp) / "main.xu"
        binary = Path(tmp) / "smoke"
        source.write_text(SOURCE)
        subprocess.run([str(compiler), "build", str(source), "-o", str(binary)], check=True, env=env)
        subprocess.run([str(binary)], check=True, env=env)


if __name__ == "__main__":
    main()
