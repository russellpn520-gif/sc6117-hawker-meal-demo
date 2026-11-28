import unittest
from copy import deepcopy

from mobile_ui import coverage_status


class LegacyCoverageTests(unittest.TestCase):
    def setUp(self):
        self.record = {
            "input": {
                "method": "photo",
                "suggested_grams": {"garnish": 6},
                "unmatched_foods": ["蒸米饭", "白切鸡肉片"],
            },
            "items": [{"food_id": "garnish", "confirmed_g": 6}],
        }

    def test_old_garnish_only_record_is_marked_without_mutating_it(self):
        before = deepcopy(self.record)
        self.assertEqual(coverage_status(self.record), "legacy_review")
        self.assertEqual(before, self.record)

    def test_explicit_new_decision_takes_precedence(self):
        for partial, status in ((False, "complete"), (True, "partial")):
            self.record["input"]["partial_record"] = partial
            self.assertEqual(coverage_status(self.record), status)

    def test_old_manual_additions_are_not_reclassified(self):
        self.record["items"].append({"food_id": "rice", "confirmed_g": 200})
        self.assertEqual(coverage_status(self.record), "complete")

    def test_older_photo_with_only_size_notes_is_not_reclassified(self):
        del self.record["input"]["unmatched_foods"]
        self.record["input"]["unmatched"] = ["没有参照物，份量不确定"]
        self.assertEqual(coverage_status(self.record), "complete")
