import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app import next_meal_due
from meal_drinks import add_drink, available_drinks
from meals import (SG_TIME, MealChangedError, create_pending, get_pending, get_profile, list_meals, list_pending,
                   load_foods, make_draft, portion_items, save_meal)
from nutrition_coach import Preferences, get_preferences, save_preferences
from sample_meal import practice_path, start_practice


class PracticeAndDrinksTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.diary = Path(folder.name) / "visitor.sqlite3"
        self.today = datetime.now(SG_TIME).date()

    def test_no_code_sample_uses_real_review_and_keeps_personal_diary_separate(self):
        with (patch("app.cloud_diary", return_value=self.diary),
              patch("app.photo_api_key", side_effect=AssertionError("sample requested a key")),
              patch("app.start_recognition", side_effect=AssertionError("sample started a model"))):
            ui = AppTest.from_string("from app import main\nmain(public_demo=True)", default_timeout=25)
            ui.query_params["lang"] = "en"
            ui.run().button(key="sample_chicken").click().run()
            self.assertFalse(ui.exception)
            path = practice_path(self.diary, self.today)
            draft, = list_pending(db_path=path)
            self.assertEqual(draft["status"], "ready")
            self.assertTrue(draft["photo"].startswith(b"\xff\xd8"))
            prefix = f"meal-{draft['id']}-v3"
            ui.segmented_control(key=prefix + "-eaten-fdc-2708407-en").set_value(2).run()
            ui.button(key=prefix + "-cup-kopi").click().run()
            self.assertEqual(ui.button(key=prefix + "-cup-kopi").label, "✓ Kopi O Kosong ×")
            ui.button(key=prefix + "-confirm").click().run()
            self.assertFalse(ui.exception)
            record, = list_meals(self.today, db_path=path)
            grams = {item["food_id"]: item["confirmed_g"] for item in record["items"]}
            self.assertEqual(grams["fdc-2708407"], 90)
            self.assertEqual(grams["fdc-2710375"], 200)
            self.assertTrue(record["has_thumbnail"])
            ui.button(key="leave_practice").click().run()
            self.assertTrue(ui.button(key="sample_chicken"))
            self.assertIsNone(get_profile(db_path=self.diary))
            self.assertEqual(list_meals(self.today, db_path=self.diary), [])

    def test_practice_resumes_draft_and_inherits_real_food_preferences(self):
        prefs = Preferences(None, "vegan", ("soy",))
        save_preferences(self.diary, prefs)
        path, key = start_practice(self.diary, self.today, restart=True)
        self.assertEqual(start_practice(self.diary, self.today, restart=True), (path, key))
        self.assertEqual(len(list_pending(db_path=path)), 1)
        self.assertEqual(get_preferences(path), prefs)
        self.assertFalse(add_drink(path, key, "kopi_c"))
        self.assertFalse(add_drink(path, key, "soy"))
        self.assertEqual(set(available_drinks(prefs)), {"kopi", "teh"})

    def test_a_cup_is_saved_once_and_present_in_both_portion_views(self):
        draft = make_draft("photo", "rice", {"white-rice": 100}, [])
        draft.update(status="ready", variants={"按配料": {"suggested_grams": {"white-rice": 100}}})
        create_pending(draft, db_path=self.diary)
        self.assertTrue(add_drink(self.diary, draft["id"], "kopi_c"))
        self.assertFalse(add_drink(self.diary, draft["id"], "kopi_c"))
        saved = get_pending(draft["id"], db_path=self.diary)
        self.assertEqual(saved["input"]["suggested_grams"], saved["variants"]["按配料"]["suggested_grams"])
        self.assertEqual(sum(saved["input"]["suggested_grams"].values()), 300)
        self.assertEqual(saved["quick_drinks"], ["kopi_c"])
        with self.assertRaises(MealChangedError):
            save_meal(draft, portion_items(load_foods(), {"white-rice": 100}), db_path=self.diary)
        self.assertIsNotNone(get_pending(draft["id"], db_path=self.diary))

    def test_three_hour_prompt_uses_latest_meal_time_not_confirmation_order(self):
        now = datetime.now(SG_TIME)
        old_meal = {"at": now, "input": {"captured_at": (now - timedelta(hours=4)).isoformat()}}
        self.assertTrue(next_meal_due([old_meal], now))
        self.assertFalse(next_meal_due([old_meal, {"at": now - timedelta(hours=1), "input": {}}], now))
        self.assertFalse(next_meal_due([], now))
