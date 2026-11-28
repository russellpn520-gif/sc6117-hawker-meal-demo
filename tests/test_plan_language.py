import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from streamlit.testing.v1 import AppTest

from meals import get_profile, planned_days, save_profile
from planning import Profile


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
from plan_ui import calendar_for_view, day_summary, profile_form, settings, training_plan
from planning import day_plan

db = Path({str(self.db)!r})
today = date.fromisoformat({self.today.isoformat()!r})
profile = get_profile(db_path=db)
if st.session_state.get("view") == "calendar":
    days = calendar_for_view(profile, today, db)
    if notice := st.session_state.pop("notice", None):
        st.info(notice)
    training_plan(profile, today, days, db)
    day_summary(profile, today, day_plan(profile, today, days), {{"kcal": 105, "protein_g": 0.2}})
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
        move = next(b for b in app.button if b.label == "Move today’s workout to tomorrow")
        move.click().run()
        self.assertTrue(any("Workout moved from Nov 28 to Nov 29" in x.value for x in app.info))
        profile = get_profile(db_path=self.db)
        self.assertEqual(profile.goal, "gain")
        self.assertEqual(planned_days(profile, self.today, self.today + timedelta(days=1), db_path=self.db),
                         {self.today + timedelta(days=1)})
        for element in [*app.markdown, *app.caption, *app.subheader, *app.info]:
            self.assertNotRegex(element.value, r"[\u4e00-\u9fff]")
        self.assertEqual({e.label for e in app.metric}, {"Remaining today", "Protein remaining"})
        app.session_state["ui_lang"] = "zh"
        app.run()
        self.assertTrue(any(b.label == "把明天的训练移到今天" for b in app.button))
