import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from meals import planned_days, save_profile
from planning import Profile


class CoachInterfaceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db = Path(folder.name) / "diary.sqlite3"
        self.today = date(2026, 11, 28)
        self.profile = Profile(nickname="Sam", age=30, height_cm=170, weight_kg=65,
                               activity="occasional", start=self.today)
        save_profile(self.profile, db_path=self.db)
        self.app = AppTest.from_string(f"""
from datetime import date
from pathlib import Path
import streamlit as st
from coach_ui import coach_entry
st.session_state.ui_lang = 'en'
coach_entry(date.fromisoformat('{self.today}'), Path({str(self.db)!r}), True)
""", default_timeout=15)

    def test_workout_preview_and_confirmation_from_dialog(self):
        app = self.app.run()
        self.assertFalse(app.exception)
        self.assertIsNone(app.session_state.mituan_state.get("pending"))
        self.assertFalse(any(button.key == "mituan_quick_training" for button in app.button))
        app.button(key="mituan_launcher").click().run()
        app.button(key="mituan_quick_training").click().run()
        app.button(key="mituan_follow_move").click().run()
        tomorrow = self.today + timedelta(days=1)
        self.assertEqual(planned_days(self.profile, self.today, tomorrow, db_path=self.db), {self.today})
        self.assertTrue(any("Proposed move" in m.value for m in app.markdown))
        app.button(key="mituan_confirm_move").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(planned_days(self.profile, self.today, tomorrow, db_path=self.db), {tomorrow})
        self.assertFalse(any(button.key == "mituan_confirm_move" for button in app.button))

    def test_free_question_needs_team_access_and_is_consumed_once(self):
        app = self.app.run()
        app.button(key="mituan_launcher").click().run()
        with patch("photo_access.coach_api_key", return_value=""):
            app.text_input(key="mituan_question").input("Describe my workout")
            next(b for b in app.button if b.label == "Send question").click().run()
        self.assertEqual(app.session_state.mituan_state["pending"], "Describe my workout")
        with patch("photo_access.coach_api_key", return_value="mock-only"), patch(
            "coach.ask_coach", return_value={"text": "Training answer"}
        ) as reader:
            app.run()
            app.run()
            reader.assert_called_once()
            self.assertIsNone(app.session_state.mituan_state["pending"])
            self.assertTrue(any(m.value == "Training answer" for m in app.markdown))
            app.session_state.diary_token = "different-device"
            app.run()
            self.assertEqual(app.session_state.mituan_state["turns"], [])

    def test_groceries_only_follow_an_available_meal_and_keep_its_budget(self):
        app = self.app.run()
        app.button(key="mituan_launcher").click().run()
        app.button(key="mituan_quick_dinner").click().run()
        self.assertFalse(any(b.key == "mituan_follow_shopping" for b in app.button))
        self.assertTrue(any(b.label == "Save food preferences" for b in app.button))
        app.multiselect(key="coach_food_preferences-allergies").select("none")
        next(b for b in app.button if b.label == "Save food preferences").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.session_state.mituan_state["turns"][-1]["reply"]["meal_context"])
        sample_context = {"budget_sgd": 3}
        with patch("photo_access.coach_api_key", return_value="mock-only"), patch("coach.ask_coach") as reader:
            reader.return_value = {"text": "Test budget dinner", "tool_names": ["PlanDinner"], "meal_context": sample_context}
            app.text_input(key="mituan_question").input("Dinner for three dollars?")
            next(b for b in app.button if b.label == "Send question").click().run()
            reader.return_value = {"text": "Test grocery list", "tool_names": ["PlanDinner"]}
            app.button(key="mituan_follow_shopping").click().run()
            self.assertEqual(reader.call_args.kwargs["meal_context"], sample_context)
            self.assertTrue(all(item["role"] == "user" for item in reader.call_args.kwargs["history"]))
