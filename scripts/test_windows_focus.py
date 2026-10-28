#!/usr/bin/env python3
"""Test the production focus classifier against a mocked native window tree.

No windows are created or controlled; the host's IsChild dependency is mocked.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess

from test_windows_workers import WindowsTemporaryDirectory


PREFIX = r'''
#include <stdint.h>
#include <stdio.h>
using HWND = uintptr_t;
struct XuContentPlugin { HWND hwnd; };
// Canvas 1 owns proxy 2 and its descendant 3; canvas 4 owns proxy 5.
static bool IsChild(HWND parent, HWND child) {
  const HWND parents[] = {0,0,1,2,0,4};
  while (child && child < 6) {
    child = parents[child];
    if (child == parent) return true;
  }
  return false;
}
'''

SUFFIX = r'''
int main() {
  XuContentPlugin canvas{1};
  struct Case { const char *name; HWND next; bool internal; };
  const Case cases[] = {
    {"canvas itself",1,true}, {"native editor proxy",2,true},
    {"nested canvas child",3,true}, {"another canvas",4,false},
    {"another canvas editor",5,false}, {"focus left the app",0,false},
    {"unrelated window",99,false},
  };
  for (const auto &test : cases) {
    if (draw_focus_within_canvas(&canvas,test.next) != test.internal) {
      fprintf(stderr,"focus classification failed: %s\n",test.name);
      return 1;
    }
  }
  if (draw_focus_within_canvas(nullptr,2)) return 2;
  canvas.hwnd = 0;
  if (draw_focus_within_canvas(&canvas,2)) return 3;
  puts("Windows canvas focus regression passed");
  return 0;
}
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = (root / "src/ui/host/windows_draw.cc").read_text(encoding="utf-8")
    helper = re.search(r"static bool draw_focus_within_canvas\([^\n]*\) \{.*?\n\}", source, re.S)
    if helper is None:
        raise RuntimeError("production focus classifier not found")
    with WindowsTemporaryDirectory(prefix="xu-windows-focus-") as folder:
        workspace = Path(folder)
        fixture = workspace / "focus.cc"
        fixture.write_text(PREFIX + helper[0] + SUFFIX, encoding="utf-8")
        executable = workspace / "focus.exe"
        subprocess.run([str(args.cxx.resolve()), "-std=c++17", "-O2", "-static", str(fixture), "-o", str(executable)], check=True, timeout=60)
        subprocess.run([str(executable)], check=True, timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
