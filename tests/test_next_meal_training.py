"""Offline, diary-level regressions for linked training, meal targets and drafts."""
import json
from datetime import date, timedelta
from uuid import uuid4

import pytest

from meal_targets import daily_hint, fit_score, meal_target, vegetable_grams
from meals import get_pending, get_profile, load_foods, move_workout, open_db, planned_days, portion_items, save_profile, total_nutrients
from nearby_hawker import LANDMARKS, add_nearby_draft, recommend_nearby
from nutrition_coach import (Preferences, add_home_draft, checked_side_grams, choose_booster, dinner_result, plan_dinner,
                             save_preferences, side_options)
from planning import DayPlan, Profile, TrainingPreferences, day_plan, move_targets
from training_coach import read_logs, save_training_log, save_training_preferences, training_context


MON = date(2026, 11, 23)
DAILY = DayPlan(True, (1950, 2050), 110, 240, 65, "legs")
EATEN = {"kcal": 600, "protein_g": 30, "carb_g": 55, "fat_g": 20}
ROW = {"items": [{"food_id": "white-rice", "confirmed_g": 90}]}


def profile(gear="gym", mode="mixed", cardio="run", weekdays=(0, 2, 4, 5)):
    prefs = TrainingPreferences(equipment=gear, mode=mode, weekdays=weekdays, minutes=45, cardio=cardio, since=MON)
    return Profile(age=24, height_cm=172, weight_kg=70, activity="regular", start=MON, training=prefs)


def test_split_every_remaining_nutrient_and_infer_snack():
    two = meal_target(DAILY, EATEN, [ROW])
    one = meal_target(DAILY, EATEN, [ROW, ROW])
    assert (two.mode, one.mode, two.veg_gap) == ("two", "one", True)
    assert two.amounts == {"kcal": 700, "protein_g": 40, "carb_g": 92.5, "fat_g": 22.5}
    assert all(one.amounts[k] == 2*v for k, v in two.amounts.items())
    assert meal_target(DAILY, dict(EATEN, kcal=1651), []).mode == "snack"
    assert meal_target(DAILY, dict(EATEN, kcal=1650), []).mode == "two"
    assert meal_target(DAILY, EATEN, [], choice="snack").amounts["kcal"] == 300
    assert not meal_target(DAILY, EATEN, [ROW], partial=True).amounts
    assert not meal_target(None, EATEN, []).amounts
    assert fit_score(two, two.amounts, 80) < fit_score(two, dict(two.amounts, carb_g=20, fat_g=50), 0)


def test_gap_booster_checks_energy_allergens_avoid_and_home_budget(tmp_path):
    target = meal_target(DAILY, EATEN, [ROW], choice="one")
    prefs = Preferences(None, "vegan", ("soy", "milk"), ("sweet_potato",))
    main = dict(EATEN, protein_g=17)
    side = choose_booster(target, main, prefs)
    assert side["key"] == "chickpea"
    assert choose_booster(target, main, prefs, limit=1) is None
    assert choose_booster(meal_target(DAILY, EATEN, [ROW]), main, prefs) is None
    assert not choose_booster(target, target.amounts, prefs)
    assert choose_booster(target, dict(target.amounts, kcal=500), prefs)
    assert not side_options(Preferences(None, "any", ("other",)))
    assert not side_options(Preferences(None, "any", (), (), "garlic"))
    db = tmp_path / "meal.db"
    save_preferences(db, prefs)
    recipe = plan_dinner(prefs, target=target)
    ident = str(uuid4())
    add_home_draft(db, recipe["recipe"].names[1], side["key"], ident)
    draft = get_pending(ident, db_path=db)
    totals = total_nutrients([i["nutrients"] for i in portion_items(load_foods(), draft["input"]["suggested_grams"])])
    assert draft["status"] == "ready"
    assert totals == pytest.approx(total_nutrients([recipe["nutrients"], side["totals"]]))
    assert all(i["source_url"].startswith("https://") for i in side["items"])
    save_preferences(db, Preferences(None, "vegan", ("soy",), ("chickpea",)))
    with pytest.raises(ValueError):
        add_home_draft(db, recipe["recipe"].names[1], "chickpea", str(uuid4()))


