import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class DiaryLanguageTests(unittest.TestCase):
    SOURCE = """
import streamlit as st
from i18n import language_switch, tr
from meal_review import review_meal

language_switch()
st.title(tr("食阁记餐", "Meal Diary"))
draft = {"id": "lang-test", "input": {"method": "photo", "description": "example",
         "suggested_grams": {"white-rice": 180}, "unmatched": [], "uncertain_items": []}}
result = review_meal(draft)
if result:
    st.session_state.saved = result
"""

    def test_english_review_and_switch_keeps_food_ids_and_link_parameters(self):
        at = AppTest.from_string(self.SOURCE, default_timeout=20)
        at.query_params.update(lang="en", group="demo")
        at.run()
        self.assertFalse(at.exception)
        self.assertEqual(at.title[0].value, "Meal Diary")
        self.assertEqual(at.button(key="meal-lang-test-confirm").label, "Ate it all · Log meal")
        self.assertTrue(any("rice" in item.value.lower() for item in at.markdown))
        share = next(w for w in at.get("button_group") if w.key == "meal-lang-test-eaten-white-rice-en")
        share.set_value(2).run()
        next(w for w in at.get("button_group") if w.key == "ui_language_control").set_value("zh").run()
        self.assertFalse(at.exception)
        self.assertEqual(at.title[0].value, "食阁记餐")
        self.assertEqual(at.query_params["group"], "demo")
        self.assertEqual(at.button(key="meal-lang-test-confirm").label, "按实际份量确认记餐")
        at.button(key="meal-lang-test-confirm").click().run()
        draft, items = at.session_state.saved
        self.assertEqual(draft["id"], "lang-test")
        self.assertEqual([(item["food_id"], item["confirmed_g"]) for item in items], [("white-rice", 90)])

    def test_public_app_landing_text_log_diary_and_language_switch(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "private-test.sqlite3"
            with patch("app.cloud_diary", return_value=path):
                app = AppTest.from_string("from app import main\nmain(public_demo=True)", default_timeout=20)
                app.query_params["lang"] = "en"
                app.run()
                self.assertFalse(app.exception)
                self.assertEqual(app.title[0].value, "Meal Diary")
                self.assertTrue(any("sent to OpenAI" in c.value for c in app.caption))
                app.text_input[0].set_value("white rice, boiled egg")
                next(b for b in app.button if b.label == "Find foods and create draft").click().run()
                next(b for b in app.button if b.label == "Ate it all · Log meal").click().run()
                self.assertTrue(any("Meal added to diary" in m.value for m in app.markdown))
                next(w for w in app.get("button_group") if w.key.startswith("diary_nav_")).set_value("日记").run()
                self.assertEqual(app.date_input[0].label, "Meal date")
                self.assertTrue(any("rice" in e.label.lower() for e in app.expander))
                next(w for w in app.get("button_group") if w.key == "ui_language_control").set_value("zh").run()
                self.assertFalse(app.exception)
                self.assertEqual(app.date_input[0].label, "用餐日期")
                self.assertTrue(any("白饭" in e.label for e in app.expander))
                nav = next(w for w in app.get("button_group") if w.key.startswith("diary_nav_"))
                self.assertEqual(nav.value, "日记")
                self.assertEqual(list(nav.proto.default), [1])
                next(w for w in app.get("button_group") if w.key == "ui_language_control").set_value("en").run()
                nav = next(w for w in app.get("button_group") if w.key.startswith("diary_nav_"))
                self.assertEqual(nav.value, "日记")
                self.assertEqual(list(nav.proto.default), [1])
