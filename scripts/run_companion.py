#!/usr/bin/env python3
"""Run an explicit entrypoint in an optional Xu companion checkout."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from companion_repos import PROJECTS, ROOT, project_root


def main() -> int:
    if len(sys.argv) < 3 or sys.argv[1] not in PROJECTS:
        raise SystemExit("usage: run_companion.py examples|bench|site|packages|bootstrap|vscode SCRIPT [ARGS...]")
    project = sys.argv[1]
    checkout = project_root(project)
    script = (checkout / sys.argv[2]).resolve()
    if not script.is_relative_to(checkout) or not script.is_file():
        raise SystemExit(f"missing {PROJECTS[project]} entrypoint: {script}; "
                         f"set XU_{project.upper()}_ROOT to its checkout")
    command = [sys.executable, str(script)] if script.suffix == ".py" else [str(script)]
    env = dict(os.environ, XU_ROOT=str(ROOT))
    os.chdir(checkout)
    os.execvpe(command[0], command + sys.argv[3:], env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
