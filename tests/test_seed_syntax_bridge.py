import importlib.util
from pathlib import Path
import os
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("seed_bridge", ROOT / "scripts/stage_seed_syntax.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def test_bridge_only_changes_module_declarations(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    original = b'@os/exec\n#path/filepath\nfn run() { println("example.com/a")\n obj.value() }\n'
    (source / "mod.xu").write_bytes(original)
    manifest = b"module: cmd/compile\nversion: !ver 2.0.0\nxu: !ver 0.8.1\n"
    (source / "xu.xun").write_bytes(manifest)
    dest = tmp_path / "staged"
    assert bridge.stage(source, dest) == 2
    assert (dest / "mod.xu").read_bytes() == original.replace(b"@os/exec", b"@os.exec", 1)
    assert (dest / "xu.xun").read_bytes() == manifest.replace(b"module: cmd/compile", b"module: cmd.compile", 1)
    assert (source / "mod.xu").read_bytes() == original
    assert (source / "xu.xun").read_bytes() == manifest
    with pytest.raises(ValueError, match="already exists"):
        bridge.stage(source, dest)


def test_current_product_accepts_complete_slash_probe(tmp_path):
    package = tmp_path / "seed_probe/slash"
    package.mkdir(parents=True)
    (package / "mod.xu").write_text('@seed_probe/slash\npub fn value() int { << 0 }\n')
    main = tmp_path / "main.xu"
    main.write_text('@main\n#seed_probe/slash\nfn main() int { << slash.value() }\n')
    result = subprocess.run([os.environ.get("XU", str(ROOT / "bin/xu")), "check", str(main)],
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
