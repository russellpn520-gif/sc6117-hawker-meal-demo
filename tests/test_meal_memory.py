import tempfile
import unittest
from pathlib import Path

from catalog import load_foods
from meal_memory import start_repeat, suggest_corrections, usual_meals
from meals import make_draft, portion_items, save_meal


class MealMemoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.diary = Path(temp.name) / "one.sqlite3"
        self.other = Path(temp.name) / "two.sqlite3"
        self.foods = load_foods()

    def confirmed(self, g, decisions=(), **changes):
        draft = make_draft("photo", "meal", {"white-rice": g}, [])
        draft["input"].update(served_grams={"white-rice": g}, partial_record=False, coverage_decisions=decisions)
        draft["input"].update(changes)
        save_meal(draft, portion_items(self.foods, {"white-rice": int(g / 2)}), db_path=self.diary)

    def test_repeat_uses_latest_served_not_eaten_weight_and_new_draft_identity(self):
        self.confirmed(120)
        self.confirmed(180)
        self.confirmed(250, partial_record=True)
        self.confirmed(310, served_grams=None)
        self.assertEqual(usual_meals(self.foods, self.diary), [{"white-rice": 180}])
        self.assertEqual(usual_meals(self.foods, self.other), [])
        a, b = (start_repeat({"white-rice": 180}) for _ in range(2))
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(a["input"]["suggested_grams"], {"white-rice": 180})

    def test_corrections_are_scoped_confirmable_and_private(self):
        def new():
            row = {"name_en": "House  rice", "alternatives": []}
            return {"input": {"method": "photo", "missing_items": [dict(row)], "main_dishes": [dict(row)],
                              "suggested_grams": {}}}
        self.confirmed(120, [{"name_en": "House rice", "food_id": "white-rice", "scope": "whole_dish"}])
        draft = new()
        self.assertFalse(suggest_corrections(draft, self.foods, self.other))
        self.assertTrue(suggest_corrections(draft, self.foods, self.diary))
        self.assertEqual(draft["input"]["main_dishes"][0]["alternatives"], ["white-rice"])
        self.assertEqual(draft["input"]["missing_items"][0]["alternatives"], [])
        self.assertEqual(draft["input"]["suggested_grams"], {})
        self.confirmed(180, [{"name_en": "House rice", "food_id": "ban-mian", "scope": "whole_dish"}])
        self.assertFalse(suggest_corrections(new(), self.foods, self.diary))
