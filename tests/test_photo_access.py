import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class TeamPhotoAccessTests(unittest.TestCase):
    KEY = "test-provider-value-with-no-real-access"
    CODE = "fictional-team-code-01"
    A = "a" * 32
    B = "b" * 32

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.config = {"OPENAI_API_KEY": self.KEY, "TEAM_PHOTO_CODE": self.CODE}
        self.enterContext(patch("photo_access._cloud_secret", side_effect=lambda name: self.config.get(name, "")))
        self.enterContext(patch("photo_access._diary_path", side_effect=lambda token: self.folder / f"{token}.db"))
        self.enterContext(patch("photo_access.read_api_key", side_effect=AssertionError("public call read a local key")))
        self.enterContext(patch("photo_access.local_setting", side_effect=AssertionError("public call read local config")))

    def open(self, device):
        app = AppTest.from_string(f"""
import streamlit as st
from photo_access import photo_api_key
key = photo_api_key(public_demo=True)
st.session_state.result = "granted" if key == {self.KEY!r} else ("denied" if not key else "unexpected key")
""")
        app.session_state["diary_token"] = device
        app.session_state["ui_lang"] = "en"
        return app.run()

    def check(self, app, expected):
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["result"], expected)
        # Include rendered widget protos and hints, not the AppTest script source.
        visible = "\n".join(str(element.proto) for element in app if hasattr(element, "proto"))
        self.assertNotIn(self.KEY, visible)

    def test_locked_with_absent_or_wrong_codes_even_with_provider_configured(self):
        for code in ("", "short", self.KEY):
            with self.subTest(server_code=code):
                self.config["TEAM_PHOTO_CODE"] = code
                app = self.open(self.A)
                self.check(app, "denied")
                self.assertFalse(app.text_input)
        self.config["TEAM_PHOTO_CODE"] = self.CODE
        app = self.open(self.A)
        self.check(app, "denied")
        for entered in ("", "wrong-team-code"):
            app.text_input(key="photo_code_input").set_value(entered)
            app.button[0].click().run()
            self.check(app, "denied")
            self.assertIn("did not match", app.error[0].value)
        self.check(self.open(self.A), "denied")

    def test_grant_is_tied_to_device_and_current_team_code(self):
        app = self.open(self.A)
        app.text_input(key="photo_code_input").set_value(self.CODE)
        app.button[0].click().run()
        self.check(app, "granted")
        self.check(self.open(self.A), "granted")
        self.check(self.open(self.B), "denied")
        with closing(sqlite3.connect(self.folder / f"{self.A}.db")) as db:
            proof = db.execute("SELECT proof FROM photo_access").fetchone()[0]
        self.assertNotIn(self.KEY, proof)
        self.assertNotIn(self.CODE, proof)
        self.config["TEAM_PHOTO_CODE"] = "different-fictional-code-02"
        self.check(app.run(), "denied")
        self.check(self.open(self.A), "denied")
        app.text_input(key="photo_code_input").set_value(self.CODE)
        app.button[0].click().run()
        self.check(app, "denied")
        self.config["OPENAI_API_KEY"] = ""
        self.check(self.open(self.A), "denied")
