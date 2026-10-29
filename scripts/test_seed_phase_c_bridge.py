"""Layout and propagation checks for the disposable hosted seed adapter."""

import unittest

from seed_phase_c_bridge import CORE_END, CORE_START, CURRENT, LEGACY, retarget


class SeedPhaseCBridgeTests(unittest.TestCase):
    def setUp(self):
        self.prefix = b"\x7fELF\x02\x01" + bytes(range(256))
        self.core = (CORE_START + b'\nfn patch() string { << "' + LEGACY
                     + b'" + "' + LEGACY + b'" }\n//' + b" " * 400 + CORE_END)
        self.data = self.prefix + LEGACY + b"separator" + LEGACY + self.core + b"suffix"

    def test_layout_and_self_replication(self):
        result = retarget(self.data)
        self.assertEqual(len(result), len(self.data))
        self.assertTrue(result.startswith(self.prefix))
        self.assertTrue(result.endswith(b"suffix"))
        self.assertNotIn(LEGACY, result)
        self.assertEqual(result.count(CURRENT), 2)
        start = result.index(CORE_START)
        end = result.index(CORE_END, start) + len(CORE_END)
        core = result[start:end]
        self.assertNotIn(b"$", core)  # The seed's old quoting routine remains valid.
        self.assertEqual(core.count(b'string_from_byte(36)'), 2)
        self.assertEqual(retarget(result), result)

    def test_unaffected_seed(self):
        self.assertEqual(retarget(b"modern hosted seed"), b"modern hosted seed")

    def test_unknown_layouts_are_rejected(self):
        for data in (LEGACY, self.data.replace(LEGACY, b"", 1),
                     self.data.replace(b" " * 400, b" "),
                     self.data.replace(CORE_START, b"unknown payload")):
            with self.subTest(data=data[:30]), self.assertRaises(ValueError):
                retarget(data)


if __name__ == "__main__":
    unittest.main()
