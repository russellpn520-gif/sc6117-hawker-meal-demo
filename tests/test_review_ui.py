import unittest

from streamlit.testing.v1 import AppTest


def review_app(suggested, details=None, **extra):
    draft = {"id": "bowl", "input": {"method": "photo", "description": "test.jpg",
                                     "suggested_grams": suggested, "unmatched": [], **(details or {})}, **extra}
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

    def test_only_garnish_matched_requires_explicit_partial_save(self):
        details = {"unmatched_foods": ["蒸米饭", "白切鸡肉片", "焯青菜", "酱油汁", "清汤"]}
        app = review_app({"tfda-P0200601": 6}, details)
        self.assertFalse(app.exception)
        self.assertIn("5 项未计入", app.warning[0].value)
        self.assertTrue(any("已选食物小计约 **31 kcal**" in s.value for s in app.markdown))
        self.assertTrue(next(e for e in app.expander if e.label == "补选未匹配的食物").proto.expanded)
        self.assertFalse(any(b.label == "全部吃完，确认记餐" for b in app.button))
        self.assertNotIn("confirmed", app.session_state)
        app.button(key="meal-bowl-partial-confirm").click().run()
        saved, items = app.session_state.confirmed
        self.assertTrue(saved["input"]["partial_record"])
        self.assertEqual(saved["input"]["unmatched_foods"], details["unmatched_foods"])
        self.assertEqual(items[0]["confirmed_g"], 6)

    def test_fix_missing_with_photo_weight_and_explicit_omission(self):
        rice = {"name": "蒸米饭", "key": "rice", "alternatives": ["white-rice"], "low_g": 120, "high_g": 180}
        soup = {"name": "清汤", "key": "soup", "alternatives": [], "low_g": 0, "high_g": 0}
        app = review_app({"fdc-2708202": 6}, {"missing_items": [rice, soup], "unmatched": ["蒸米饭", "清汤"]})
        app.button(key="meal-bowl-rice-add-white-rice").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.number_input(key="meal-bowl-grams-white-rice").value, 150)
        self.assertEqual(app.warning[0].value, "还有 1 项未计入 · 清汤")
        app.button(key="meal-bowl-soup-omit").click().run()
        self.assertFalse(app.warning)
        app.button(key="meal-bowl-soup-undo").click().run()
        self.assertIn("清汤", app.warning[0].value)
        app.button(key="meal-bowl-soup-omit").click().run()
        app.button(key="meal-bowl-confirm").click().run()
        saved, items = app.session_state.confirmed
        self.assertFalse(saved["input"]["partial_record"])
        self.assertEqual(saved["input"]["unmatched"], [])
        self.assertEqual([item["confirmed_g"] for item in items], [6, 150])

    def test_deselecting_resolved_food_restores_guard_and_manual_search_works(self):
        app = review_app({"fdc-2708202": 6}, {"unmatched": ["陌生主食"]})
        app.text_input(key="meal-bowl-legacy-0-lookup").set_value("白饭").run()
        app.button(key="meal-bowl-legacy-0-use").click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.warning)
        app.multiselect(key="meal-bowl-foods").unselect("white-rice").run()
        self.assertIn("陌生主食", app.warning[0].value)
        self.assertFalse(any(b.label == "全部吃完，确认记餐" for b in app.button))

    def test_scale_uncertainty_alone_preserves_one_tap(self):
        app = review_app({"white-rice": 200}, {"unmatched": ["无比例尺，份量为估计"]})
        self.assertFalse(app.warning)
        self.assertEqual(app.button(key="meal-bowl-confirm").label, "全部吃完，确认记餐")
