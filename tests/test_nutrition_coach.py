import dataclasses
import itertools
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import nutrition_coach as nc
from streamlit.testing.v1 import AppTest


# Manual fixture, in cents, based on the independent shopping basket for each recipe.
# Plant and animal ingredients are classified here without using the solver's tags.
# Includes both affordable and impossible profiles; the entire grid is synthetic.
MENU = {
    "Ginger chicken and broccoli rice": (349, {"chicken", "rice", "greens", "ginger"}),
    "Tilapia and ginger rice": (476, {"fish", "rice", "greens", "ginger"}),
    "Tomato and black bean rice bowl": (148, {"tomato", "black_bean", "rice", "oil"}),
    "Tofu and broccoli rice": (202, {"tofu", "rice", "greens", "ginger"}),
    "Egg and tofu rice": (199, {"egg", "tofu", "rice", "cucumber"}),
    "Chickpea, tomato and quinoa bowl": (205, {"chickpea", "tomato", "quinoa", "oil"}),
    "Baked sweet potato with lentils": (263, {"sweet_potato", "lentil", "tomato", "oil"}),
    "Tomato and lentil pasta": (157, {"pasta", "lentil", "tomato", "oil"}),
}


def constraint_cases():
    diet_block = {"any": set(), "vegan": {"chicken", "fish", "egg"},
                  "vegetarian": {"chicken", "fish"}, "pescatarian": {"chicken"}}
    allergen_block = {"soy": {"tofu"}, "egg": {"egg"}, "fish": {"fish"},
                      "gluten": {"pasta"}, "peanut": set(), "shellfish": set()}
    for diet, limit, allergens, avoid in itertools.product(
        diet_block, (100, 150, 200, 300, 500),
        ((), ("soy",), ("egg",), ("fish",), ("gluten", "soy"), ("peanut", "shellfish")),
        ((), ("rice",), ("tomato",), ("rice", "tomato")),
    ):
        blocked = set(avoid) | diet_block[diet]
        for tag in allergens:
            blocked |= allergen_block[tag]
        eligible = {name for name, (cost, foods) in MENU.items() if cost <= limit and not foods & blocked}
        yield nc.Preferences(limit, diet, allergens, avoid), eligible


class DinnerTests(unittest.TestCase):
    def test_constraint_grid(self):
        served = withheld = 0
        for prefs, eligible in constraint_cases():
            plan = nc.plan_dinner(prefs, remaining_kcal=550, remaining_protein=32)
            if eligible:
                self.assertIsNotNone(plan, prefs)
                name = plan["recipe"].names[1]
                self.assertIn(name, eligible, prefs)
                self.assertEqual(plan["cost_cents"], MENU[name][0])
                self.assertEqual(plan["cost_cents"], sum(line[2] for line in plan["shopping"]))
                self.assertLessEqual(plan["cost_cents"], prefs.budget_cents)
                served += 1
            else:
                self.assertIsNone(plan, prefs)
                withheld += 1
        self.assertEqual(served + withheld, 480)
        self.assertGreater(min(served, withheld), 0)

    def test_filters_and_reference_weights(self):
        prefs = nc.Preferences(700, "any", ())
        for recipe in nc.RECIPES:
            with self.subTest(recipe=recipe.names[1]), patch("nutrition_coach.RECIPES", (recipe,)):
                plan = nc.plan_dinner(prefs)
                self.assertEqual(plan["cost_cents"], MENU[recipe.names[1]][0])
                self.assertTrue(all(i["source_url"].startswith("https://") for i in plan["items"]))
                for nutrient, total in plan["nutrients"].items():
                    expected = sum(i["reference_nutrients"][nutrient] * i["confirmed_g"] / i["reference_g"] for i in plan["items"])
                    self.assertAlmostEqual(total, expected)
        chicken = nc.RECIPES[0]
        with patch("nutrition_coach.RECIPES", (chicken,)):
            needed = {key: (amount, cents) for key, amount, cents in nc.plan_dinner(prefs)["shopping"]}
            self.assertEqual(needed["chicken"], (154, 239))  # 115 g served from 154 g raw at S$1.55/100 g
            self.assertEqual(needed["rice"], (69, 20))
        missing = nc.Recipe(("?", "?"), (("unassessed_sauce", 12),))
        with patch("nutrition_coach.RECIPES", (missing,)):
            self.assertIsNone(nc.plan_dinner(prefs))

    def test_stored_preferences_unknown_allergies_and_temporary_budget(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "new.db"
            self.assertIsNone(nc.get_preferences(path))
            self.assertIn("Set your", nc.dinner_reply(path, lang="en"))
            prefs = nc.Preferences(150, "vegan", ("egg",), other_restriction="")
            nc.save_preferences(path, prefs)
            self.assertEqual(nc.get_preferences(path), prefs)
            self.assertEqual(nc.plan_dinner(prefs, budget_sgd=800)["limit_cents"], 150)
            self.assertIsNone(nc.plan_dinner(prefs, budget_sgd="1.479"))
            self.assertIsNone(nc.plan_dinner(prefs, budget_sgd="not a price"))
            self.assertIn("S$1.48", nc.dinner_reply(path, lang="en", shopping=True))
            nc.save_preferences(path, dataclasses.replace(prefs, other_restriction="unlisted allergy"))
            self.assertNotIn("S$", nc.dinner_reply(path, shopping=True))
            nc.save_preferences(path, dataclasses.replace(prefs, allergies=("other",)))
            self.assertIn("unavailable", nc.dinner_reply(path, lang="en"))
            invalid = dataclasses.replace(prefs, allergies=("unrecognised",))
            self.assertIsNone(nc.plan_dinner(invalid))
            with self.assertRaises(ValueError):
                nc.save_preferences(path, invalid)

    def test_bilingual_preference_form_and_grocery_list(self):
        source = """
import streamlit as st
from nutrition_coach_ui import nutrition_preferences
from nutrition_coach import dinner_reply
nutrition_preferences(st.session_state.db, key="demo_prefs")
st.markdown(dinner_reply(st.session_state.db, lang=st.session_state.ui_lang, shopping=True))
"""
        with TemporaryDirectory() as folder:
            path = Path(folder) / "prefs.db"
            app = AppTest.from_string(source, default_timeout=15)
            app.session_state["db"] = path
            app.session_state["ui_lang"] = "en"
            app.run()
            app.button[0].click().run()
            self.assertTrue(app.warning)
            self.assertIsNone(nc.get_preferences(path))
            app.number_input(key="demo_prefs-budget").set_value(2.50)
            app.selectbox(key="demo_prefs-diet").set_value("vegan")
            app.multiselect(key="demo_prefs-allergies").set_value(["soy"])
            app.multiselect(key="demo_prefs-avoid").set_value(["pasta"])
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(nc.get_preferences(path), nc.Preferences(250, "vegan", ("soy",), ("pasta",)))
            self.assertTrue(any("Shopping list" in item.value and "S$1.48" in item.value for item in app.markdown))

            other = AppTest.from_string(source, default_timeout=15)
            other.session_state["db"], other.session_state["ui_lang"] = path, "zh"
            other.run()
            self.assertEqual(other.multiselect(key="demo_prefs-allergies").value, ["soy"])
            self.assertTrue(any("购物清单" in item.value for item in other.markdown))
            other.text_input(key="demo_prefs-other").set_value("其他食物过敏")
            other.button[0].click().run()
            self.assertFalse(other.exception)
            self.assertTrue(any("无法核实" in item.value and "S$" not in item.value for item in other.markdown))
