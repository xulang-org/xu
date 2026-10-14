#!/usr/bin/env python3
"""Rebase official external package fixtures into a disposable source copy."""
from pathlib import Path
import re
import shutil
import sys

from companion_repos import project_root


def prepare(source: Path, destination: Path) -> None:
    packages = project_root('packages').resolve()
    if not (packages / 'xu.xun').is_file():
        raise ValueError('Official packages root module missing: ' + str(packages))
    manifest = (source / 'xu.xun').read_text()
    pattern = r'(?m)^(\s*"?github\.com/xulang-org/packages"?\s*:\s*)file:[^\r\n]+'
    updated, count = re.subn(pattern, lambda match: match[1] + 'file:' + packages.as_posix(), manifest)
    if count != 1:
        raise ValueError('Fixture must declare exactly one local official packages dependency')
    shutil.copytree(source, destination)
    (destination / 'xu.xun').write_text(updated)


if __name__ == '__main__':
    try:
        prepare(Path(sys.argv[1]), Path(sys.argv[2]))
    except (OSError, ValueError) as error:
        raise SystemExit(str(error))
