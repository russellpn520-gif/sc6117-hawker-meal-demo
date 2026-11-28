import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from catalog import load_foods
from meals import SG_TIME, allocate_grams, list_meals, match_text, portion_items, save_meal
from recognition import Dish, MealPhoto, VisibleFood, resolve_photo


def seen(english, chinese, low, high):
    return VisibleFood(english=english, chinese=chinese, low_g=low, high_g=high)


class FoodCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.foods = load_foods()

    def test_global_sources_and_per_100_vs_per_serving(self):
        self.assertGreater(len(self.foods), 19000)
        self.assertEqual(set(self.foods.counts), {"sr","fndds","cofid","tfda","wafct","sgstudy","hpb","gyg-au","recipe"})
        for query in ("鹰嘴豆泥", "ceviche", "burrito bowl", "英吉拉", "kimchi", "可颂", "couscous", "嫩豆腐"):
            self.assertIsNotNone(self.foods.exact_food(query), query)
        for query in ("Jollof", "GYG", "沙拉", "paneer", "pasta"):
            self.assertTrue(self.foods.search(query), query)
        kcal = lambda key,g: portion_items(self.foods,{key:g})[0]["nutrients"]["kcal"]
        self.assertEqual(kcal("white-rice",180),248)
        self.assertEqual(kcal("gyg-au-regular-mild-shredded-beef-brisket",455),692)
        self.assertEqual(kcal("fdc-2708555",200),290)
        self.assertEqual(match_text("Salsa, red 50g",self.foods)["input"]["suggested_grams"],{"fdc-2709738":50})
        self.assertEqual(match_text("半份白饭、水煮鸡",self.foods)["input"]["suggested_grams"],{"white-rice":90,"boiled-chicken":90})

    def test_photo_sizes_alternatives_and_unknowns(self):
        self.assertEqual(self.foods.photo_match("shredded cheese", "奶酪丝"), "fdc-2705704")
        self.assertEqual(self.foods.photo_match("grilled meat chunks", "烤肉块"), "fdc-2705819")
        self.assertEqual(self.foods.photo_match("cheddar cheese", "切达奶酪"), "fdc-2705709")
        parts=[seen("black beans","黑豆",40,80), seen("guacamole","牛油果酱",15,35),
               seen("tomato salsa","番茄莎莎",15,45),seen("cooked white rice","白饭",100,160)]
        side = Dish(whole=seen("tortilla chips","玉米脆片",15,25),parts=[])
        def scan(low,high):
            bowl=Dish(whole=seen("burrito bowl","墨西哥碗",low,high),parts=parts)
            return resolve_photo(MealPhoto(dishes=[bowl,side],portion_note="参照容器",uncertain_items=[]),
                                 self.foods,"meal.jpg")
        draft=scan(280,440)
        whole=draft["variants"]["整道菜"]
        ingredients=draft["variants"]["按配料"]
        self.assertEqual(whole["suggested_grams"],{"fdc-2708555":360,"fdc-2708202":20})
        self.assertEqual(ingredients["suggested_grams"],{"fdc-2707359":60,"fdc-2709307":25,
                         "fdc-2709738":30,"white-rice":130,"fdc-2708202":20})
        self.assertEqual(scan(90,150)["input"]["suggested_grams"]["fdc-2708555"],120)
        for bounds in [(0,0),(260,180),(1,50000)]:
            default=scan(*bounds)["input"]
            self.assertIsNone(default["portion_ranges"]["fdc-2708555"])
            self.assertEqual(default["suggested_grams"]["fdc-2708555"], self.foods["fdc-2708555"].serving_g)
        mystery=Dish(whole=seen("unlisted-zqx","未辨认菜品",0,0),parts=[])
        result=resolve_photo(MealPhoto(dishes=[mystery],portion_note="",uncertain_items=[]),self.foods,"x")
        self.assertFalse(result["input"]["suggested_grams"])
        self.assertIn("未辨认菜品",result["input"]["unmatched"])

    def test_net_weight_and_fraction_survive_save(self):
        served=allocate_grams({"white-rice":160,"fdc-2707359":90,"fdc-2709307":35},420,minimum=1)
        self.assertEqual(sum(served.values()),420)
        actual=allocate_grams(served,210)
        self.assertEqual(sum(actual.values()),210)
        self.assertEqual(allocate_grams(served,420,minimum=1),served)
        draft=match_text("黑豆、牛油果酱、白饭",self.foods)
        draft["input"].update(served_grams=served,eaten_fraction=0.5)
        items=portion_items(self.foods,actual)
        with TemporaryDirectory() as work:
            path=Path(work)/"test.sqlite3"
            save_meal(draft,items,db_path=path)
            save_meal(draft,items,db_path=path)
            records=list_meals(datetime.now(SG_TIME).date(),db_path=path)
        self.assertEqual(len(records),1)
        record=records[0]
        self.assertEqual(record["input"]["eaten_fraction"],0.5)
        self.assertEqual(sum(item["confirmed_g"] for item in record["items"]),210)
        self.assertTrue(all(item["source_url"].startswith("https://") for item in record["items"]))
