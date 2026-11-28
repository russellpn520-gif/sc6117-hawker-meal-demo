import tempfile
import unittest
from datetime import date, timedelta
from itertools import combinations, product
from pathlib import Path

from streamlit.testing.v1 import AppTest

from meals import get_profile, move_workout, save_profile
from planning import ACTIVITIES, Profile, TrainingPreferences, valid_training_move
from training_coach import (_session, read_logs, save_training_log, save_training_preferences,
                            training_context, training_reply)


class StrengthCoachTests(unittest.TestCase):
    start = date(2026, 11, 23)  # Monday

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "training.db"
        self.profile = Profile(start=self.start, activity="regular", age=30, weight_kg=70, height_cm=175)
        save_profile(self.profile, db_path=self.db)

    def preferences(self, weekdays=(0, 2, 4), equipment="dumbbells", minutes=20, since=None):
        return TrainingPreferences(weekdays=weekdays, equipment=equipment, minutes=minutes, since=since or self.start)

    def test_general_advice_tracks_the_actual_calendar_before_optional_setup(self):
        tomorrow = self.start + timedelta(days=1)
        p = self.profile.model_copy(update={"activity": "occasional"})
        save_profile(p, db_path=self.db)
        self.assertTrue(move_workout(p, self.start, tomorrow, db_path=self.db))
        rest = training_reply(p, self.start, db_path=self.db, lang="en")
        self.assertIn("Rest day", rest)
        self.assertIn("easy walk", rest)
        active = training_reply(p, tomorrow, db_path=self.db, lang="zh")
        self.assertIn(f"{tomorrow.isoformat()} · 训练日", active)
        self.assertIn("快走 20 分钟", active)
        self.assertIn("器械", active)
        self.assertNotIn("训练日", training_reply(p, self.start - timedelta(days=1), db_path=self.db))

    def test_constraints_across_every_availability_pattern(self):
        for n in range(1, 8):
            for days in combinations(range(7), n):
                for tier, gear, minutes in product(ACTIVITIES, ["bodyweight", "dumbbells"], [10, 20, 30]):
                    prefs = self.preferences(days, gear, minutes)
                    chosen = prefs.strength_days(tier)
                    self.assertTrue(set(chosen) <= set(days))
                    self.assertLessEqual(len(chosen), min(3, len(ACTIVITIES[tier].training_offsets)))
                    self.assertFalse(any((d+1) % 7 in chosen for d in chosen))
                    day = self.start + timedelta(days=chosen[0])
                    profile = self.profile.model_copy(update={"training": prefs, "activity": tier, "goal": "lose"})
                    session = _session(profile, day, {day}, [], "en")
                    self.assertTrue(0 < session["planned_minutes"] <= minutes)
                    self.assertTrue(gear == "dumbbells" or all(e["id"] != "curl" for e in session["exercises"]))

    def test_progress_requires_actual_sets_and_recovery_limits_work(self):
        p = save_training_preferences(self.profile, self.preferences(), db_path=self.db)
        def session(d):
            return training_context(p, d, db_path=self.db, lang="en")["sessions"][0]
        days = [self.start + timedelta(days=i) for i in (0, 2, 4, 7, 9, 11, 14, 21)]
        for day in days[:2]:
            items = session(day)["exercises"]
            reps = {e["id"]: [{"reps": 8, "kg": 2 if e["id"] == "curl" else 0}] * 2 for e in items}
            save_training_log(p, day, day, "comfortable", reps, db_path=self.db)
            save_training_log(p, day, day, "comfortable", reps, db_path=self.db)
        self.assertEqual(len(read_logs(self.start, days[2], db_path=self.db)), 2)
        progressed = session(days[2])
        self.assertTrue(all(e["reps"] == 9 and e["sets"] == 2 for e in progressed["exercises"]))
        self.assertEqual(progressed["exercises"][-1]["kg"], 2)
        for day in days[2:4]:
            save_training_log(p, day, day, "challenging", {"squat": [{"reps": 7, "kg": 0}]}, db_path=self.db)
        self.assertEqual(session(days[4])["mode"], "deload")
        save_training_log(p, days[4], days[4], "missed", {}, db_path=self.db)
        self.assertEqual(session(days[5])["mode"], "return")
        self.assertEqual(session(days[-1])["mode"], "deload")
        with self.assertRaises(ValueError):
            save_training_log(p, days[5], days[4], "missed", {}, db_path=self.db)
        self.assertFalse(valid_training_move(p, days[0], days[0]+timedelta(days=1), set()))
        self.assertFalse(valid_training_move(p, days[0], days[2], {days[2]-timedelta(days=1)}))
        self.assertIn("Recovery day", training_reply(p, days[0]+timedelta(days=1), db_path=self.db, lang="en"))
        next_p = save_training_preferences(p, self.preferences((1, 3), since=days[5]), db_path=self.db)
        self.assertEqual(next_p.training_for(days[0]), p.training)
        self.assertEqual(next_p.training_for(days[5]).weekdays, (1, 3))

    def test_real_english_screen_accepts_per_set_log(self):
        prefs = self.preferences()
        save_training_preferences(self.profile, prefs, db_path=self.db)
        src = f"""
import streamlit as st
from datetime import date
from meals import get_profile
from plan_ui import training_plan, calendar_for_view
st.session_state.ui_lang = 'en'
path={str(self.db)!r}
day=date.fromisoformat('{self.start}')
p=get_profile(db_path=path)
training_plan(p,day,calendar_for_view(p,day,path),path)
"""
        app = AppTest.from_string(src).run()
        self.assertFalse(app.exception)
        app.button(key="open_workout_log").click().run()
        next(w for w in app.text_input if "squat" in w.label).set_value("8, 7")
        next(w for w in app.text_input if "curl" in w.label).set_value("8, 6")
        next(w for w in app.text_input if "per dumbbell" in w.label).set_value("2, 1.5")
        next(w for w in app.button if w.label == "Save workout log").click().run()
        self.assertFalse(app.exception)
        row, = read_logs(self.start, self.start, db_path=self.db)
        self.assertEqual(row["actuals"]["curl"], [{"reps": 8, "kg": 2}, {"reps": 6, "kg": 1.5}])
        self.assertEqual(get_profile(db_path=self.db).training, prefs)
        new_p = save_training_preferences(get_profile(db_path=self.db), self.preferences((3,), "bodyweight", 10),
                                          db_path=self.db)
        self.assertEqual(new_p.training.since, self.start + timedelta(days=1))
        self.assertEqual(new_p.training_for(self.start).equipment, "dumbbells")

    def test_first_setup_from_normal_training_screen(self):
        src = f"""
import streamlit as st
from datetime import date
from meals import get_profile
from plan_ui import training_plan, calendar_for_view
st.session_state.ui_lang = 'en'
path={str(self.db)!r}
day=date.fromisoformat('{self.start}')
p=get_profile(db_path=path)
training_plan(p,day,calendar_for_view(p,day,path),path)
"""
        app = AppTest.from_string(src).run()
        app.multiselect[0].set_value([0, 2, 6])
        next(b for b in app.button if b.label == "Apply training schedule").click().run()
        self.assertFalse(app.exception)
        profile = get_profile(db_path=self.db)
        self.assertEqual(profile.training.weekdays, (0, 2, 6))
        self.assertIn("Bodyweight mini squat", training_reply(profile, self.start, db_path=self.db, lang="en"))
