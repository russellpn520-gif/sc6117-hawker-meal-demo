import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from langchain_openai import ChatOpenAI

from meals import create_pending, get_pending, load_foods, make_draft
from photo_tasks import start_recognition
from recognition import identify_photo


class PhotoProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.foods = load_foods()

    def test_official_responses_request_and_bilingual_result(self):
        requests = []
        photo_result = {
            "dishes": [{"whole": {"english": "house sauce", "chinese": "特制调味汁", "low_g": 5, "high_g": 15},
                        "parts": []}],
            "uncertain_items": ["配方不详"], "uncertain_items_en": ["Recipe unknown"],
            "portion_note": "按碟子估量。", "portion_note_en": "Estimated from the plate.",
        }

        def transport(request):
            requests.append(request)
            return httpx.Response(200, json={
                "id": "resp_test", "object": "response", "created_at": 1, "model": "gpt-5-mini",
                "status": "completed", "tools": [], "parallel_tool_calls": False, "tool_choice": "auto",
                "output": [{"id": "msg_test", "type": "message", "role": "assistant", "status": "completed",
                            "content": [{"type": "output_text", "text": json.dumps(photo_result), "annotations": []}]}],
                "usage": {"input_tokens": 11, "output_tokens": 13, "total_tokens": 24,
                          "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}},
            })

        with httpx.Client(transport=httpx.MockTransport(transport)) as client, patch.dict(os.environ, {
            "OPENAI_BASE_URL": "https://invalid.example", "TRACK3_MODEL": "untrusted-model",
        }), patch("langchain_openai.ChatOpenAI", side_effect=lambda **kwargs: ChatOpenAI(http_client=client, **kwargs)) as ctor:
            draft = identify_photo(b"photo", "private-name.jpeg", self.foods, api_key="demo-placeholder", ui_lang="en")
        self.assertEqual(len(requests), 1)
        self.assertEqual(ctor.call_args.kwargs["max_retries"], 0)
        self.assertEqual(str(requests[0].url), "https://api.openai.com/v1/responses")
        body = json.loads(requests[0].content)
        self.assertFalse(body["store"])
        self.assertEqual((body["model"], body["reasoning"]["effort"], body["max_output_tokens"]), ("gpt-5-mini", "minimal", 2000))
        self.assertTrue(body["text"]["format"]["strict"])
        human_input = body["input"][-1]["content"]
        self.assertEqual(human_input[0]["text"], "Identify the meal and estimate each portion.")
        self.assertEqual(human_input[1]["image_url"], "data:image/jpeg;base64,cGhvdG8=")
        self.assertNotIn(b"private-name", requests[0].content)
        view = draft["input"]
        self.assertEqual(view["unmatched_en"], ["Recipe unknown", "house sauce"])
        self.assertEqual(view["uncertain_items"], ["配方不详"])
        self.assertEqual(view["portion_note_en"], "Estimated from the plate.")
        self.assertEqual((view["ui_lang"], view["model"], view["token_usage"]["total_tokens"]), ("en", "gpt-5-mini", 24))

    def test_no_key_skips_provider_and_errors_are_safe_to_display(self):
        class ProviderError(Exception):
            pass

        with tempfile.TemporaryDirectory() as directory, patch("photo_tasks._workers.submit", side_effect=lambda fn, *args: fn(*args)):
            db = Path(directory) / "demo.sqlite"
            for key, status, code, expected in (
                ("  ", None, None, "unconfigured"), ("mock", 401, None, "key"),
                ("mock", 429, "insufficient_quota", "quota"), ("mock", 429, None, "rate_limit"),
                ("mock", 503, None, "unavailable"),
            ):
                with self.subTest(expected=expected):
                    draft = make_draft("photo", "Lunch", {}, [])
                    draft["input"]["ui_lang"] = "en"
                    draft["profile"] = {"weight": 75}
                    create_pending(draft, b"photo", db_path=db)
                    exception = ProviderError("private-provider-detail")
                    exception.status_code, exception.code = status, code
                    with patch("recognition.identify_photo", side_effect=exception) as scan:
                        start_recognition(draft["id"], db, key)
                    if key.strip():
                        scan.assert_called_once_with(b"photo", "Meal photo", self.foods, api_key=key, ui_lang="en")
                    else:
                        scan.assert_not_called()
                    saved = get_pending(draft["id"], db_path=db)
                    self.assertEqual((saved["status"], saved["error_code"], saved["photo"]), ("failed", expected, b"photo"))
                    self.assertNotIn("private-provider-detail", saved["error"] + saved["error_en"])
                    self.assertTrue(saved["error_en"].startswith("Your photo is saved"))

        with patch("langchain_openai.ChatOpenAI") as ctor, self.assertRaises(ValueError):
            identify_photo(b"photo", "Lunch", self.foods, api_key=" ")
        ctor.assert_not_called()
