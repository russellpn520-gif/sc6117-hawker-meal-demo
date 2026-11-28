"""Reproduce the Track 3 plan constraint evidence without a model call or a user diary.

From the repository root run: uv run python -m evaluation.plan_constraints
"""
from datetime import date, timedelta
from itertools import product
import json
from pathlib import Path
import sys
import unittest

from nutrition_coach import plan_dinner
from planning import ACTIVITIES, Profile, TrainingPreferences
from training_coach import _session

# Use the same independent, hand-costed reference menu as the regression suite.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from test_nutrition_coach import constraint_cases
from test_training_coach import StrengthCoachTests


def longitudinal():
    start = date(2026, 11, 2)  # Monday
    checks = 0
    largest_rep_jump = largest_volume_change = 0
    scenarios = (
        ("comfortable", "comfortable", 14, "strength", True),
        ("comfortable", "challenging", 14, "strength", False),
        ("challenging", "challenging", 14, "deload", False),
        ("comfortable", "missed", 14, "return", False),
        ("comfortable", "comfortable", 21, "deload", False),
        ("comfortable", "comfortable", 28, "return", False),
    )
    for activity, gear, minutes in product(ACTIVITIES, ("bodyweight", "dumbbells"), (10, 20, 30)):
        config = TrainingPreferences(equipment=gear, weekdays=(0,), minutes=minutes, since=start)
        profile = Profile(age=30, height_cm=175, weight_kg=70, activity=activity, start=start, training=config)
        for first, second, offset, expected_mode, can_progress in scenarios:
            history = []
            last_completed = {}
            for days, status in ((0, first), (7, second)):
                day = start + timedelta(days=days)
                session = _session(profile, day, {day}, history, "en")
                targets = {e["id"]: e for e in session["exercises"]}
                actuals = {}
                if status != "missed":
                    for name, ex in targets.items():
                        kg = 2 if name == "curl" else 0
                        actuals[name] = [{"kg": kg, "reps": ex["reps"]} for _ in range(ex["sets"])]
                    last_completed = actuals
                history.append({"date": day.isoformat(), "targets": targets, "actuals": actuals, "status": status})
            day = start + timedelta(days=offset)
            next_session = _session(profile, day, {day}, history, "en")
            assert next_session["mode"] == expected_mode
            previous_volume = sum(s["reps"] for sets in last_completed.values() for s in sets)
            volume = 0
            for ex in next_session["exercises"]:
                done = last_completed[ex["id"]]
                assert ex["sets"] <= len(done)
                assert ex["kg"] <= min(s["kg"] for s in done)
                gain = ex["reps"] - min(s["reps"] for s in done)
                assert gain <= int(can_progress)
                largest_rep_jump = max(largest_rep_jump, gain)
                volume += ex["reps"] * ex["sets"]
            change = (volume - previous_volume) / previous_volume
            largest_volume_change = max(largest_volume_change, change)
            checks += 1
    return {"trajectories": checks, "max_reps_added_per_set": largest_rep_jump,
            "max_session_rep_volume_gain_percent": round(100 * largest_volume_change, 2)}


def main():
    schedule = unittest.TestResult()
    StrengthCoachTests("test_constraints_across_every_availability_pattern").run(schedule)
    if not schedule.wasSuccessful():
        raise AssertionError(schedule.errors + schedule.failures)
    served = withheld = 0
    for prefs, eligible in constraint_cases():
        plan = plan_dinner(prefs, remaining_kcal=550, remaining_protein=32)
        if eligible:
            assert plan is not None and plan["recipe"].names[1] in eligible
            assert plan["cost_cents"] <= prefs.budget_cents
            served += 1
        else:
            assert plan is None
            withheld += 1
    print(json.dumps({"synthetic_schedule_profiles": 127 * 4 * 2 * 3, **longitudinal(),
                      "eligible_dinners_served": served, "infeasible_dinners_withheld": withheld},
                     indent=2))


if __name__ == "__main__":
    main()
