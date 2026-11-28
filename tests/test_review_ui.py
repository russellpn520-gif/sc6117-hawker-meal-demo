import unittest

from streamlit.testing.v1 import AppTest


def review_app(suggested, **extra):
    draft = {"id": "bowl", "input": {"method": "photo", "description": "test.jpg",
                                     "suggested_grams": suggested, "unmatched": []}, **extra}
    script = (
        "import streamlit as st\n"
        "from meal_review import review_meal\n"
        f"result = review_meal({draft!r})\n"
        "if result: st.session_state.confirmed = result\n"
    )
    return AppTest.from_string(script, default_timeout=20).run()


class MealReviewTests(unittest.TestCase):
    def test_one_tap_means_all_served_food(self):
        app = review_app({"fdc-2708555": 450, "fdc-2708202": 50})
        self.assertFalse(app.exception)
        self.assertNotIn("confirmed", app.session_state)
        button = app.button(key="meal-bowl-confirm")
        self.assertEqual(button.label, "全部吃完，确认记餐")
        button.click().run()
        draft, items = app.session_state.confirmed
        self.assertEqual(draft["id"], "bowl")
        self.assertEqual(draft["input"]["eaten_fraction"], 1.0)
        self.assertEqual([i["confirmed_g"] for i in items], [450, 50])

    def test_adjust_only_the_side_and_recalibrate(self):
        app = review_app({"fdc-2708555": 450, "fdc-2708202": 50})
        app.number_input(key="meal-bowl-net").set_value(400).run()
        app.button(key="meal-bowl-scale").click().run()
        shares = next(w for w in app.get("button_group") if w.label == "玉米脆片吃了多少？")
        shares.set_value(2).run()
        app.button(key="meal-bowl-confirm").click().run()
        self.assertFalse(app.exception)
        draft, items = app.session_state.confirmed
        self.assertEqual(sum(draft["input"]["served_grams"].values()), 400)
        self.assertEqual([i["confirmed_g"] for i in items], [360, 20])
        self.assertEqual(draft["input"]["eaten_fractions"], {"fdc-2708555": 1, "fdc-2708202": 0.5})
        self.assertEqual(draft["input"]["eaten_fraction"], 0.95)

    def test_empty_or_uneaten_meal_cannot_be_confirmed(self):
        empty = review_app({})
        self.assertTrue(empty.button(key="meal-bowl-confirm").disabled)
        empty.text_input(key="meal-bowl-search").set_value("白饭").run()
        empty.multiselect(key="meal-bowl-foods").select("white-rice").run()
        self.assertFalse(empty.button(key="meal-bowl-confirm").disabled)
        next(w for w in empty.get("button_group") if w.label == "白饭吃了多少？").set_value(0).run()
        self.assertTrue(empty.button(key="meal-bowl-confirm").disabled)

    def test_components_replace_whole_dish_and_keep_side_share(self):
        whole = {"fdc-2708555": 450, "fdc-2708202": 50}
        parts = {"white-rice": 200, "fdc-2707359": 70, "fdc-2708202": 50}
        variants = {"整道菜": {"suggested_grams": whole}, "按配料": {"suggested_grams": parts}}
        app = review_app(whole, variants=variants)
        next(w for w in app.get("button_group") if w.label == "玉米脆片吃了多少？").set_value(2).run()
        next(w for w in app.get("button_group") if w.label == "要调整哪一部分？").set_value("按配料").run()
        app.button(key="meal-bowl-confirm").click().run()
        draft, items = app.session_state.confirmed
        self.assertEqual(draft["input"]["portion_mode"], "按配料")
        self.assertEqual({i["food_id"]: i["confirmed_g"] for i in items},
                         {"white-rice": 200, "fdc-2707359": 70, "fdc-2708202": 25})
