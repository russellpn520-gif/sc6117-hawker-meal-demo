import unittest

from catalog import load_foods
from recognition import Dish, MealPhoto, VisibleFood, resolve_photo


def item(english, chinese, low, high):
    return VisibleFood(english=english, chinese=chinese, low_g=low, high_g=high)


class PartialPhotoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.foods = load_foods()

    def scan(self, *dishes):
        return resolve_photo(MealPhoto(dishes=list(dishes), uncertain_items=[], portion_note="参考餐盘大小"),
                             self.foods, "lunch.jpg")

    def test_chicken_plate_component_descriptions(self):
        labels = [
            ("蒸米饭", 130, 190), ("白切鸡肉片", 75, 125), ("焯青菜", 40, 60),
            ("酱油汁", 5, 15), ("清汤", 150, 220), ("油葱酥", 5, 7),
        ]
        draft = self.scan(*(Dish(whole=item("", name, low, high), parts=[]) for name, low, high in labels))
        view = draft["input"]
        self.assertEqual(view["suggested_grams"], {
            "white-rice": 160, "boiled-chicken": 100, "fdc-2709593": 50,
            "fdc-2707132": 185, "tfda-P0200601": 6,
        })
        self.assertEqual(view["unmatched_foods"], ["酱油汁"])
        sauce, = view["missing_items"]
        self.assertEqual((sauce["key"], sauce["low_g"], sauce["high_g"]), ("d3", 5, 15))
        self.assertEqual(sauce["alternatives"], ["fdc-2707442", "fdc-2707148"])

    def test_an_unknown_plate_cannot_become_a_complete_garnish(self):
        plate = item("house chicken rice platter", "招牌米饭套餐", 300, 450)
        garnish = item("fried shallots", "油葱酥", 5, 7)
        draft = self.scan(Dish(whole=plate, parts=[garnish]))
        partial = draft["variants"]["按配料"]
        self.assertEqual(draft["input"]["missing_items"], partial["missing_items"])
        self.assertEqual(partial["suggested_grams"], {"tfda-P0200601": 6})
        gap, = partial["missing_items"]
        self.assertEqual(gap["key"], "d0-gap")
        self.assertEqual(gap["alternatives"], [])
        whole = draft["variants"]["整道菜"]
        self.assertEqual(whole["suggested_grams"], {})
        self.assertIn("chicken-rice-plate", whole["missing_items"][0]["alternatives"])

    def test_components_do_not_include_the_parent_dish(self):
        plate = item("Hainanese chicken rice", "海南鸡饭", 300, 450)
        rice = item("chicken rice", "鸡油饭", 180, 240)
        chicken = item("sliced poached chicken", "白切鸡肉片", 70, 125)
        draft = self.scan(Dish(whole=plate, parts=[rice, chicken]))
        self.assertEqual(set(draft["variants"]["整道菜"]["suggested_grams"]), {"chicken-rice-plate"})
        parts = draft["variants"]["按配料"]
        self.assertEqual(set(parts["suggested_grams"]), {"fdc-2708407", "boiled-chicken"})
        self.assertFalse(parts["missing_items"])

    def test_ambiguous_components_remain_separate_and_do_not_infer_recipe(self):
        self.assertIsNone(self.foods.photo_match("unlabelled chicken slices", "不明做法的鸡肉片"))
        self.assertIsNone(self.foods.photo_match("sweet soy dressing", "甜酱油汁"))
        draft = self.scan(Dish(whole=item("unidentified mixed tray", "组合餐", 260, 350), parts=[
            item("unidentified staple", "不明主食", 120, 170),
            item("unknown protein", "不明主菜", 75, 110),
            item("fried shallots", "油葱酥", 5, 7),
        ]))
        rows = draft["input"]["missing_items"]
        self.assertEqual([r["name"] for r in rows], ["不明主食", "不明主菜"])
        self.assertEqual(len({r["key"] for r in rows}), len(rows))
