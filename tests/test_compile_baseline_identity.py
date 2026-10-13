"""A changed compiler workload must not masquerade as a timing regression."""
import unittest
from scripts.compile_baseline_identity import validate


class CompileBaselineIdentityTests(unittest.TestCase):
    def setUp(self):
        self.current = dict(host="Darwin-arm64", source_seed_files="172",
                            source_closure_files="191", source_seed_bytes="4000000",
                            reference_primer_sha256="primer", primer_opt="O0",
                            source_seed_sha256="seed", source_closure_sha256="closure",
                            gen1_wall="33.64", gen1_timings="timings: total=33494ms")

    def test_same_scale_source_edits_keep_timing_gate(self):
        old = dict(self.current, source_seed_bytes="3900000", source_seed_sha256="old")
        self.assertEqual(validate(old, self.current), [])

    def test_historical_metadata_free_baseline_is_rejected(self):
        self.assertTrue(validate(dict(gen1_wall="9.24"), self.current))

    def test_different_host_profile_or_file_count_is_rejected(self):
        for field in ("host", "source_seed_files", "source_closure_files", "primer_opt"):
            with self.subTest(field=field):
                self.assertTrue(validate(dict(self.current, **{field: "different"}), self.current))

    def test_primer_rebuild_keeps_the_original_timing_budget(self):
        self.assertEqual(validate(dict(self.current, reference_primer_sha256="rebuilt"), self.current), [])

    def test_large_workload_change_is_rejected_in_either_direction(self):
        for size in ("1500000", "8000000", "0", "invalid"):
            self.assertTrue(validate(dict(self.current, source_seed_bytes=size), self.current))

    def test_missing_or_zero_timings_cannot_disable_the_gate(self):
        for value in ("0", "invalid", "nan"):
            self.assertTrue(validate(dict(self.current, gen1_wall=value), self.current))
        self.assertTrue(validate(dict(self.current, gen1_timings="n/a"), self.current))


if __name__ == "__main__":
    unittest.main()
