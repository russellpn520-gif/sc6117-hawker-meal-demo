import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from streamlit.testing.v1 import AppTest

from meals import get_profile, move_workout, planned_days, save_profile
from planning import Profile, TrainingPreferences, move_targets, span
from training_coach import save_training_log, save_training_preferences


class PlanLanguageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = Path(temp.name) / "diary.sqlite3"
        self.today = date(2026, 11, 28)
        self.app_source = f"""
from datetime import date
from pathlib import Path

import streamlit as st
from meals import get_profile
from plan_ui import calendar_for_view, profile_form, settings, training_plan

db = Path({str(self.db)!r})
today = date.fromisoformat({self.today.isoformat()!r})
profile = get_profile(db_path=db)
if st.session_state.get("view") == "calendar":
    days = calendar_for_view(profile, today, db)
    if notice := st.session_state.pop("notice", None):
        st.info(notice)
    training_plan(profile, today, days, db, eaten={{"kcal": 105, "protein_g": 0.2, "carb_g": 21, "fat_g": 1}})
    settings(profile, db, public_demo=True)
else:
    profile_form(profile, today, db, public_demo=False)
"""

    def test_create_in_english_then_read_stored_values_in_chinese(self):
        app = AppTest.from_string(self.app_source)
        app.session_state["ui_lang"] = "en"
        app.run()
        self.assertEqual(app.subheader[0].value, "Your personal plan")
        self.assertEqual(app.selectbox(key="plan_activity").options[2], "Regularly active · usually 3 or more days a week")
        app.text_input(key="plan_nickname").input("Sam")
        app.number_input(key="plan_age").set_value(25)
        app.number_input(key="plan_height").set_value(174.0)
        app.number_input(key="plan_weight").set_value(68.5)
        app.selectbox(key="plan_activity").select("regular")
        app.button[0].click().run()
        self.assertFalse(app.exception)
        profile = get_profile(db_path=self.db)
        self.assertEqual((profile.nickname, profile.activity, profile.weight_kg), ("Sam", "regular", 68.5))
        app.session_state["ui_lang"] = "zh"
        app.run()
        self.assertEqual(app.subheader[0].value, "调整个人计划")
        self.assertEqual(app.selectbox(key="plan_activity").value, "regular")
        self.assertEqual(app.number_input(key="plan_weight").value, 68.5)

    def test_en_training_move_and_dynamic_labels_on_existing_profile(self):
        save_profile(Profile(age=27, height_cm=170, weight_kg=64, activity="occasional", goal="gain",
                             start=self.today, sex="female"), db_path=self.db)
        app = AppTest.from_string(self.app_source)
        app.session_state["ui_lang"] = "en"
        app.session_state["view"] = "calendar"
        app.run()
        self.assertFalse(app.exception)
        app.button(key="open_move_days").click().run()
        app.button(key=f"move_option_{self.today + timedelta(days=1)}").click().run()
        profile = get_profile(db_path=self.db)
        tomorrow = self.today + timedelta(days=1)
        days = planned_days(profile, self.today, self.today + timedelta(days=13), db_path=self.db)
        self.assertIn(self.today, days)
        self.assertNotIn(tomorrow, days)
        comparison = next(m.value for m in app.markdown if "down " in m.value)
        for before, after in move_targets(profile, self.today, tomorrow, days):
            self.assertIn(f"{span(before.kcal)} → **{span(after.kcal)} kcal**", comparison)
        self.assertIn("up ", comparison)
        app.button(key="confirm_training_move").click().run()
        self.assertTrue(any("Workout moved from Nov 28 to Nov 29" in x.value for x in app.info))
        self.assertEqual(app.session_state.selected_day, tomorrow)
        profile = get_profile(db_path=self.db)
        self.assertEqual(profile.goal, "gain")
        self.assertEqual(planned_days(profile, self.today, self.today + timedelta(days=1), db_path=self.db),
                         {self.today + timedelta(days=1)})
        for element in [*app.markdown, *app.caption, *app.subheader, *app.info]:
            self.assertNotRegex(element.value, r"[\u4e00-\u9fff]")
        self.assertTrue(any("Protein " in c.value and "Carbs " in c.value and "Fat " in c.value for c in app.caption))
        app.session_state["ui_lang"] = "zh"
        app.run()
        self.assertTrue(any(b.label == "换到其他休息日" for b in app.button))

    def test_calendar_cross_week_preview_cancel_and_concurrent_move(self):
        profile = Profile(age=29, height_cm=170, weight_kg=64, activity="regular", start=self.today)
        save_profile(profile, db_path=self.db)
        end = self.today + timedelta(days=13)
        alternative = self.today + timedelta(days=8)
        days = planned_days(profile, self.today, end, db_path=self.db)
        app = AppTest.from_string(self.app_source)
        app.session_state["view"] = "calendar"
        app.run()
        for attempt in ("cancel", "stale"):
            if not any(b.key == f"move_option_{alternative}" for b in app.button):
                app.button(key="open_move_days").click().run()
            app.button(key=f"move_option_{alternative}").click().run()
            self.assertFalse(app.exception)
            expected = move_targets(profile, self.today, alternative, days)
            comparison = next(m.value for m in app.markdown if "减少 " in m.value)
            for before, after in expected:
                self.assertIn(f"{span(before.kcal)} → **{span(after.kcal)} kcal**", comparison)
            self.assertTrue(any("跨周" in s.value for s in app.caption))
            self.assertEqual(planned_days(profile, self.today, end, db_path=self.db), days)
            if attempt == "cancel":
                app.button(key="cancel_training_move").click().run()
                self.assertEqual(planned_days(profile, self.today, end, db_path=self.db), days)
            else:
                # Another browser moves a different workout across the same two weeks.
                other = self.today + timedelta(days=2)
                new = self.today + timedelta(days=10)
                self.assertTrue(move_workout(profile, other, new, db_path=self.db))
                app.button(key="confirm_training_move").click().run()
                self.assertTrue(any("未保存" in m.value for m in app.info))
                self.assertEqual(planned_days(profile, self.today, end, db_path=self.db), (days - {other}) | {new})

    def test_logged_workout_and_unavailable_rest_days_cannot_be_selected(self):
        p = Profile(age=28, height_cm=170, weight_kg=65, activity="regular", start=self.today)
        save_profile(p, db_path=self.db)
        prefs = TrainingPreferences(weekdays=[self.today.weekday()], since=self.today)
        p = save_training_preferences(p, prefs, db_path=self.db)
        save_training_log(p, self.today, self.today, "missed", {}, db_path=self.db)
        app = AppTest.from_string(self.app_source)
        app.session_state["view"] = "calendar"
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(any(b.key == "open_move_days" for b in app.button))
        future = self.today + timedelta(days=7)
        next(b for b in app.button if (b.key or "").startswith(f"cal_day_{future}_")).click().run()
        self.assertTrue(any("暂无符合" in c.value for c in app.caption))
        self.assertFalse(any(b.key == "open_move_days" for b in app.button))
