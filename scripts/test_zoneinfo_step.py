#!/usr/bin/env python3
"""Verification for time.load_location and zoneinfo loading on Windows."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
COMPILER = ROOT / "bin" / "xu.exe"

TEST_CODE = r'''@main

#time

fn test_builtin_zones() {
    // 1. Asia/Shanghai (+8h, 28800s, no DST)
    sh := time.load_location("Asia/Shanghai") >>> (err) {
        eprintln("load Asia/Shanghai failed: " + err.msg())
        <<< 1
    }
    if sh.name != "Asia/Shanghai" || sh.offset_sec != 28800 || sh.has_dst != 0 {
        eprintln("Asia/Shanghai properties mismatch")
        <<< 2
    }
    println("OK: builtin Asia/Shanghai verified")

    // 2. America/New_York (-5h, -18000s, has DST)
    ny := time.load_location("America/New_York") >>> (err) {
        eprintln("load America/New_York failed: " + err.msg())
        <<< 3
    }
    if ny.name != "America/New_York" || ny.offset_sec != -18000 || ny.has_dst != 1 {
        eprintln("America/New_York properties mismatch")
        <<< 4
    }
    println("OK: builtin America/New_York verified")

    // 3. Unknown location rejected
    time.load_location("Unknown/Not_Exists") >>> (err) {
        println("OK: unknown location rejected")
        <<
    }
    eprintln("expected error for unknown location")
    <<< 5
}

fn test_custom_tzif() {
    // 4. Custom/Auckland loaded via ZONEINFO
    ak := time.load_location("Custom/Auckland") >>> (err) {
        eprintln("load Custom/Auckland via ZONEINFO failed: " + err.msg())
        <<< 6
    }
    if ak.name != "Custom/Auckland" || ak.offset_sec != 43200 || ak.has_dst != 1 {
        eprintln("Custom/Auckland properties mismatch: offset=" + str(ak.offset_sec) + " has_dst=" + str(ak.has_dst))
        <<< 7
    }
    println("OK: external IANA TZif via ZONEINFO verified")
}

fn main() {
    test_builtin_zones()
    test_custom_tzif()
    println("ALL_ZONEINFO_TESTS_PASSED")
}
'''

def main() -> int:
    env = os.environ.copy()
    env["XU_STDLIB_ROOT"] = str(ROOT / "src")
    env["XU_ROOT"] = str(ROOT)

    with tempfile.TemporaryDirectory() as td:
        tz_dir = Path(td) / "tzdata"
        custom_dir = tz_dir / "Custom"
        custom_dir.mkdir(parents=True)
        auckland_file = custom_dir / "Auckland"

        # Standard TZif file header and POSIX TZ string footer for NZST-12NZDT
        tzif_content = b"TZif2" + (b"\x00" * 40) + b"\nNZST-12NZDT,M9.5.0,M4.1.0/3\n"
        auckland_file.write_bytes(tzif_content)

        env["ZONEINFO"] = str(tz_dir)

        src = Path(td) / "test_zone.xu"
        exe = Path(td) / "test_zone.exe"
        src.write_text(TEST_CODE, encoding="utf-8")

        build_cmd = [str(COMPILER), "build", str(src), "-o", str(exe)]
        r = subprocess.run(build_cmd, env=env, capture_output=True, text=True)
        if r.returncode != 0:
            print("COMPILE FAILED:\n" + r.stderr + "\n" + r.stdout)
            return 1

        r2 = subprocess.run([str(exe)], env=env, capture_output=True, text=True, timeout=10)
        print(r2.stdout)
        if r2.stderr:
            print(r2.stderr, file=sys.stderr)

        if r2.returncode != 0:
            print(f"FAILED with exit code {r2.returncode}")
            return 1

        if "ALL_ZONEINFO_TESTS_PASSED" not in r2.stdout:
            print("FAILED: missing completion banner")
            return 1

    print("SUCCESS: Windows zoneinfo and ZONEINFO external loading passed!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
