"""Coverage of the public, offline nearby-dinner path."""
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import nearby_hawker as nearby
from meals import clear_diary, discard_pending, get_pending, list_pending, load_foods, portion_items, total_nutrients
from nutrition_coach import ALLERGENS, DIETS, INGREDIENTS, Preferences, save_preferences


SAT = date(2026, 11, 28)
NTU = nearby.LANDMARKS["ntu"]["coords"]


class NearbyHawkerTests(unittest.TestCase):
    def test_directory_references_and_bilingual_rows(self):
        directory = nearby._directory()
        rows = directory["orders"]
        self.assertTrue(15 <= len(rows) <= 25)
        self.assertEqual(len(rows), len({row["id"] for row in rows}))
        for row in rows:
            with self.subTest(order=row["id"]):
                venue = directory["venues"][row["venue"]]
                self.assertTrue(directory["sources"][row["source"]].startswith("https://"))
                self.assertTrue(directory["sources"][venue["source"]].startswith("https://"))
                self.assertTrue(1 < venue["coords"][0] < 2 and 103 < venue["coords"][1] < 105)
                for values in (venue["names"], row["dish"], row["stall"], row["order"], row["note"]):
                    self.assertEqual(len(values), 2)
                    self.assertTrue(all(values))
                self.assertTrue(row["maps_query"])
                self.assertTrue(set(row["diets"]) <= DIETS.keys())
                self.assertTrue(set(row["ingredients"]) <= INGREDIENTS.keys())
                self.assertTrue(set(row["allergens"]) <= ALLERGENS.keys())
                self.assertTrue(set(row.get("checked_allergens", ())) <= ALLERGENS.keys())
                self.assertTrue(all(item["source_url"].startswith("https://")
                                    for item in portion_items(load_foods(), row["portion_items"])))

    def test_distances_are_local_and_sorted_within_equally_ranked_options(self):
        self.assertEqual(nearby.distance_m(NTU, NTU), 0)
        self.assertAlmostEqual(nearby.distance_m((1.3, 103.8), (1.3, 103.81)), 1112, delta=2)
        for landmark in nearby.LANDMARKS.values():
            result = nearby.recommend_nearby(landmark["coords"], SAT)
            self.assertEqual(len(result["cards"]), 3)
            self.assertTrue(all(c["distance_m"] < 2000 for c in result["cards"]))
        self.assertLess(nearby.recommend_nearby(NTU, SAT)["cards"][0]["distance_m"], 100)
        self.assertEqual(nearby.recommend_nearby((40.7, -74), SAT)["total"], 0)
        with self.assertRaises(ValueError):
            nearby.recommend_nearby((float("nan"), 100), SAT)

    def test_nearby_paging_repeats_only_after_available_cards(self):
        first = nearby.recommend_nearby(nearby.LANDMARKS["marina"]["coords"], SAT)
        second = nearby.recommend_nearby(nearby.LANDMARKS["marina"]["coords"], SAT, page=1)
        self.assertFalse({c["id"] for c in first["cards"]} & {c["id"] for c in second["cards"]})
        pages = (first["total"] + 2) // 3
        self.assertEqual(first, nearby.recommend_nearby(nearby.LANDMARKS["marina"]["coords"], SAT, page=pages))

    def test_official_cleaning_and_repairs_dates_are_inclusive(self):
        rows = [dict(name="Centre A", latitude_hc="1.30001", longitude_hc="103.80001",
                     q1_cleaningstartdate="3/2/2026", q1_cleaningenddate="5/2/2026",
                     q2_cleaningstartdate="NA", q2_cleaningenddate="NA",
                     other_works_startdate="31/8/2026", other_works_enddate="2/9/2026")]
        centre = nearby.read_nea_centres(rows)["Centre A"]
        self.assertEqual(centre["coords"], (1.30001, 103.80001))
        self.assertTrue(nearby._closed(centre, date(2026, 2, 3)))
        self.assertTrue(nearby._closed(centre, date(2026, 2, 5)))
        self.assertFalse(nearby._closed(centre, date(2026, 2, 6)))
        self.assertTrue(nearby._closed(centre, date(2026, 9, 1)))
        river = nearby.LANDMARKS["river"]["coords"]
        for day in (2, 3):
            result = nearby.recommend_nearby(river, date(2026, 12, day))
            self.assertIn("Zion Riverside Food Centre", [c[1] for c in result["closed"]])
            self.assertFalse(any(c["id"].startswith("zion-") for c in result["cards"]))
        self.assertNotIn("Zion Riverside Food Centre",
                         [c[1] for c in nearby.recommend_nearby(river, date(2026, 12, 4))["closed"]])
        self.assertTrue(nearby.recommend_nearby(river, date(2026, 12, 4))["schedule_covered"])
        self.assertFalse(nearby.recommend_nearby(river, date(2027, 1, 1))["schedule_covered"])

    def test_published_schedule_applies_to_draft_and_nearest_closed_venue(self):
        closed = date(2026, 12, 14)
        result = nearby.recommend_nearby(nearby.LANDMARKS["marina"]["coords"], closed)
        self.assertIn("Maxwell Food Centre", [c[1] for c in result["closed"]])
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                nearby.add_nearby_draft(Path(tmp) / "diary.sqlite", "maxwell-tiantian", closed)

    def test_saved_restrictions_exclude_conflicts_and_unverified_allergens(self):
        prefs = Preferences(None, "any", ("fish",))
        cards = nearby.recommend_nearby(NTU, SAT, preferences=prefs)["cards"]
        self.assertEqual([c["id"] for c in cards], ["ntu-veg-sub"])
        for allergens in (("egg",), ("gluten",), ("other",), ("celery",)):
            self.assertEqual(nearby.recommend_nearby(NTU, SAT, preferences=Preferences(None, "any", allergens))["total"], 0)
        stops = [Preferences(None, "vegan", None, ("tofu",)), Preferences(None, "any", None, (), "no garlic")]
        for preference in stops:
            self.assertEqual(nearby.recommend_nearby(nearby.LANDMARKS["marina"]["coords"], SAT,
                                                    preferences=preference)["total"], 0)
        vegan = nearby.recommend_nearby(nearby.LANDMARKS["marina"]["coords"], SAT,
                                        preferences=Preferences(None, "vegan", None))
        self.assertEqual([c["id"] for c in vegan["cards"]], ["lau-veggie"])

    def test_training_special_needs_both_training_and_room(self):
        for location in nearby.LANDMARKS.values():
            def first(training, kcal):
                return nearby.recommend_nearby(location["coords"], SAT, training=training,
                                               remaining_kcal=kcal, remaining_protein=25)["cards"][0]
            self.assertTrue(first(True, 850)["treat_friendly"])
            self.assertTrue(first(True, (850, 1050))["treat_friendly"])
            self.assertFalse(first(True, 849)["treat_friendly"])
            self.assertFalse(first(True, None)["treat_friendly"])
            self.assertFalse(first(False, 1000)["treat_friendly"])

    def test_card_addition_is_ready_editable_idempotent_and_revalidated(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "meal.sqlite"
            card = nearby.recommend_nearby(NTU, SAT)["cards"][0]
            token = str(uuid4())
            self.assertEqual(nearby.add_nearby_draft(path, card["id"], SAT, draft_id=token), token)
            draft = get_pending(token, db_path=path)
            self.assertEqual(draft["status"], "ready")
            self.assertEqual(draft["photo"], b"")
            self.assertEqual(draft["input"]["nearby_order_id"], card["id"])
            portions = portion_items(load_foods(), draft["input"]["suggested_grams"])
            self.assertEqual(card["totals"], total_nutrients([p["nutrients"] for p in portions]))
            self.assertEqual(nearby.add_nearby_draft(path, card["id"], SAT, draft_id=token), token)
            self.assertEqual(len(list_pending(db_path=path)), 1)
            discard_pending(token, db_path=path)
            with self.assertRaises(ValueError):
                nearby.add_nearby_draft(path, card["id"], SAT, draft_id=token)
            save_preferences(path, Preferences(None, "vegan", ("egg",), ("chicken",)))
            with self.assertRaises(ValueError):
                nearby.add_nearby_draft(path, card["id"], SAT)
            self.assertEqual(list_pending(db_path=path), [])

    def test_only_preset_identifier_persists_and_clear_resets_it(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "meal.sqlite"
            self.assertEqual(nearby.get_landmark(path), "ntu")
            nearby.save_landmark(path, "marina")
            self.assertEqual(nearby.get_landmark(path), "marina")
            with self.assertRaises(ValueError):
                nearby.save_landmark(path, "1.305,103.8")
            clear_diary(db_path=path)
            self.assertEqual(nearby.get_landmark(path), "ntu")
