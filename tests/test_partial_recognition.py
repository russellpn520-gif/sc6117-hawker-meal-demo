import unittest

from catalog import load_foods
from recognition import BilingualMealPhoto, Dish, MealPhoto, VisibleFood, resolve_photo, reviewable_photo


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

    def test_soup_and_rice_on_a_tray_use_their_own_references(self):
        tray = Dish(whole=item("Hainanese chicken rice", "海南鸡饭", 600, 920), parts=[
            item("Steamed Chicken Rice", "鸡饭米饭", 160, 240),
            item("poached chicken", "白切鸡肉", 100, 150),
            item("clear soup", "清汤", 160, 240),
            item("greens with soy sauce and fried shallots", "烫青菜配葱酥酱油", 100, 150),
        ])
        cucumber = Dish(whole=item("cucumber slices", "黄瓜片", 15, 35), parts=[])
        draft = self.scan(tray, cucumber)
        view = draft["input"]
        self.assertFalse(draft.get("variants"))
        self.assertEqual(view["suggested_grams"], {"boiled-chicken": 125, "fdc-2707132": 200, "fdc-2709784": 25})
        rice, greens, sauce = view["missing_items"]
        self.assertEqual((rice["low_g"], rice["high_g"]), (160, 240))
        self.assertEqual(rice["alternatives"], ["white-rice", "fdc-2708407"])
        self.assertEqual(greens["alternatives"], ["fdc-2709593"])
        self.assertIn("葱酥酱油", sauce["name"])
        self.assertFalse(sauce["alternatives"])
        self.assertEqual(reviewable_photo(draft), draft)

    def test_resume_older_tray_removes_unsafe_weights_and_candidates(self):
        whole = {"suggested_grams": {"chicken-rice-plate": 760}}
        parts = {"suggested_grams": {"sgstudy-steamed-chicken-rice": 200, "boiled-chicken": 150, "fdc-2707132": 200},
                 "portion_ranges": {"sgstudy-steamed-chicken-rice": [150, 250]},
                 "missing_items": [{"key": "cucumber", "name": "黄瓜片", "alternatives": ["steamed-fish"],
                                    "low_g": 15, "high_g": 35},
                                   {"key": "greens", "name": "烫青菜配葱酥酱油", "alternatives": ["steamed-fish"]}]}
        draft = {"id": "existing", "input": {**whole, "method": "photo"}, "variants": {"整道菜": whole, "按配料": parts}}
        fixed = reviewable_photo(draft)
        self.assertEqual(fixed["id"], "existing")
        self.assertFalse(fixed.get("variants"))
        view = fixed["input"]
        self.assertEqual(view["suggested_grams"], {"boiled-chicken": 150, "fdc-2707132": 200})
        cucumber, greens, sauce, rice = view["missing_items"]
        self.assertEqual(cucumber["alternatives"], ["fdc-2709784"])
        self.assertEqual((cucumber["low_g"], cucumber["high_g"]), (15, 35))
        self.assertEqual(greens["alternatives"], ["fdc-2709593"])
        self.assertFalse(sauce["alternatives"])
        self.assertEqual((rice["low_g"], rice["high_g"]), (150, 250))
        self.assertNotIn("steamed-fish", view["alternatives"])
        self.assertIs(reviewable_photo(fixed), fixed)

    def test_soup_already_separate_does_not_change_the_weighed_plate(self):
        plate = Dish(whole=item("Hainanese chicken rice", "海南鸡饭", 320, 380), parts=[])
        soup = Dish(whole=item("clear broth", "清汤", 150, 210), parts=[])
        view = self.scan(plate, soup)["input"]
        self.assertEqual(view["suggested_grams"], {"chicken-rice-plate": 350, "fdc-2707132": 180})

    def test_bilingual_chicken_plate_and_recovery_of_the_same_v2_draft(self):
        chicken = item("Poached chicken breast/thigh (sliced)", "白切鸡肉（切片）", 80, 110)
        sauce = item("Light soy/ginger sauce", "清淡酱汁（酱油/姜油）", 4, 10)
        greens = item("Blanched leafy greens (gai lan / Chinese broccoli style)", "青菜（类似芥兰）", 40, 70)
        shallots = item("Fried shallot garnish", "炸葱酥", 3, 7)
        rice = item("Plain cooked white rice", "白米饭（蒸）", 165, 225)
        broth = item("Clear broth with cilantro/scallion", "清汤（带香菜/葱）", 150, 230)
        bowl = item("Clear soup (small bowl)", "清汤（小碗）", 150, 230)
        plate = Dish(whole=item("Chicken meat, boiled", "白切鸡", 155, 185), parts=[chicken, sauce, greens, shallots])
        scan = BilingualMealPhoto(dishes=[plate, Dish(whole=rice, parts=[rice]), Dish(whole=bowl, parts=[broth])],
                                  uncertain_items=["酱汁用油量不明。"], uncertain_items_en=["Oil in the dressing is uncertain."],
                                  portion_note="根据餐盘大小估算。", portion_note_en="Estimated from the plates.")
        fresh = resolve_photo(scan, self.foods, "Meal photo")
        def old_row(identifier, seen):
            return {"key": identifier, "name": seen.chinese, "name_en": seen.english,
                    "low_g": seen.low_g, "high_g": seen.high_g,
                    "alternatives": ["fdc-2707442"] if seen == sauce else []}
        old_whole = {"suggested_grams": {"boiled-chicken": 170, "white-rice": 195},
                     "portion_ranges": {"boiled-chicken": [155, 185], "white-rice": [165, 225]},
                     "missing_items": [old_row("d2", bowl)]}
        old_parts = {"suggested_grams": {}, "portion_ranges": {}, "uncertain_items": scan.uncertain_items,
                     "uncertain_items_en": scan.uncertain_items_en,
                     "missing_items": [old_row(f"d{i}-p{j}", part) for i, dish in enumerate(scan.dishes)
                                       for j, part in enumerate(dish.parts)]}
        saved = {"id": "existing", "status": "ready", "input": {**old_whole, "method": "photo",
                 "photo_resolution_version": 2, "token_usage": {"total_tokens": 2406}},
                 "variants": {"整道菜": old_whole, "按配料": old_parts}}
        recovered = reviewable_photo(saved)
        self.assertEqual(recovered["input"]["token_usage"], {"total_tokens": 2406})
        for draft in (fresh, recovered):
            view = draft["input"]
            self.assertFalse(draft.get("variants"))
            self.assertEqual(view["suggested_grams"], {"boiled-chicken": 95, "fdc-2709593": 55, "tfda-P0200601": 5,
                                                       "white-rice": 195, "fdc-2707132": 190})
            self.assertEqual(view["portion_ranges"]["boiled-chicken"], [80, 110])
            self.assertEqual(view["unmatched_foods_en"], ["Light soy/ginger sauce"])
            row, = view["missing_items"]
            self.assertEqual((row["key"], row["low_g"], row["high_g"], row["alternatives"]), ("d0-p1", 4, 10, []))
            self.assertEqual(view["uncertain_items_en"], scan.uncertain_items_en)
            self.assertEqual(view["photo_resolution_version"], 3)
            self.assertIs(reviewable_photo(draft), draft)

    def test_photo_qualifiers_do_not_remove_additional_ingredients(self):
        self.assertIsNone(self.foods.photo_match("clear broth with noodles", "清汤面配肉"))
        self.assertIsNone(self.foods.photo_match("blanched greens with oyster sauce", "蚝油芥兰"))
        self.assertIsNone(self.foods.photo_match("soy ginger dressing", "酱油"))
