import unittest

from streamlit.testing.v1 import AppTest

from catalog import load_foods
from recognition import Dish, MealPhoto, VisibleFood, resolve_photo


def visible(en, zh, low, high):
    return VisibleFood(english=en, chinese=zh, low_g=low, high_g=high)


def partial_draft():
    main = Dish(whole=visible("house noodle plate", "招牌拌面", 320, 400), parts=[
        visible("unknown staple", "不明主食", 210, 270),
        visible("fried shallots", "油葱酥", 4, 8)])
    side = Dish(whole=visible("fried shallots", "油葱酥", 10, 14), parts=[])
    draft = resolve_photo(MealPhoto(dishes=[main, side], portion_note="", uncertain_items=[]), load_foods(), "test")
    draft["id"] = "regression"
    return draft


class MainDishReviewTests(unittest.TestCase):
    def test_parenthetical_serving_detail_keeps_recipe_modifiers(self):
        foods = load_foods()
        self.assertEqual(foods.photo_match("Steamed white rice (150 g)", ""), "white-rice")
        self.assertEqual(foods.photo_match("", "白饭（小碗）"), "white-rice")
        self.assertNotEqual(foods.photo_match("steamed white rice (with butter)", ""), "white-rice")
        self.assertIsNone(foods.photo_match("noodles (unknown sauce and filling)", ""))
        self.assertEqual(foods.photo_match("Masala dosa", ""), "sgstudy-marsala-thosai")

    def test_only_components_from_the_selected_group_are_replaced(self):
        draft = partial_draft()
        group, = draft["input"]["main_dishes"]
        self.assertEqual(group["component_grams"], {"tfda-P0200601": 6})
        self.assertEqual(draft["input"]["suggested_grams"]["tfda-P0200601"], 18)
        script = ("import streamlit as st\nfrom meal_review import review_meal\n"
                  "st.session_state.ui_lang='en'\n"
                  f"res=review_meal({draft!r})\nif res: st.session_state.result=res")
        app = AppTest.from_string(script, default_timeout=20).run()
        self.assertFalse(app.exception)
        self.assertTrue(any("main dish is incomplete" in w.value for w in app.warning))
        field = next(t for t in app.text_input if t.label == "Search for a whole dish")
        field.set_value("ban mian").run()
        next(b for b in app.button if b.label == "Use this dish").click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.warning)
        next(b for b in app.button if b.label == "Ate it all · Log meal").click().run()
        saved, items = app.session_state.result
        self.assertEqual({i["food_id"]: i["confirmed_g"] for i in items},
                         {"ban-mian": 360, "tfda-P0200601": 12})
        self.assertEqual(saved["input"]["coverage_decisions"][0]["scope"], "whole_dish")
        self.assertFalse(saved["input"]["partial_record"])
        app.multiselect[0].unselect("ban-mian").run()
        self.assertFalse(app.exception)
        self.assertTrue(any("main dish is incomplete" in w.value for w in app.warning))
        self.assertFalse(any(b.label == "Ate it all · Log meal" for b in app.button))
