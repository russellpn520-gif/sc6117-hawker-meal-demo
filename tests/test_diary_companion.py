import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image
from streamlit.testing.v1 import AppTest

from meals import (SG_TIME, clear_diary, create_pending, export_pending, list_meals, load_foods,
                   make_draft, meal_thumbnail, open_db, portion_items, recent_activity, save_meal)
from mobile_ui import _meter
from training_coach import LOG_SCHEMA


class DiaryCompanionTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "diary.sqlite3"
        self.today = datetime.now(SG_TIME).date()
        self.items = portion_items(load_foods(), {"white-rice": 90})

    def test_thumbnail_is_small_private_and_keeps_only_an_image(self):
        raw = BytesIO()
        exif = Image.Exif()
        exif[315] = "private camera owner"
        Image.effect_noise((1200, 800), 100).convert("RGB").save(raw, "JPEG", quality=90, exif=exif)
        draft = make_draft("photo", "", {"white-rice": 180}, [])
        create_pending(draft, raw.getvalue(), db_path=self.path)
        self.assertTrue(save_meal(draft, self.items, db_path=self.path))
        self.assertFalse(save_meal(draft, self.items, db_path=self.path))
        record, = list_meals(self.today, db_path=self.path)
        self.assertTrue(record["has_thumbnail"])
        self.assertNotIn("thumbnail", record)
        jpeg = meal_thumbnail(record["id"], db_path=self.path)
        self.assertGreater(len(jpeg), 0)
        self.assertLessEqual(len(jpeg), 25_000)
        with Image.open(BytesIO(jpeg)) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertLessEqual(max(image.size), 320)
            self.assertEqual(len(image.getexif()), 0)
        self.assertEqual(export_pending(db_path=self.path)["rows"], [])
        self.assertIsNone(meal_thumbnail(record["id"], db_path=self.path.with_name("other.sqlite3")))
        clear_diary(db_path=self.path)
        self.assertIsNone(meal_thumbnail(record["id"], db_path=self.path))

    def test_upgrades_old_diary_in_two_tabs_and_preserves_record(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE meals (id TEXT PRIMARY KEY, day TEXT, confirmed_at TEXT, input TEXT, items TEXT, totals TEXT)")
            db.execute("INSERT INTO meals VALUES ('legacy', ?, ?, '{}', '[]', '{}')",
                       (self.today.isoformat(), datetime.now(SG_TIME).isoformat()))
        with ThreadPoolExecutor(2) as pool:
            copies = list(pool.map(lambda _: list_meals(self.today, db_path=self.path), range(2)))
        for records in copies:
            self.assertEqual([(r["id"], r["has_thumbnail"]) for r in records], [("legacy", False)])
        self.assertIsNone(meal_thumbnail("legacy", db_path=self.path))

    def test_label_and_damaged_photo_still_log_without_thumbnail(self):
        valid = BytesIO()
        Image.new("RGB", (40, 40)).save(valid, "PNG")
        for method, photo in (("label", valid.getvalue()), ("photo", b"older unreadable photo")):
            draft = make_draft(method, "", {}, [])
            create_pending(draft, photo, db_path=self.path)
            self.assertTrue(save_meal(draft, self.items, db_path=self.path))
            self.assertIsNone(meal_thumbnail(draft["id"], db_path=self.path))

    def test_rhythm_uses_meal_date_and_only_completed_training(self):
        draft = make_draft("text", "rice", {"white-rice": 90}, [])
        draft["captured_at"] = (datetime.now(SG_TIME) - timedelta(days=1)).isoformat()
        create_pending(draft, db_path=self.path)
        save_meal(draft, self.items, db_path=self.path)
        with closing(open_db(self.path)) as db, db:
            db.execute(LOG_SCHEMA)
            for offset, status in ((0, "comfortable"), (2, "missed"), (6, "challenging"), (7, "comfortable")):
                db.execute("INSERT INTO training_log VALUES (?, ?, '{}', '{}')",
                           ((self.today - timedelta(days=offset)).isoformat(), status))
            db.execute("INSERT INTO workouts VALUES (?)", ((self.today - timedelta(days=3)).isoformat(),))
        self.assertEqual(recent_activity(self.today, db_path=self.path),
                         {self.today - timedelta(days=n) for n in (0, 1, 6)})

    def test_progress_uses_range_and_receipt_reflects_actual_portion(self):
        def meter(current, high, complete=True):
            return _meter("Energy", str(current), "kcal", current, "Target 100", (100, high), complete)

        self.assertIn("width:60.00%", meter(60, 110))
        self.assertIn("in-range", meter(100, 110))
        self.assertIn("above-range", meter(120, 110))
        self.assertIn("in-range", meter(150, None))
        self.assertNotIn("above-range", meter(120, 110, complete=False))
        guest = _meter("Energy", "60", "kcal", 60, "", None, True)
        self.assertIn("no-target", guest)
        self.assertNotIn('role="progressbar"', guest)
        app = AppTest.from_string("""
import streamlit as st
from meals import load_foods, portion_items, total_nutrients
from mobile_ui import saved_receipt
st.session_state.ui_lang = 'en'
items = portion_items(load_foods(), {'white-rice': 90})
saved_receipt({'items': items, 'totals': total_nutrients([x['nutrients'] for x in items]),
               'input': {'eaten_fractions': {'white-rice': .5}}}, just_saved=True)
""").run()
        self.assertFalse(app.exception)
        self.assertIn("half eaten", app.caption[0].value)
        self.assertIn(f"{self.items[0]['nutrients']['protein_g']:.1f} g", app.caption[0].value)
