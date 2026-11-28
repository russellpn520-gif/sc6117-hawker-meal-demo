from datetime import datetime, time, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx
from langchain_openai import ChatOpenAI

from coach import NextStep, PlanDinner, PreviewMove, ReadDiary, _route, ask_coach, confirm_move
from meals import SG_TIME, create_pending, load_foods, make_draft, planned_days, portion_items, save_meal, save_profile
from nutrition_coach import Preferences, save_dinner_mode, save_preferences
from planning import Profile


class CoachTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db = Path(folder.name) / "private.sqlite3"
        self.today = datetime.now(SG_TIME).date()
        self.tomorrow = self.today + timedelta(days=1)
        self.profile = Profile(age=25, height_cm=168, weight_kg=65, activity="regular",
                               start=self.today - timedelta(days=7))
        save_profile(self.profile, db_path=self.db)
        save_preferences(self.db, Preferences(700, "any", ()))
        save_dinner_mode(self.db, "home")

    def ask(self, text="", *, lang="en", **kwargs):
        return ask_coach(text, today=self.today, db_path=self.db, lang=lang, **kwargs)

    def log(self, day, key, grams, partial=False):
        draft = make_draft("text", "food", {key: grams}, [])
        draft["captured_at"] = datetime.combine(day, time(), tzinfo=SG_TIME).isoformat()
        if partial:
            draft["input"].update(unmatched_foods=["sauce"], partial_record=True)
        create_pending(draft, db_path=self.db)
        self.assertTrue(save_meal(draft, portion_items(load_foods(), {key: grams}), db_path=self.db))

    def test_week_and_daily_distinguish_empty_partial_and_outside_window(self):
        self.log(self.today - timedelta(days=7), "white-rice", 180)
        self.log(self.today - timedelta(days=6), "boiled-egg", 50)
        self.log(self.today, "tfda-P0200601", 6, partial=True)
        for lang in ("zh", "en"):
            with self.subTest(lang=lang):
                week = self.ask(lang=lang, quick="week")["text"]
                self.assertEqual(sum(line.startswith("- ") for line in week.splitlines()), 7)
                self.assertIn("74 kcal", week)
                self.assertIn("31 kcal", week)
                self.assertNotIn("248 kcal", week)
                self.assertEqual(week.count("No confirmed meals" if lang == "en" else "无已确认餐食"), 5)
                self.assertIn("partial" if lang == "en" else "部分记录", week)
                today = self.ask(lang=lang, quick="today")["text"]
                self.assertIn("subtotal" if lang == "en" else "小计", today)
                self.assertNotIn("kcal remain" if lang == "en" else "剩余参考量", today)

    def test_move_and_dinner_previews_do_not_mutate_and_confirmation_is_idempotent(self):
        calls = [PreviewMove(origin=self.today.isoformat(), destination=self.tomorrow.isoformat()),
                 PlanDinner(groceries=False, budget_sgd=1.5, new_food_restrictions=False)]
        active = lambda: planned_days(self.profile, self.today, self.tomorrow, db_path=self.db)
        self.log(self.today, "boiled-egg", 50)
        with patch("coach._route", return_value=(calls, {"total_tokens": 87})):
            reply = self.ask("Move today's workout to tomorrow and suggest dinner under S$1.50.", api_key="dummy")
        self.assertEqual(reply["move"], (self.today, self.tomorrow))
        self.assertEqual(reply["usage"]["total_tokens"], 87)
        self.assertEqual(active(), {self.today})
        self.assertIn("S$1.48", reply["text"])
        self.assertIn("Training day", reply["text"])
        self.assertNotIn("Workout moved to", reply["text"])
        ok, text = confirm_move(*reply["move"], today=self.today, db_path=self.db, lang="zh")
        self.assertTrue(ok)
        self.assertIn("已", text)
        self.assertEqual(active(), {self.tomorrow})
        self.assertFalse(confirm_move(*reply["move"], today=self.today, db_path=self.db)[0])
        self.assertIn("休息日", self.ask(lang="zh", quick="dinner")["text"])
        context = reply["meal_context"]
        self.assertIsNotNone(context)
        self.assertEqual(context["budget_sgd"], 1.50)
        shopping = self.ask(lang="zh", quick="shopping", meal_context=context)
        self.assertIn("购物清单", shopping["text"])
        self.assertIn("S$1.50", shopping["text"])
        self.assertIn("休息日", shopping["text"])
        self.assertNotIn("鸡肉", shopping["text"])
        # A preference change invalidates a previous feasible basket.
        save_preferences(self.db, Preferences(700, "vegan", ("soy",), ("black_bean",)))
        blocked = self.ask(lang="en", quick="shopping", meal_context=context)
        self.assertIsNone(blocked["meal_context"])
        self.assertNotIn("**Shopping list**", blocked["text"])

    def test_profile_change_invalidates_displayed_move_targets(self):
        reply = self.ask(quick="move")
        save_profile(self.profile.model_copy(update={"weight_kg": 85}), db_path=self.db)
        ok, _ = confirm_move(*reply["move"], today=self.today, db_path=self.db, expected_targets=reply["move_targets"])
        self.assertFalse(ok)
        self.assertEqual(planned_days(self.profile, self.today, self.tomorrow, db_path=self.db), {self.today})

    def test_health_and_router_failure_do_not_act_or_echo_provider_error(self):
        before = planned_days(self.profile, self.today, self.tomorrow, db_path=self.db)
        for q, lang in (("Can I train with knee pain?", "en"), ("怀孕了能照这个练吗？", "zh")):
            with patch("coach._route") as route:
                reply = self.ask(q, api_key="dummy", lang=lang)
                route.assert_not_called()
            self.assertIsNone(reply["move"])
            self.assertIn("clinician" if lang == "en" else "医生", reply["text"])
            self.assertNotIn("S$", reply["text"])
        with patch("coach._route", side_effect=ValueError("private provider detail")):
            reply = self.ask("Plan dinner", api_key="dummy")
        self.assertNotIn("private provider detail", reply["text"])
        self.assertIsNone(reply["move"])
        self.assertEqual(planned_days(self.profile, self.today, self.tomorrow, db_path=self.db), before)

    def test_ambiguous_moves_ask_for_dates_and_medical_outcome_suppresses_all_actions(self):
        proposed = PreviewMove(origin=self.today.isoformat(), destination=self.tomorrow.isoformat())
        other = proposed.model_copy(update={"destination": (self.tomorrow + timedelta(days=2)).isoformat()})
        with patch("coach._route", return_value=([proposed, other], {})):
            reply = self.ask("把训练挪到有空的那天", api_key="dummy", lang="zh")
        self.assertIsNone(reply["move"])
        self.assertIn("哪", reply["text"])
        with patch("coach._route", return_value=([proposed, NextStep(reason="medical")], {})):
            reply = self.ask("Should I change my exercise after my clinical appointment?", api_key="dummy")
        self.assertIsNone(reply["move"])
        self.assertIn("clinician", reply["text"])
        self.assertEqual(planned_days(self.profile, self.today, self.tomorrow, db_path=self.db), {self.today})

    def test_batch_food_restriction_is_respected_by_every_menu_call(self):
        menu = PlanDinner(groceries=True, budget_sgd=5, new_food_restrictions=False)
        guard = NextStep(reason="food_preferences")
        for lang, request, calls in (("en", "Dinner without nuts please", [menu, guard]),
                                     ("zh", "晚餐别放花生", [guard, menu])):
            with self.subTest(lang=lang), patch("coach._route", return_value=(calls, {})):
                reply = self.ask(request, lang=lang, api_key="dummy")
                self.assertTrue(reply["show_nutrition"])
                self.assertNotIn("S$", reply["text"])
                self.assertIsNone(reply["meal_context"])

    def test_dinner_and_groceries_requested_together(self):
        calls = [PlanDinner(groceries=g, budget_sgd=2, new_food_restrictions=False) for g in (False, True)]
        with patch("coach._route", return_value=(calls, {})):
            result = self.ask("请给今晚的晚餐和购物单，预算两元", api_key="dummy", lang="zh")
        self.assertIn("购物清单", result["text"])
        self.assertIn("S$2.00", result["text"])
        self.assertIsNotNone(result["meal_context"])

        # A second tool call may omit the shared budget, even when the first
        # has no viable recipe to hand to the grocery tool.
        for order in ((False, True), (True, False)):
            calls = [PlanDinner(groceries=shopping, budget_sgd=1.0 if not shopping else None,
                                new_food_restrictions=False) for shopping in order]
            with self.subTest(order=order), patch("coach._route", return_value=(calls, {})):
                blocked = self.ask("Dinner and groceries, total budget S$1.", api_key="dummy")
                self.assertIsNone(blocked["meal_context"])
                self.assertNotIn("**Shopping list**", blocked["text"])

    def test_official_responses_tool_schema_and_real_transport_parsing(self):
        requests = []

        def transport(request):
            requests.append(request)
            return httpx.Response(200, json={
                "id": "resp_synthetic", "object": "response", "created_at": 1, "model": "gpt-5-mini",
                "status": "completed", "tools": [], "parallel_tool_calls": False, "tool_choice": "required",
                "output": [{"id": "fc_test", "type": "function_call", "call_id": "call_test",
                            "name": "ReadDiary", "arguments": '{"period":"week"}', "status": "completed"}],
                "usage": {"input_tokens": 12, "output_tokens": 5, "total_tokens": 17,
                          "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}},
            })

        with httpx.Client(transport=httpx.MockTransport(transport)) as client, patch(
            "langchain_openai.ChatOpenAI", side_effect=lambda **kwargs: ChatOpenAI(http_client=client, **kwargs)
        ) as ctor:
            calls, usage = _route("What did I log this week?", self.today, "dummy", [
                {"role": "user", "content": "Can you show my diary?"},
                {"role": "assistant", "content": "Private diary entries that should not go to the router"},
            ])
        self.assertEqual([type(c) for c in calls], [ReadDiary])
        self.assertEqual(calls[0].period, "week")
        self.assertEqual(usage["total_tokens"], 17)
        self.assertEqual(len(requests), 1)
        self.assertEqual(str(requests[0].url), "https://api.openai.com/v1/responses")
        payload = json.loads(requests[0].content)
        self.assertFalse(payload["store"])
        self.assertEqual(payload["tool_choice"], "required")
        self.assertEqual(ctor.call_args.kwargs["max_retries"], 0)
        self.assertTrue(all(t["strict"] for t in payload["tools"]))
        dinner_schema = next(t["parameters"] for t in payload["tools"] if t["name"] == "PlanDinner")
        self.assertEqual(set(dinner_schema["required"]), set(dinner_schema["properties"]))
        self.assertNotIn("default", dinner_schema["properties"]["mode"])
        self.assertIn({"type": "null"}, dinner_schema["properties"]["mode"]["anyOf"])
        self.assertEqual({t["name"] for t in payload["tools"]}, {"ReadDiary", "ReadWorkout", "PlanDinner", "PreviewMove", "NextStep"})
        self.assertNotIn("Private diary entries", json.dumps(payload["input"]))