def test_nearby_checked_and_unchecked_match_catalogue_and_recheck(tmp_path):
    db = tmp_path / "venue.db"
    target = meal_target(DAILY, EATEN, [ROW], choice="one")
    cards = recommend_nearby(LANDMARKS["ntu"]["coords"], MON, target=target)["cards"]
    assert len(cards) == 3
    card = cards[0]
    side = card["booster"]
    for extra in (None, side["key"]):
        draft = get_pending(add_nearby_draft(db, card["id"], MON, side_key=extra), db_path=db)
        items = portion_items(load_foods(), draft["input"]["suggested_grams"])
        before = [card["totals"], side["totals"]] if extra else [card["totals"]]
        assert total_nutrients([i["nutrients"] for i in items]) == pytest.approx(total_nutrients(before))
    save_preferences(db, Preferences(None, "any", ("other",)))
    with pytest.raises(ValueError):
        add_nearby_draft(db, card["id"], MON, side_key=side["key"])


@pytest.mark.parametrize("gear", ["bodyweight", "dumbbells", "gym"])
@pytest.mark.parametrize(("days", "themes"), [
    ((0,), ["full"]), ((0, 3), ["upper", "lower"]), ((0, 2, 4), ["push", "pull", "legs"]),
    ((0, 2, 4, 6), ["chest", "back", "legs", "core"])])
def test_strength_split_and_equipment(gear, days, themes, tmp_path):
    p = profile(gear=gear, mode="strength", weekdays=days)
    sessions = training_context(p, MON, db_path=tmp_path/"training.db")["sessions"]
    work = [s for s in sessions if s["mode"] != "rest"]
    assert [s["theme"] for s in work] == themes
    for s in work:
        assert len({e["id"] for e in s["exercises"]}) >= 3
        assert s["planned_minutes"] <= p.training.minutes
        assert all((e["kg"] == 0 if gear == "bodyweight" else e["kg"] is None) for e in s["exercises"])


@pytest.mark.parametrize("activity", ["run", "swim", "cycle", "walk"])
def test_cardio_duration_effort_and_mixed_week(activity, tmp_path):
    p = profile(cardio=activity)
    db = tmp_path / "cardio.db"
    save_profile(p, db_path=db)
    aerobic = MON + timedelta(days=5)
    sessions = training_context(p, MON, db_path=db)["sessions"]
    assert [s["theme"] for s in sessions if s["mode"] != "rest"] == ["push", "pull", "legs", activity]
    assert sessions[5]["intensity"] == "easy" and sessions[5]["planned_minutes"] == 45
    for w, intensity in ((1, "tempo"), (2, "interval"), (3, "easy")):
        s = training_context(p, aerobic+timedelta(weeks=w), db_path=db)["sessions"][0]
        assert s["intensity"] == intensity
        assert (s["minutes"] < 45) == (w == 3)
    with pytest.raises(ValueError):
        save_training_log(p, aerobic, aerobic, "comfortable", {"minutes": 28, "rpe": 12}, db_path=db)
    save_training_log(p, aerobic, aerobic, "comfortable", {"minutes": 28, "rpe": 4}, db_path=db)
    row, = read_logs(MON, aerobic, db_path=db)
    assert row["actuals"] == {"minutes": 28, "rpe": 4} and row["targets"]["theme"] == activity


def test_move_persists_theme_and_four_targets_across_week_boundary(tmp_path):
    p = profile()
    db = tmp_path / "schedule.db"
    save_profile(p, db_path=db)
    start, end = MON, MON + timedelta(days=13)
    active = planned_days(p, start, end, db_path=db)
    week = [day_plan(p, start+timedelta(days=i), active) for i in range(7)]
    push, rest, back, _, legs, cardio, _ = week
    assert legs.kcal == back.kcal == push.kcal and push.kcal > cardio.kcal > rest.kcal
    assert back.protein_g == legs.protein_g == cardio.protein_g == rest.protein_g
    assert back.carb_g == push.carb_g and push.carb_g > cardio.carb_g > rest.carb_g
    assert cardio.fat_g < push.fat_g
    for plan in week:
        assert abs(4*(plan.carb_g+plan.protein_g)+9*plan.fat_g-sum(plan.kcal)/2) <= 2
    origin, destination = MON+timedelta(days=2), MON+timedelta(days=8)
    preview = move_targets(p, origin, destination, active)
    assert move_workout(p, origin, destination, db_path=db, expected_targets=preview)
    active = planned_days(p, start, end, db_path=db)
    for d, (before, after) in zip((origin, destination), preview):
        actual = day_plan(p, d, active)
        assert actual == after and before.theme != after.theme
        assert meal_target(actual, EATEN, [ROW]).amounts != meal_target(before, EATEN, [ROW]).amounts
        assert all(getattr(actual, k) != getattr(before,k) for k in ("kcal","carb_g","fat_g"))
    assert training_context(p, destination, db_path=db)["sessions"][0]["theme"] == "pull"


