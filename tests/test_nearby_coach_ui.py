from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from streamlit.testing.v1 import AppTest

from meals import SG_TIME, create_pending, load_foods, make_draft, portion_items, save_meal, save_profile
from nearby_hawker import NEA_SNAPSHOT_DATE, NEA_URL, get_landmark
from planning import Profile


class NearbyCoachScreenTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db = Path(folder.name) / "diary.sqlite"
        self.today = datetime.now(SG_TIME).date()

    def test_practice_coach_changes_greeting_and_keeps_move_free(self):
        save_profile(Profile(age=24, height_cm=165, weight_kg=60, activity="regular", start=self.today), db_path=self.db)
        app = AppTest.from_string(f"""
import streamlit as st
from datetime import date
from coach_ui import _greeting, _panel
st.session_state.ui_lang = 'en'
st.session_state.practice_mode = True
st.session_state.setdefault('mituan_state', dict(pending=None, turns=[], preferences=False))
today = date.fromisoformat('{self.today}')
st.write(_greeting(today, {str(self.db)!r}))
_panel(today, {str(self.db)!r}, True)
""").run()
        self.assertFalse(app.exception)
        self.assertIn("workout today", app.markdown[0].value)
        self.assertFalse(app.text_input)
        app.button(key="mituan_quick_move").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.button(key="mituan_confirm_move").label,
                         f"Confirm move to {(self.today + timedelta(days=1)):%d %b}")
        draft = make_draft("text", "rice", {"white-rice": 100}, [])
        create_pending(draft, db_path=self.db)
        save_meal(draft, portion_items(load_foods(), {"white-rice": 100}), db_path=self.db)
        app.run()
        self.assertIn("Meal’s in the diary", app.markdown[0].value)

    def test_future_radar_links_to_nea_and_remembers_landmark(self):
        outside_schedule = date(NEA_SNAPSHOT_DATE.year + 1, 1, 2)
        app = AppTest.from_string(f"""
from datetime import date
import streamlit as st
from nearby_ui import nearby_dinner
st.session_state.ui_lang = 'en'
nearby_dinner(st.session_state.setdefault('coach', {{}}), date.fromisoformat('{outside_schedule}'), {str(self.db)!r})
""").run()
        self.assertFalse(app.exception)
        schedule = next(caption.value for caption in app.caption if "outside the saved schedule" in caption.value)
        self.assertIn(NEA_URL, schedule)
        landmarks = next(group for group in app.get("button_group") if "radar_landmarks" in group.key)
        landmarks.set_value("marina").run()
        self.assertEqual(get_landmark(self.db), "marina")
        self.assertTrue(any("From Marina Bay" in caption.value for caption in app.caption))
