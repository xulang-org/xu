import io
import struct
import unittest

from import_perf_pgo import import_stacks


class PerfImportTest(unittest.TestCase):
    def setUp(self):
        self.image = bytearray(256)
        self.image[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<HH", self.image, 16, 2, 62)
        struct.pack_into("<Q", self.image, 32, 64)
        struct.pack_into("<HH", self.image, 54, 56, 1)
        struct.pack_into("<IIQQQQ", self.image, 64, 1, 5, 0, 0x4000, 0, 256)
        self.layout = ({(0x4020, 0x4080): ("f", 0, "false")},
                       {0x4020: ("f", 0, "true")}, {"f": "b1.2-r-r"})

    def read(self, lines):
        return import_stacks(io.StringIO("\n".join(lines)), "/bin/xu",
                             self.image, self.layout)[0]

    def test_interval_boundaries(self):
        entry = "0x4090 (/bin/xu)/0x4010 (/bin/xu)/P/-/-/0"
        taken = "0x4020 (/bin/xu)/0x4080 (/bin/xu)/P/-/-/0"
        after = "0x4030 (/bin/xu)/0x5000 (/lib/other)/P/-/-/0"
        profiles = self.read([after + " " + entry, taken + " " + entry])
        self.assertEqual(profiles["f"].counts, [1, 1])
        self.assertFalse(self.read([after, entry]))
        self.assertFalse(self.read([after + " " + entry.replace("/bin/xu", "/other/xu")]))
        self.assertFalse(self.read([after + " " + entry + "/COND/SPEC_WRONG_PATH"]))

    def test_malformed_middle_entry(self):
        with self.assertRaisesRegex(ValueError, "sample line 1"):
            self.read(["0x4030 (/bin/xu)/0x5000 (/lib/other)/P/-/-/0 ???"])


if __name__ == "__main__":
    unittest.main()
