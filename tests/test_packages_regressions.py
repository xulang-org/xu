"""Compatibility entrypoint for regressions owned by the packages repository."""
from pathlib import Path
import runpy
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from companion_repos import project_root

_suite = project_root("packages") / "tests/test_packages_regressions.py"
if not _suite.is_file():
    raise SystemExit(f"missing packages regressions: {_suite}; set XU_PACKAGES_ROOT")
globals().update({key: value for key, value in runpy.run_path(str(_suite)).items()
                  if not key.startswith("__")})
if __name__ == "__main__":
    import unittest
    unittest.main()
