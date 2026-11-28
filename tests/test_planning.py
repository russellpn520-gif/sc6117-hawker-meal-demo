import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from meals import get_profile, move_workout, planned_days, save_profile, schedule_workout
from planning import ACTIVITIES, Profile, calorie_balance, day_plan, energy_factor


class PersonalPlanTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Path(self.directory.name) / "diary.sqlite3"
        self.start = date(2026, 1, 1)
        self.profile = Profile(age=25, height_cm=168, weight_kg=65, activity="regular", start=self.start)
        self.days = [self.start + timedelta(days=i) for i in range(14)]

    def targets(self, profile):
        active = planned_days(profile, self.days[0], self.days[-1], db_path=self.db)
        return [day_plan(profile, day, active) for day in self.days]

    def test_reference_and_optional_coefficient(self):
        self.assertEqual(self.profile.resting_kcal, (1414, 1580))
        male = self.profile.model_copy(update={"sex": "male"})
        self.assertEqual(male.resting_kcal, (1580, 1580))
        save_profile(male, db_path=self.db)
        self.assertEqual(get_profile(db_path=self.db), male)
        self.assertEqual(self.targets(male)[0].kcal, (2441, 2441))
        self.assertEqual(self.targets(male)[1].kcal, (2086, 2086))
        self.assertEqual(calorie_balance((2289, 2289), 248), ("今天还差", "2041 kcal"))
        for consumed, label in [(1500, "距今日目标下限"), (2100, "今日热量"), (2600, "已超出今日目标")]:
            self.assertEqual(calorie_balance((2000, 2400), consumed)[0], label)

    def test_activity_tiers_and_moves_only_affect_changed_dates(self):
        for key, tier in ACTIVITIES.items():
            with self.subTest(activity=key):
                profile = self.profile.model_copy(update={"activity": key})
                before = self.targets(profile)
                self.assertEqual(sum(d.training for d in before[:7]), len(tier.training_offsets))
                for i, resting in enumerate(profile.resting_kcal):
                    self.assertEqual(sum(d.kcal[i] for d in before[:7]), sum(round(resting * tier.pal * energy_factor(profile, d.theme)) for d in before[:7]))
        before = self.targets(self.profile)
        self.assertTrue(move_workout(self.profile, self.days[0], self.days[1], db_path=self.db))
        after = self.targets(self.profile)
        self.assertEqual((after[0], after[1]), (before[1], before[0]))
        self.assertEqual(after[2:], before[2:])
        self.assertFalse(move_workout(self.profile, self.days[0], self.days[1], db_path=self.db))
        self.assertFalse(move_workout(self.profile, self.days[1], self.days[2], db_path=self.db))
        self.assertTrue(move_workout(self.profile, self.days[1], self.days[8], db_path=self.db))
        crossing = self.targets(self.profile)
        self.assertEqual(crossing[1], before[1])
        self.assertEqual(crossing[8], before[0])
        self.assertEqual([d for i,d in enumerate(crossing) if i not in (1,8)],
                         [d for i,d in enumerate(after) if i not in (1,8)])

    def test_existing_explicit_training_and_goal_limits(self):
        schedule_workout(self.days[1], db_path=self.db)
        self.assertTrue(self.targets(self.profile)[1].training)
        for changes in ({"activity": "athlete", "goal": "lose"}, {"weight_kg": 48, "goal": "lose"}):
            self.assertEqual(energy_factor(self.profile.model_copy(update=changes), "rest"), 1.0)
        self.assertEqual(energy_factor(self.profile.model_copy(update={"goal": "gain"}), "rest"), 1.05)


if __name__ == "__main__":
    unittest.main()
