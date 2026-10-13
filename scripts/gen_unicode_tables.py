#!/usr/bin/env python3
"""Compatibility entry point for the pinned Unicode 15.0.0 Go generator."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
raise SystemExit(subprocess.call(['go', 'run', 'scripts/gen_unicode_tables.go', *sys.argv[1:]], cwd=ROOT))
