import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("module_path_contract", ROOT / "scripts/check_module_paths.py")
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)


def test_contract_separates_module_paths_from_property_access():
    assert contract.errors(Path("mod.xu"), "@os/exec\n#path/filepath\nfn run() { cmd.run() }\n") == []
    assert contract.errors(Path("mod.xu"), '@"example.com/a"\na #example.com/a\n') == []
    assert contract.errors(Path("mod.xu"), '@os.exec\n#path.filepath\n')
    assert contract.errors(Path("xu.xun"), "module: cmd/doc\nversion: !ver 1.0.0\n") == []
    assert contract.errors(Path("xu.xun"), "module: cmd.doc\n")
