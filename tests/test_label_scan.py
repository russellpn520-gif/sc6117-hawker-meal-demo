import json
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from langchain_openai import ChatOpenAI
from streamlit.testing.v1 import AppTest

from label_scan import check_energy_unit, empty_label, intake_units, label_item, read_label
from meals import SG_TIME, create_pending, get_pending, list_meals, make_draft


class LabelTests(unittest.TestCase):
    def setUp(self):
        self.panel = {**empty_label(), "product_name": "Plain milk", "basis": "100ml", "energy": 209.2,
                      "energy_unit": "kJ", "protein_g": 3.2, "carb_g": 5.0, "fat_g": 2.0,
                      "portion_size": 250.0, "portion_unit": "ml"}

    def test_shared_basis_units_and_kj(self):
        self.assertEqual(intake_units(self.panel), ["ml", "serving"])
        milk = label_item(self.panel, 0.5, "serving")
        self.assertAlmostEqual(milk["nutrients"]["kcal"], 62.5)
        self.assertAlmostEqual(milk["nutrients"]["protein_g"], 4)
        self.assertEqual(milk["nutrients"], label_item(self.panel, 125, "ml")["nutrients"])
        self.assertNotIn("confirmed_g", milk)
        for invalid in [None, 0, -1, float("inf")]:
            with self.assertRaises(ValueError):
                label_item(self.panel, invalid, "ml")
        with self.assertRaises(ValueError):
            label_item(self.panel, 1, "g")
        for nutr in ["energy", "protein_g", "carb_g", "fat_g"]:
            with self.assertRaises(ValueError):
                label_item({**self.panel, nutr: None}, 100, "ml")
        for basis in ("serving", "package"):
            snack = {**self.panel, "basis": basis, "portion_size": 40.0, "portion_unit": "g", "fat_g": 0}
            self.assertEqual(label_item(snack, 1.5, basis)["nutrients"], label_item(snack, 60, "g")["nutrients"])
            self.assertEqual(intake_units({**snack, "portion_size": None}), [basis])
        self.assertEqual(intake_units({**self.panel, "portion_unit": "g"}), ["ml"])

    def test_large_unit_discrepancy_requires_explicit_recheck_and_keeps_reading(self):
        panel = dict(self.panel, energy=209.2, energy_unit="kcal")
        self.assertTrue(check_energy_unit(panel))
        self.assertFalse(check_energy_unit(self.panel))
        self.assertFalse(check_energy_unit({**panel, "energy": 0.0}))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "checked.sqlite3"
            draft = make_draft("label", "", {}, [])
            draft["input"].update(label=panel, eaten_amount=100.0, eaten_unit="ml")
            create_pending(draft, db_path=path)
            app = AppTest.from_string("from label_ui import review_label\n"
                                      f"review_label({draft!r}, {str(path)!r})").run()
            self.assertFalse(app.exception)
            self.assertTrue(app.button[0].disabled)
            self.assertEqual(label_item(panel, 100, "ml")["nutrients"]["kcal"], 209.2)
            app.checkbox[0].check().run()
            self.assertFalse(app.button[0].disabled)
            app.number_input(key="label-" + draft["id"] + "-energy").set_value(210.0).run()
            self.assertTrue(app.button[0].disabled)

    def test_label_output_uses_official_transport_and_null_for_unreadable(self):
        calls = []
        def transport(request):
            calls.append(json.loads(request.content))
            return httpx.Response(200, json={
                "id": "resp_fixture", "object": "response", "created_at": 1, "model": "gpt-5-mini",
                "status": "completed", "tools": [], "parallel_tool_calls": False, "tool_choice": "auto",
                "output": [{"id":"msg_1", "type": "message", "role":"assistant", "status":"completed",
                            "content":[{"type":"output_text", "text":json.dumps(self.panel), "annotations":[]}]}],
                "usage":{"input_tokens":110,"output_tokens":70,"total_tokens":180,
                         "input_tokens_details":{"cached_tokens":0},"output_tokens_details":{"reasoning_tokens":0}}})
        with httpx.Client(transport=httpx.MockTransport(transport)) as client, patch(
            "langchain_openai.ChatOpenAI", side_effect=lambda **kw: ChatOpenAI(http_client=client, **kw)
        ):
            result = read_label(b"test-image", api_key="dummy", ui_lang="en")["input"]
        self.assertFalse(calls[0]["store"])
        self.assertEqual(result["method"], "label")
        self.assertEqual(result["label"]["basis"], "100ml")
        self.assertEqual(result["token_usage"]["total_tokens"], 180)

    def test_reopen_correct_and_confirm_once_in_public_diary(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "private-test.sqlite3"
            draft = make_draft("label", "label", {}, [])
            draft["input"]["label"] = {**self.panel, "protein_g": None}
            draft["status"] = "ready"
            create_pending(draft, db_path=path)
            run = lambda: AppTest.from_string("from app import main\nmain(public_demo=True)", default_timeout=20)
            prefix = "label-"+draft["id"]
            with patch("app.cloud_diary", return_value=path):
                first = run()
                first.query_params["lang"] = "en"
                first.run()
                self.assertFalse(first.exception)
                self.assertTrue(first.button(key=prefix+"-confirm").disabled)
                first.number_input(key=prefix+"-protein_g").set_value(3.2).run()
                first.number_input(key=prefix+"-amount-ml").set_value(125.0).run()
                self.assertEqual(get_pending(draft["id"], db_path=path)["input"]["eaten_amount"], 125.0)
                app = run().run()
                self.assertFalse(app.exception)
                self.assertFalse(app.button(key=prefix+"-confirm").disabled)
                app.button(key=prefix+"-confirm").click().run()
                self.assertFalse(app.exception)
                record, = list_meals(datetime.now(SG_TIME).date(), db_path=path)
                self.assertAlmostEqual(record["totals"]["kcal"], 62.5)
                self.assertIsNone(get_pending(draft["id"], db_path=path))
                next(b for b in app.get("button_group") if b.key=="section").set_value("日记").run()
                self.assertFalse(app.exception)
                self.assertTrue(any("125 ml" in t.value.lower() for t in app.markdown))
