#!/usr/bin/env python3
"""Execute the production DirectWrite dispatcher with concurrent native callers."""
from __future__ import annotations
import argparse
from pathlib import Path
import subprocess
from test_windows_workers import WindowsTemporaryDirectory

PREFIX = r'''#define _WIN32_WINNT 0x0602
#include <windows.h>
#include <atomic>
#include <mutex>
#include <thread>
#include <vector>
#include <cstdio>
'''
SUFFIX = r'''
int main() {
  TextNativeWorker worker;
  std::atomic<unsigned> failures{0}, active{0}, completed{0};
  std::atomic<DWORD> identity{0};
  std::vector<std::thread> callers;
  for (unsigned caller = 0; caller < 8; ++caller) callers.emplace_back([&] {
    for (unsigned i = 0; i < 128; ++i) {
      struct Call { DWORD caller; unsigned input, output; std::atomic<unsigned> *failures, *active, *completed; std::atomic<DWORD> *identity; };
      Call call{GetCurrentThreadId(), i, 0, &failures, &active, &completed, &identity};
      bool ok = worker.run([](void *opaque) {
        auto *c = static_cast<Call *>(opaque);
        DWORD id = GetCurrentThreadId(), expected = 0;
        c->identity->compare_exchange_strong(expected, id);
        ULONG_PTR low = 0, high = 0;
        GetCurrentThreadStackLimits(&low, &high);
        ULONG_PTR address = reinterpret_cast<ULONG_PTR>(&id);
        if (id == c->caller || c->identity->load() != id || address < low || address >= high) ++*c->failures;
        if (c->active->fetch_add(1) != 0) ++*c->failures;
        c->output = c->input * 3 + 7;
        --*c->active;
        ++*c->completed;
      }, &call);
      if (!ok || call.output != i * 3 + 7) ++failures;
    }
  });
  for (auto &caller : callers) caller.join();
  if (failures || completed != 1024) return 1;
  puts("Windows text worker: 1024 concurrent requests, OS stack bounds, identity and completion passed");
  return 0;
}
'''

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    text = (root / "src/ui/host/windows_text.inc").read_text(encoding="utf-8")
    start = text.index("struct TextNativeWork {")
    end = text.index("static TextNativeWorker &text_worker()", start)
    with WindowsTemporaryDirectory(prefix="xu-windows-text-worker-") as folder:
        work = Path(folder)
        source = work / "worker.cc"
        source.write_text(PREFIX + text[start:end] + SUFFIX, encoding="utf-8")
        executable = work / "worker.exe"
        subprocess.run([str(args.cxx.resolve()), "-std=c++17", "-O2", "-static", str(source), "-o", str(executable)], check=True, timeout=90)
        subprocess.run([str(executable)], check=True, timeout=30)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
