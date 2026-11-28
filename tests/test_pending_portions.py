import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from meals import (SG_TIME, create_pending, discard_pending, export_pending, get_pending, list_meals,
                   make_draft, restore_pending, update_pending_portion)


def open_diary(language):
    app = AppTest.from_string("from app import main\nmain(public_demo=True)", default_timeout=20)
    app.query_params["lang"] = language
    return app.run()


def control(app, suffix):
    return next(w for w in app.get("button_group") if w.key.endswith(suffix))


class PendingPortionsTests(unittest.TestCase):
    def test_reconnect_switch_language_variant_and_confirm_once(self):
        whole = {"white-rice": 200, "boiled-egg": 50}
        parts = {"white-rice": 120, "boiled-egg": 50}
        draft = make_draft("text", "test servings", whole, [])
        draft["variants"] = {"整道菜": {"suggested_grams": whole}, "按配料": {"suggested_grams": parts}}
        key = draft["id"]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "review.sqlite3"
            create_pending(draft, db_path=path)
            with patch("app.cloud_diary", return_value=path):
                first = open_diary("en")
                control(first, "-eaten-white-rice-en").set_value(2).run()
                control(first, "-eaten-boiled-egg-en").set_value(1).run()
                control(first, "-mode-en").set_value("按配料").run()
                self.assertEqual(control(first, "-eaten-white-rice-en").value, 4)
                self.assertEqual(control(first, "-eaten-boiled-egg-en").value, 1)
                control(first, "-eaten-white-rice-en").set_value(3).run()
                # Streamlit can deserialize a disappearing control as None on mobile.
                control(first, "-eaten-white-rice-en").set_value(None).run()
                self.assertFalse(first.exception)
                self.assertEqual(get_pending(key, db_path=path)["portion_review"]["shares"]["按配料"]["white-rice"], 3)
                control(first, "ui_language_control").set_value("zh").run()
                self.assertFalse(first.exception)
                self.assertEqual(control(first, "-eaten-white-rice").value, 3)
                self.assertEqual(list_meals(datetime.now(SG_TIME).date(), db_path=path), [])

                fresh = open_diary("zh")
                self.assertEqual(control(fresh, "-mode").value, "按配料")
                self.assertEqual(control(fresh, "-eaten-white-rice").value, 3)
                self.assertEqual(control(fresh, "-eaten-boiled-egg").value, 1)
                control(fresh, "-mode").set_value("整道菜").run()
                self.assertEqual(control(fresh, "-eaten-white-rice").value, 2)
                fresh.button(key=f"meal-{key}-confirm").click().run()
                self.assertFalse(fresh.exception)
                meal, = list_meals(datetime.now(SG_TIME).date(), db_path=path)
                self.assertEqual([i["confirmed_g"] for i in meal["items"]], [100, 12])
                self.assertIsNone(get_pending(key, db_path=path))
                self.assertFalse(update_pending_portion(key, "text", "整道菜", db_path=path))
                first.button(key=f"meal-{key}-confirm").click().run()
                self.assertEqual(len(list_meals(datetime.now(SG_TIME).date(), db_path=path)), 1)

    def test_independent_updates_backup_restore_and_discard(self):
        draft = make_draft("text", "rice and egg", {"white-rice": 180, "boiled-egg": 50}, [])
        key = draft["id"]
        with tempfile.TemporaryDirectory() as folder:
            path, recovered = (Path(folder) / name for name in ("first.sqlite3", "recovered.sqlite3"))
            create_pending(draft, db_path=path)
            for food, choice in (("white-rice", 0), ("boiled-egg", 2)):
                self.assertTrue(update_pending_portion(key, "text", "default", scope="default", food_id=food,
                                                       quarters=choice, db_path=path))
            self.assertFalse(update_pending_portion(key, "label", "different", db_path=path))
            restore_pending(export_pending(db_path=path)["rows"], db_path=recovered)
            restored = get_pending(key, db_path=recovered)
            self.assertEqual(restored["input"], draft["input"])
            self.assertEqual(restored["portion_review"]["shares"]["default"], {"white-rice": 0, "boiled-egg": 2})
            self.assertTrue(discard_pending(key, db_path=recovered))
            self.assertFalse(update_pending_portion(key, "text", "default", db_path=recovered))
            self.assertIsNone(get_pending(key, db_path=recovered))
