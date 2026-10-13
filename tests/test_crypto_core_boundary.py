"""Hardware references must not grant permission for crypto code in core."""
import importlib.util
import contextlib
import io
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('crypto_boundary', ROOT / 'scripts/check_crypto_constant_time.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class CryptoCoreBoundaryTests(unittest.TestCase):
    def check(self, relative, source, allowed):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'src/xu').mkdir(parents=True)
            (root / 'src/cmd/compile').mkdir(parents=True)
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
            with patch.object(checker, 'ROOT', root):
                if allowed:
                    checker.check_core_boundary()
                else:
                    with self.assertRaises(SystemExit):
                        checker.check_core_boundary()

    def test_registered_references_only_in_designated_files(self):
        for relative, labels in checker.HW_REFERENCE_FILES.items():
            for label in labels:
                with self.subTest(relative=relative, label=label):
                    self.check(relative, f'fn guard() {{ target := "{label}" }}', True)
                    self.check('src/cmd/compile/other.xu', f'target := "{label}"', False)

    def test_hardware_literal_does_not_mask_algorithm_or_import(self):
        relative = 'src/xu/types/mir_10_opt_cfg.xu'
        prefix = 'target := "_xu_crypto_aes_aes_hw_"\n'
        for forbidden in ('#crypto/aes', '@crypto/aes', 'fn aes() {}',
                          'target := "_xu_crypto_aes_encrypt"',
                          'target := "_xu_crypto_aes_aes_hw_unregistered"',
                          'target := _xu_crypto_aes_aes_hw_'):
            # A prefix literal alone is allowed, but cannot be used to hide
            # another marker, including an unquoted crypto identifier.
            with self.subTest(forbidden=forbidden):
                self.check(relative, prefix + forbidden, False)


    def test_independent_bootstrap_keeps_crypto_boundary_and_logical_diagnostics(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder)
            root = parent / 'xu'
            (root / 'src/xu').mkdir(parents=True)
            (root / 'src/cmd/compile').mkdir(parents=True)
            primer = parent / 'bootstrap'
            source = primer / 'crates/fake/src/lib.rs'
            source.parent.mkdir(parents=True)
            source.write_text('pub fn ordinary() {}')
            with patch.object(checker, 'ROOT', root), patch.dict(os.environ, {'XU_BOOTSTRAP_ROOT': str(primer)}):
                checker.check_core_boundary()
                source.write_text('#crypto/aes')
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
                    checker.check_core_boundary()
                self.assertIn('bootstrap/crates/fake/src/lib.rs', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
