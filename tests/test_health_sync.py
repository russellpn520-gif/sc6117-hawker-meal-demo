from datetime import date, timedelta
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from coach import _today_values
from meal_targets import meal_target
from meals import (clear_diary, clear_health, diary_move_targets, get_health, get_profile, move_workout,
                   planned_days, save_profile, sync_health)
from planning import Profile, TrainingCalendar, TrainingPreferences, day_plan, energy_factor
from sample_meal import start_practice


DAY = date(2026, 11, 28)


def person(**changes):
    values = dict(age=30, height_cm=170, weight_kg=70, sex="male", activity="regular", start=DAY)
    return Profile(**(values | changes))


@pytest.mark.parametrize("goal,factors,protein", [
    ("lose", (.90, .90, .80), 140), ("gain", (1.14, 1.14, 1.05), 119),
    ("recomp", (1.03, .95, .88), 147),
])
def test_strength_cardio_rest_and_active_energy(goal, factors, protein):
    p = person(goal=goal)
    for theme, factor in zip(("legs", "swim", "rest"), factors):
        days = TrainingCalendar({DAY} if theme != "rest" else set(), {DAY: theme})
        assert energy_factor(p, theme) == factor
        for active in (None, 0, 460, 1030):
            plan = day_plan(p, DAY, days, active_kcal=active)
            bmr = p.resting_kcal[0]
            output = bmr * 1.5 if active is None else bmr + active
            expected = round(output * factor)
            if goal != "gain":
                expected = max(expected, 1500, int(bmr + .999))
            assert plan.kcal == (expected, expected)
            assert plan.output_kcal == (None if active is None else (round(output),) * 2)
            assert plan.protein_g == protein
            share = (.30 if theme == "rest" else .24) if goal == "recomp" else .25
            assert plan.fat_g == max(49, round(expected * share / 9))
            assert plan.carb_g == max(0, round((expected - 4 * protein - 9 * plan.fat_g) / 4))


def test_profile_migration_adjusted_weight_and_guards():
    p = person(goal="maintain", weight_kg=110)
    assert Profile.model_validate_json(p.model_dump_json().replace("recomp", "maintain")).goal == "recomp"
    threshold = 25 * 1.7**2
    assert p.reference_kg == pytest.approx(threshold + .4 * (110 - threshold))
    assert day_plan(p, DAY, set()).protein_g == round(p.reference_kg * 2.1)
    assert person().reference_kg == 70
    for goal in ("lose", "recomp", "gain"):
        assert energy_factor(person(goal=goal, activity="athlete"), "legs") == 1
        if goal != "gain":
            assert energy_factor(person(goal=goal, weight_kg=48), "rest") == 1
    tiny = person(age=70, weight_kg=50, height_cm=150, sex=None)
    assert day_plan(tiny, DAY, set(), active_kcal=0).kcal == (1200, 1500)
    sedentary = person(activity="inactive")
    assert day_plan(sedentary, DAY, set()).protein_g == 112
    prefs = TrainingPreferences(weekdays=(0, 3), mode="strength", since=DAY)
    assert day_plan(sedentary.model_copy(update={"training":prefs}), DAY, set()).protein_g == 147


def test_diary_scope_next_meal_and_stale_move(tmp_path):
    db = tmp_path / "real.db"
    p = person()
    save_profile(p, db_path=db)
    tomorrow = DAY + timedelta(days=1)
    active = planned_days(p, DAY, tomorrow, db_path=db)
    def guide():
        rows, eaten, partial, plan = _today_values(p, DAY, db)
        return meal_target(plan, eaten, rows, partial, choice="two").amounts
    base = guide()
    sync_health(DAY, 460, 8600, "sample_watch", db_path=db)
    preview = diary_move_targets(p, DAY, tomorrow, active, db)
    assert preview[0][0].output_kcal and preview[0][1].output_kcal and preview[1][0].output_kcal is None
    lower = guide()
    sync_health(DAY, 1120, 9200, "apple_shortcut", db_path=db)
    higher = guide()
    assert higher["kcal"] > lower["kcal"] and higher["protein_g"] == lower["protein_g"]
    assert not move_workout(p, DAY, tomorrow, db_path=db, expected_targets=preview)
    sample, _ = start_practice(db, DAY)
    assert get_health(DAY, db_path=sample) is None and get_profile(db_path=sample).goal == "recomp"
    sync_health(DAY, 0, None, "sample_watch", db_path=sample)
    assert get_health(DAY, db_path=db).active_kcal == 1120
    clear_diary(db_path=sample)
    assert get_health(DAY, db_path=sample) is None
    sync_health(tomorrow, 10, None, "apple_shortcut", db_path=db)
    clear_health(DAY, db_path=db)
    assert guide() == base and get_health(tomorrow, db_path=db).active_kcal == 10
    clear_diary(db_path=db)
    assert get_health(tomorrow, db_path=db) is None


@pytest.mark.parametrize("active,steps,valid", [
    ("500", "9200", True), ("0", None, True), ("5000", "150000", True), ("460.5", "0", True),
    ("5001", "0", False), ("nan", "12", False), ("100", "-1", False), ("0", "1.5", False),
    ("1", "150001", False), ("", None, False), (None, "1", False), (["1", "2"], None, False),
])
def test_shortcut_url_is_consumed_once(tmp_path, active, steps, valid):
    db = tmp_path / "phone.db"
    script = f"from datetime import date\nfrom health_ui import import_health_link\nimport_health_link(date.fromisoformat('{DAY}'), {str(db)!r})"
    app = AppTest.from_string(script)
    app.query_params["lang"] = "en"
    app.query_params["practice"] = "1"
    if active is not None:
        app.query_params["health_active"] = active
    if steps is not None:
        app.query_params["health_steps"] = steps
    with patch("health_ui.sync_health", wraps=sync_health) as write:
        app.run()
        assert not app.exception
        assert set(app.query_params) == {"lang", "practice"}
        reading = get_health(DAY, db_path=db)
        if valid:
            assert (reading.active_kcal, reading.steps, reading.source) == (float(active), int(steps) if steps else None, "apple_shortcut")
        else:
            assert reading is None
        count = write.call_count
        app.run()
        assert write.call_count == count and get_health(DAY, db_path=db) == reading
