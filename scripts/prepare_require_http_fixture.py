#!/usr/bin/env python3
"""Pin the product HTTP fixture to its independent source golden.

The frozen oracle keeps its historical FNV fixture. Call this only on the
disposable product copy, after choosing the local HTTP server port.
"""
import hashlib
from pathlib import Path
import sys


def prepare(directory):
    directory = Path(directory)
    manifest = (directory / "xu.xun").read_text()
    locator = next(line.split(":", 1)[1].strip() for line in manifest.splitlines()
                   if line.strip().startswith("rempkg:"))
    source = "xu-source-v2\n6:rempkg" + str(len(locator.encode())) + ":" + locator
    origin = hashlib.sha256(source.encode()).hexdigest()
    file_digest = hashlib.sha256((directory / "www/rempkg.xu").read_bytes()).hexdigest()
    # Derive the byte length of the relative path independently.
    tree = "xu-tree-v1\nD0:\nF" + str(len("rempkg.xu")) + ":rempkg.xu:" + file_digest + "\n"
    digest = hashlib.sha256(tree.encode()).hexdigest()
    (directory / "xu.lock").write_text("xu-lock-v2 sha256-tree-v1\nrempkg " + origin + " " + digest + " -\n")


if __name__ == "__main__":
    prepare(sys.argv[1])
