import unittest
from policy import completion_label, significance_label, phase_name, validate_features, split_year, supported

class ContractTests(unittest.TestCase):
    def test_ongoing_is_unknown(self):
        self.assertIsNone(completion_label("RECRUITING"))
    def test_completion(self):
        self.assertEqual([completion_label(x) for x in ["COMPLETED", "TERMINATED", "WITHDRAWN"]], [1,0,0])
    def test_missing_p_unknown(self):
        self.assertIsNone(significance_label("COMPLETED", None))
    def test_nan_unknown(self):
        self.assertIsNone(significance_label("COMPLETED", float("nan")))
    def test_noncompleted_p_unknown(self):
        self.assertIsNone(significance_label("TERMINATED", .01))
    def test_p_boundary(self):
        self.assertEqual(significance_label("COMPLETED", .05), 0)
        self.assertEqual(significance_label("COMPLETED", .049), 1)
    def test_invalid_p_unknown(self):
        self.assertIsNone(significance_label("COMPLETED", -1))
    def test_combined_not_duplicated(self):
        self.assertEqual(phase_name("Phase 1/Phase 2"), "PHASE1/PHASE2")
    def test_early_phase_retained(self):
        self.assertEqual(phase_name("EARLY_PHASE1"), "EARLY_PHASE1")
    def test_leaky_and_text_columns_rejected(self):
        for c in ["post_enrollment_final", "overall_status", "met_primary", "label_min_primary_p", "n_sites", "emb_pc1", "elig_biomarker", "sponsor_prior_stop_rate"]:
            with self.assertRaises(ValueError): validate_features([c])
    def test_disjoint_years(self):
        self.assertEqual([split_year(y) for y in [2012,2013,2015,2016]], ["train","validation","calibration","test"])
    def test_small_stratum_unsupported(self):
        self.assertFalse(supported([0]*40+[1]*2))
        self.assertFalse(supported([1]*100))
    def test_duplicate_features_rejected(self):
        with self.assertRaises(ValueError): validate_features(["start_year", "start_year"])

if __name__ == "__main__": unittest.main()
