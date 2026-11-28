import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from meals import (
    SG_TIME, claim_pending, clear_diary, create_pending, discard_pending, draft_cursor,
    export_pending, finish_pending, get_pending, list_meals, list_pending, make_draft,
    open_db, restore_pending, save_meal, update_pending,
)


class PendingMealTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "diary.sqlite3"
        self.draft = make_draft("photo", "meal.jpg", {"white-rice": 100}, [])
        self.draft["captured_at"] = (datetime.now(SG_TIME) - timedelta(days=1)).isoformat()
        self.jpeg = b"test compressed meal"
        self.item = {"nutrients": {"kcal": 100, "fat_g": 0, "protein_g": 5, "carb_g": 20}}
        self.assertTrue(create_pending(self.draft, self.jpeg, db_path=self.path))

    def test_lock_reopen_and_atomic_capture_day_confirmation(self):
        self.assertFalse(create_pending(self.draft, self.jpeg, db_path=self.path))
        restored, = list_pending(db_path=self.path)
        self.assertEqual(restored["photo"], self.jpeg)
        day = datetime.fromisoformat(restored["captured_at"]).date()
        self.assertEqual(list_meals(day, db_path=self.path), [])
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: save_meal(restored, [self.item], db_path=self.path), range(2)))
        self.assertCountEqual(results, [True, False])
        self.assertFalse(create_pending(self.draft, self.jpeg, db_path=self.path))
        self.assertEqual(list_pending(db_path=self.path), [])
        meal, = list_meals(day, db_path=self.path)
        self.assertEqual(meal["input"]["captured_at"], restored["captured_at"])
        self.assertEqual(meal["totals"]["kcal"], 100)

    def test_recognition_retry_manual_correction_and_discard(self):
        key = self.draft["id"]
        with ThreadPoolExecutor(3) as pool:
            claims = list(pool.map(lambda _: claim_pending(key, db_path=self.path), range(3)))
        lease, = [value for value in claims if value is not None]
        self.assertTrue(finish_pending({**self.draft, "status": "failed"}, claim=lease, db_path=self.path))
        retry = claim_pending(key, db_path=self.path)
        self.assertTrue(retry)
        with closing(open_db(self.path)) as db, db:
            db.execute("UPDATE pending SET lease_until = 0 WHERE id = ?", (key,))
        takeover = claim_pending(key, db_path=self.path)
        self.assertTrue(takeover)
        ready = {**self.draft, "status": "ready"}
        self.assertFalse(finish_pending(ready, claim=retry, db_path=self.path))
        self.assertTrue(update_pending(ready, db_path=self.path))
        self.assertFalse(finish_pending(ready, claim=takeover, db_path=self.path))
        self.assertIsNone(claim_pending(key, db_path=self.path))
        self.assertTrue(discard_pending(key, db_path=self.path))
        self.assertFalse(update_pending(ready, db_path=self.path))
        self.assertFalse(save_meal(ready, [self.item], db_path=self.path))
        self.assertFalse(create_pending(self.draft, self.jpeg, db_path=self.path))

    def test_rehydrate_from_browser_after_cloud_disk_reset(self):
        new_path = self.path.with_name("new-disk.sqlite3")
        hydrate = export_pending(db_path=self.path)
        self.assertEqual(len(hydrate["rows"]), 1)
        self.assertEqual(list_pending(db_path=new_path), [])
        restore_pending([*hydrate["rows"], {"id": "corrupt"}], db_path=new_path)
        recovered = get_pending(self.draft["id"], db_path=new_path)
        self.assertEqual(recovered, get_pending(self.draft["id"], db_path=self.path))
        self.assertEqual(draft_cursor(db_path=new_path)[2], 1)
        self.assertTrue(save_meal(recovered, [self.item], db_path=new_path))
        restore_pending(hydrate["rows"], db_path=new_path)
        self.assertEqual(export_pending(db_path=new_path)["rows"], [])
        self.assertEqual(len(list_pending(db_path=self.path)), 1)
        clear_diary(db_path=self.path)
        self.assertEqual(export_pending(db_path=self.path)["rows"], [])
