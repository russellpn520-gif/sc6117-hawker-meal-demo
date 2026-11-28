import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app import next_meal_due
from meal_drinks import KOPI_C_PORTIONS
from meals import (SG_TIME, get_profile, list_meals, list_pending,
                   load_foods, portion_items)
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
            self.assertFalse(any("-cup-" in (b.key or "") for b in ui.button))
            ui.text_input(key=prefix + "-search").set_value("Kopi O Kosong").run()
            ui.multiselect(key=prefix + "-foods-en").select("fdc-2710375").run()
            ui.button(key=prefix + "-confirm").click().run()
            self.assertFalse(ui.exception)
            record, = list_meals(self.today, db_path=path)
            grams = {item["food_id"]: item["confirmed_g"] for item in record["items"]}
            self.assertEqual(grams["fdc-2708407"], 90)
            self.assertEqual(grams["fdc-2710375"], load_foods()["fdc-2710375"].serving_g)
            self.assertTrue(record["has_thumbnail"])
            ui.button(key="leave_practice").click().run()
            self.assertTrue(ui.button(key="sample_chicken"))
            # The outer Cloud frame can still send the previous URL on the next rerun.
            ui.query_params["practice"] = "1"
            ui.run()
            self.assertTrue(ui.button(key="sample_chicken"))
            self.assertNotIn("practice", ui.query_params)
            self.assertIsNone(get_profile(db_path=self.diary))
            self.assertEqual(list_meals(self.today, db_path=self.diary), [])

    def test_practice_resumes_draft_and_inherits_real_food_preferences(self):
        prefs = Preferences(None, "vegan", ("soy",))
        save_preferences(self.diary, prefs)
        path, key = start_practice(self.diary, self.today, restart=True)
        self.assertEqual(start_practice(self.diary, self.today, restart=True), (path, key))
        self.assertEqual(len(list_pending(db_path=path)), 1)
        self.assertEqual(get_preferences(path), prefs)

    def test_local_drinks_are_searchable_and_mixed_cup_uses_ingredient_nutrients(self):
        foods = load_foods()
        for name, key in (("Kopi O Kosong", "fdc-2710375"), ("Kopi C Siu Dai", "kopi-c-siu-dai"),
                          ("Teh O Kosong", "fdc-173227"), ("无糖豆浆", "fdc-2705405")):
            self.assertEqual(foods.search(name)[0], key)
        cup = portion_items(foods, {"kopi-c-siu-dai": 200})[0]
        ingredients = portion_items(foods, KOPI_C_PORTIONS)
        for nutrient, amount in cup["nutrients"].items():
            self.assertAlmostEqual(amount, sum(i["nutrients"][nutrient] for i in ingredients))

    def test_three_hour_prompt_uses_latest_meal_time_not_confirmation_order(self):
        now = datetime.now(SG_TIME)
        old_meal = {"at": now, "input": {"captured_at": (now - timedelta(hours=4)).isoformat()}}
        self.assertTrue(next_meal_due([old_meal], now))
        self.assertFalse(next_meal_due([old_meal, {"at": now - timedelta(hours=1), "input": {}}], now))
        self.assertFalse(next_meal_due([], now))
