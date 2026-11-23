import unittest
from policy import verify_split_records, assert_fit_partition

def row(trial,year,split,**extra):
    return dict(nct_id=trial,start_year=year,split=split,**extra)

class SplitIntegrityTests(unittest.TestCase):
    def test_distinct_trials_pass(self):
        report=verify_split_records([row("A",2012,"train"),row("B",2013,"validation"),row("C",2015,"calibration"),row("D",2016,"test")])
        self.assertEqual(report["trial_id_overlap"],0)
        self.assertEqual(report["unique_trials"],4)
    def test_same_trial_in_train_and_test_fails(self):
        with self.assertRaises(ValueError):
            verify_split_records([row("A",2012,"train"),row("A",2016,"test")])
    def test_test_year_cannot_be_reassigned_to_train(self):
        with self.assertRaises(ValueError): verify_split_records([row("A",2016,"train")])
    def test_related_group_crossing_partitions_fails(self):
        with self.assertRaises(ValueError):
            verify_split_records([row("A",2012,"train",group="G"),row("B",2016,"test",group="G")],group_key="group")
    def test_related_group_within_partition_passes(self):
        verify_split_records([row("A",2011,"train",group="G"),row("B",2012,"train",group="G")],group_key="group")
    def test_missing_group_fails_when_grouping_requested(self):
        with self.assertRaises(ValueError): verify_split_records([row("A",2012,"train")],group_key="group")
    def test_test_and_validation_cannot_fit(self):
        for split in ["test","validation"]:
            with self.assertRaises(ValueError): assert_fit_partition([{"split":split}],{"train"})
    def test_calibrator_cannot_fit_test_or_train(self):
        for split in ["test","train"]:
            with self.assertRaises(ValueError): assert_fit_partition([{"split":split}],{"calibration"})
    def test_assigned_fitting_partitions_pass(self):
        assert_fit_partition([{"split":"train"}],{"train"})
        assert_fit_partition([{"split":"calibration"}],{"calibration"})
    def test_invalid_fitting_policy_fails(self):
        with self.assertRaises(ValueError): assert_fit_partition([],{"test"})
    def test_invalid_manifest_identity_fails(self):
        with self.assertRaises(ValueError): verify_split_records([row("",2012,"train")])
    def test_fractional_year_fails(self):
        with self.assertRaises(ValueError): verify_split_records([row("A",2012.5,"train")])

if __name__=="__main__": unittest.main()
