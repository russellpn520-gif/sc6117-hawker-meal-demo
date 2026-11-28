import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from meals import clear_diary, create_pending, load_foods, make_draft, portion_items, save_meal, save_profile
from planning import Profile


class HomeProgressTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "diary.sqlite3"
        self.profile = Profile(nickname="Sam", age=30, height_cm=170, weight_kg=65,
                               activity="occasional", start=date(2026, 11, 28))
        save_profile(self.profile, db_path=self.path)

    def home(self):
        app = AppTest.from_string("from app import main\nmain(public_demo=True)", default_timeout=20)
        app.query_params["lang"] = "en"
        return app.run()

    def test_first_meal_then_day_balance_and_offline_dinner(self):
        from coach import ask_coach

        with patch("app.cloud_diary", return_value=self.path):
            app = self.home()
            self.assertTrue(any("Today's energy target" in m.value for m in app.markdown))
            draft = make_draft("text", "rice", {"white-rice": 100}, [])
            draft["status"] = "ready"
            create_pending(draft, db_path=self.path)
            app.run()
            self.assertEqual(app.subheader[0].value, "Meal to confirm")
            next(b for b in app.button if b.label == "Ate it all · Log meal").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any("kcal left today" in m.value for m in app.markdown))
            self.assertTrue(any("g protein left" in c.value for c in app.caption))
            with patch("coach.ask_coach", wraps=ask_coach) as read, patch("photo_access.coach_api_key") as auth:
                app.button(key="home_dinner").click().run()
                app.run()
                self.assertFalse(app.exception)
                read.assert_called_once()
                self.assertEqual(read.call_args.kwargs["quick"], "dinner")
                auth.assert_not_called()

    def test_incomplete_meal_shows_recorded_subtotal(self):
        draft = make_draft("photo", "", {"white-rice": 80}, [])
        draft["input"].update(partial_record=True, unmatched_foods=["unidentified main"])
        save_meal(draft, portion_items(load_foods(), {"white-rice": 80}), db_path=self.path)
        with patch("app.cloud_diary", return_value=self.path):
            app = self.home()
        self.assertTrue(any("Logged subtotal" in m.value for m in app.markdown))
        self.assertFalse(any("kcal left today" in m.value for m in app.markdown))

    def test_guest_can_continue_to_dinner_and_log_another_meal_after_reopening(self):
        clear_diary(db_path=self.path)
        with patch("app.cloud_diary", return_value=self.path):
            app = self.home()
            self.assertEqual(app.subheader[0].value, "Log a meal")
            draft = make_draft("text", "rice", {"white-rice": 100}, [])
            draft["status"] = "ready"
            create_pending(draft, db_path=self.path)
            app.run()
            self.assertEqual(app.subheader[0].value, "Meal to confirm")
            self.assertFalse(any(b.key == "home_dinner" for b in app.button))
            next(b for b in app.button if b.label == "Ate it all · Log meal").click().run()
            self.assertTrue(any("Meal added to diary" in m.value for m in app.markdown))
            app = self.home()
            self.assertFalse(app.exception)
            self.assertTrue(any("Last meal" in m.value for m in app.markdown))
            self.assertTrue(any(b.key == "home_dinner" for b in app.button))
            self.assertTrue(any(e.label == "Log the next meal" for e in app.expander))