def test_legacy_sql_profile_and_optional_new_settings(tmp_path):
    db = tmp_path/"old.db"
    original = dict(age=27, weight_kg=65, height_cm=170, activity="regular", start=MON.isoformat(),
                    training=dict(equipment="dumbbells", weekdays=[0,2,4], minutes=10, since=MON.isoformat()))
    with open_db(db) as conn:
        conn.execute("INSERT INTO profile VALUES (1,?)", (json.dumps(original),))
    p = get_profile(db_path=db)
    assert p.training.mode is None and p.training.minutes == 10
    tomorrow = MON+timedelta(days=1)
    prefs = p.training.model_copy(update=dict(mode="cardio", cardio="swim", time_slot="evening", since=tomorrow))
    changed = save_training_preferences(p, prefs, db_path=db)
    assert changed.training_for(MON) == p.training and changed.training_for(tomorrow) == prefs
    assert DayPlan(True,(1000,1000),60).fat_g == 0


def test_snack_sourced_and_saved_with_exclusions(tmp_path):
    db = tmp_path/"snack.db"
    prefs = Preferences(None, "vegetarian", ("milk", "egg"))
    save_preferences(db, prefs)
    food_id, weight = checked_side_grams("soy_milk", prefs)
    ident = add_home_draft(db, None, "soy_milk", str(uuid4()))
    assert get_pending(ident, db_path=db)["input"]["suggested_grams"] == {food_id: weight}
    with pytest.raises(ValueError):
        add_home_draft(db, None, "yogurt", str(uuid4()))
    assert vegetable_grams([{"source_name": "Carrots, raw", "confirmed_g": 90}]) == 90
    assert "carb" in daily_hint(DAILY, EATEN, False, 10)[1].lower()


def test_moved_split_survives_chained_moves_and_duration_edit(tmp_path):
    db = tmp_path / "moves.db"
    p = profile()
    save_profile(p, db_path=db)
    origin, first, final = (MON + timedelta(days=i) for i in (2, 3, 6))
    assert move_workout(p, origin, first, db_path=db)
    assert move_workout(p, first, final, db_path=db)
    p = save_training_preferences(p, p.training.model_copy(update={"minutes": 60}), db_path=db)
    session = training_context(p, final, db_path=db)["sessions"][0]
    assert session["theme"] == "pull" and session["minutes"] == 60
    assert move_workout(p, final, origin, db_path=db)
    days = planned_days(p, MON, final, db_path=db)
    assert origin in days and first not in days and final not in days
    assert day_plan(p, origin, days).theme == "pull"


def test_moved_workout_releases_original_when_new_calendar_conflicts(tmp_path):
    db = tmp_path / "changed.db"
    p = profile()
    save_profile(p, db_path=db)
    origin, dest = MON+timedelta(days=2), MON+timedelta(days=3)
    assert move_workout(p, origin, dest, db_path=db)
    p = save_training_preferences(p, p.training.model_copy(update={"weekdays":(0,2,3,5)}), db_path=db)
    days = planned_days(p, MON, MON+timedelta(days=6), db_path=db)
    assert origin in days and dest in days
    assert day_plan(p, origin, days).theme == "pull" and day_plan(p, dest, days).theme == "legs"


def test_four_day_week_uses_goal_factors_and_budget_uses_price_evidence():
    p = profile()
    active = {MON+timedelta(days=d) for d in p.training.weekdays}
    plans = [day_plan(p, MON+timedelta(days=d), active) for d in range(7)]
    assert sum(v.kcal[0] for v in plans) == sum(round(p.resting_kcal[0] * 1.5 * factor) for factor in (1.03, .88, 1.03, .88, 1.03, .95, .88))
    target = meal_target(DAILY, EATEN, [ROW], choice="one")
    where = LANDMARKS["nus"]["coords"]
    def ids(cap):
        return [c["id"] for pg in range(4) for c in recommend_nearby(
            where, MON, target=target, training=True, remaining_kcal=1300, budget_limit=cap, page=pg)["cards"]]
    assert ids(500).index("nus-utown-wagyu") >= ids(3000).index("nus-utown-wagyu")


def test_shopping_list_keeps_checked_side_and_rechecks_allergies(tmp_path):
    db = tmp_path / "shopping.db"
    recipe = "Ginger chicken and broccoli rice"
    text, _ = dinner_result(db, lang="en", shopping=True, recipe_name=recipe, side_key="yogurt")
    assert "Plain nonfat Greek yogurt" in text and "170 g" in text
    save_preferences(db, Preferences(None, "any", ("milk",)))
    text, result = dinner_result(db, lang="en", shopping=True, recipe_name=recipe, side_key="yogurt")
    assert result is None and "no longer fits" in text
