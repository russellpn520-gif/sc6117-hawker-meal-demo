"""Hands-on review actions, diary rollback and schedule replacement."""
from contextlib import closing
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from meals import (SG_TIME, create_pending, delete_meal, get_pending, list_meals,
                   load_foods, make_draft, open_db, planned_days, portion_items, recent_activity,
                   save_meal, save_profile, total_nutrients)
from planning import Profile, TrainingPreferences
from sample_meal import PHOTO
from training_coach import save_training_preferences, split_exercises


def make_ready(db, grams):
    draft = make_draft("photo", "", grams, [])
    draft["status"] = "ready"
    assert create_pending(draft, db_path=db)
    return get_pending(draft["id"], db_path=db)


def test_remove_every_row_undo_and_reopen(tmp_path):
    db = tmp_path / "review.db"
    draft = make_ready(db, {"white-rice": 145, "boiled-egg": 55})
    prefix = "meal-" + draft["id"]
    src = "from app import main\nmain(public_demo=True)"
    with patch("app.cloud_diary", return_value=db):
        def launch():
            app = AppTest.from_string(src, default_timeout=20)
            app.query_params["lang"] = "en"
            return app.run()

        app = launch()
        app.number_input(key=prefix + "-grams-white-rice").set_value(127).run()
        assert app.button(key=prefix + "-confirm").label == "Confirm portions and log"
        app.segmented_control(key="ui_language_control").set_value("zh").run()
        assert app.number_input(key=prefix + "-grams-boiled-egg").value == 55
        assert app.number_input(key=prefix + "-grams-white-rice").value == 127
        app.segmented_control(key="ui_language_control").set_value("en").run()
        app.button(key=prefix + "-remove-white-rice").click().run()
        app.button(key=prefix + "-remove-boiled-egg").click().run()
        assert not app.exception and app.button(key=prefix + "-confirm").disabled
        app.button(key=prefix + "-undo-row").click().run()
        app = launch()
        assert app.multiselect[0].value == ["boiled-egg"]
        app.multiselect[0].select("white-rice").run()
        app.button(key=prefix + "-confirm").click().run()
        assert not app.exception
        record, = list_meals(datetime.now(SG_TIME).date(), db_path=db)
        assert {i["food_id"]: i["confirmed_g"] for i in record["items"]} == {"boiled-egg": 55, "white-rice": 145}


def test_widget_remount_cannot_change_saved_foods_or_weights(tmp_path):
    db = tmp_path / "remount.db"
    draft = make_ready(db, {"white-rice": 145, "boiled-egg": 55})
    prefix = "meal-" + draft["id"]
    with patch("app.cloud_diary", return_value=db):
        app = AppTest.from_string("from app import main\nmain(public_demo=True)", default_timeout=20)
        app.query_params["lang"] = "en"
        app.run()
        app.button(key=prefix + "-remove-white-rice").click().run()
        app.button(key=prefix + "-undo-row").click().run()
        # A Cloud iframe rerun can supply a stale selection or widget default.
        app.session_state[prefix + "-foods-en"] = ["white-rice"]
        app.session_state[prefix + "-grams-white-rice"] = 1
        app.run()
        assert app.multiselect[0].value == ["white-rice", "boiled-egg"]
        assert app.number_input(key=prefix + "-grams-white-rice").value == 145
        app.button(key=prefix + "-confirm").click().run()
        meal, = list_meals(datetime.now(SG_TIME).date(), db_path=db)
        assert {row["food_id"]: row["confirmed_g"] for row in meal["items"]} == {"white-rice": 145, "boiled-egg": 55}


def test_retake_opens_capture_even_with_another_draft_and_a_saved_meal(tmp_path):
    db = tmp_path / "retake.db"
    saved = make_ready(db, {"boiled-egg": 55})
    save_meal(saved, portion_items(load_foods(), saved["input"]["suggested_grams"]), db_path=db)
    other = make_ready(db, {"white-rice": 100})
    photo = make_draft("photo", "", {"white-rice": 210}, [])
    photo["status"] = "ready"
    create_pending(photo, PHOTO.read_bytes(), db_path=db)
    with patch("app.cloud_diary", return_value=db):
        app = AppTest.from_string("from app import main\nmain(public_demo=True)", default_timeout=20)
        app.query_params["lang"] = "en"
        app.run()
        app.button(key="retake-" + photo["id"]).click().run()
        assert not app.exception
        assert app.subheader[0].value == "Retake meal photo"
        assert get_pending(photo["id"], db_path=db) is None
        assert get_pending(other["id"], db_path=db) is not None
        app.button(key="cancel_retake").click().run()
        assert app.subheader[0].value == "Meal to confirm"


def test_legacy_cup_can_be_removed_and_restored_like_any_food(tmp_path):
    db = tmp_path / "old-cup.db"
    draft = make_draft("photo", "", {"white-rice": 100, "fdc-2710375": 200}, [])
    draft.update(status="ready", quick_drinks=["kopi", "unknown"])
    create_pending(draft, db_path=db)
    prefix = "meal-" + draft["id"]
    with patch("app.cloud_diary", return_value=db):
        app = AppTest.from_string("from app import main\nmain(public_demo=True)", default_timeout=20)
        app.run().button(key=prefix + "-remove-fdc-2710375").click().run()
        assert not any("-cup-" in (b.key or "") for b in app.button)
        app.button(key=prefix + "-undo-row").click().run()
        assert app.number_input(key=prefix + "-grams-fdc-2710375").value == 200
        app.button(key=prefix + "-confirm").click().run()
        assert not app.exception


def test_gym_push_has_lateral_raise_and_pull_keeps_face_pull():
    push = split_exercises("gym", "push")
    assert "cable_raise" in push and "face_pull" not in push
    assert split_exercises("gym", "pull")[-1] == "face_pull"


def test_delete_one_meal_recalculates_diary_and_blocks_old_pending(tmp_path):
    db = tmp_path / "history.db"
    today = datetime.now(SG_TIME).date()
    entries = [make_ready(db, {food: grams}) for food, grams in (("white-rice", 120), ("boiled-egg", 50))]
    for draft in entries:
        assert save_meal(draft, portion_items(load_foods(), draft["input"]["suggested_grams"]), db_path=db)
    original = list_meals(today, db_path=db)
    remaining = next(row["totals"] for row in original if row["id"] == entries[1]["id"])
    assert delete_meal(entries[0]["id"], db)
    assert not delete_meal(entries[0]["id"], db)
    assert not create_pending(entries[0], db_path=db)
    assert total_nutrients([r["totals"] for r in list_meals(today, db_path=db)]) == remaining
    assert today in recent_activity(today, db_path=db)
    assert delete_meal(entries[1]["id"], db)
    assert today not in recent_activity(today, db_path=db)


def test_home_meters_and_receipt_after_deleting_a_confirmed_meal(tmp_path):
    db = tmp_path / "receipt.db"
    today = datetime.now(SG_TIME).date()
    save_profile(Profile(age=26, height_cm=170, weight_kg=65, activity="regular", start=today), db_path=db)
    first = make_ready(db, {"white-rice": 120})
    rice, = portion_items(load_foods(), {"white-rice": 120})
    save_meal(first, [rice], db_path=db)
    second = make_ready(db, {"boiled-egg": 50})
    with patch("app.cloud_diary", return_value=db):
        app = AppTest.from_string("from app import main\nmain(public_demo=True)", default_timeout=20)
        app.query_params["lang"] = "en"
        app.run().button(key="meal-" + second["id"] + "-confirm").click().run()
        assert app.session_state.receipt["id"] == second["id"]
        # Deleting the receipt meal in a second tab must update this home too.
        assert delete_meal(second["id"], db)
        app.run()
        assert "receipt" not in app.session_state
        meters = next(el.proto.body for el in app.get("html") if 'role="progressbar"' in el.proto.body)
        assert f'aria-valuetext="{rice["nutrients"]["kcal"]:.0f} kcal,' in meters
        assert f'aria-valuetext="{rice["nutrients"]["protein_g"]:.0f} g,' in meters


@pytest.mark.parametrize(("equipment", "rear"), [("bodyweight", "prone_w"), ("dumbbells", "reverse_fly"), ("gym", "face_pull")])
@pytest.mark.parametrize("theme", ["pull", "back"])
def test_pull_day_finishes_with_a_distinct_rear_delt_exercise(equipment, rear, theme):
    moves = split_exercises(equipment, theme)
    assert len(moves) == len(set(moves)) == 4
    assert moves[-1] == rear
    assert not {"machine_press", "db_press", "pike"}.intersection(moves)


@pytest.mark.parametrize("reapply", [False, True])
def test_applying_schedule_frees_today_and_drops_orphan_workouts(tmp_path, reapply):
    db = tmp_path / "plans.db"
    monday = date(2026, 11, 23)
    prefs = TrainingPreferences(mode="strength", equipment="gym", weekdays=(0, 4) if reapply else (1, 3),
                                since=monday - timedelta(days=7))
    p = Profile(age=25, height_cm=172, weight_kg=66, activity="regular", start=prefs.since, training=prefs)
    save_profile(p, db_path=db)
    before, tues = monday - timedelta(days=1), monday + timedelta(days=1)
    with closing(open_db(db)) as conn, conn:
        for table, day in [("rest_days", monday), ("workouts", tues), ("workouts", before)]:
            conn.execute(f"INSERT INTO {table} VALUES (?)", (day.isoformat(),))
    new = prefs.model_copy(update={"weekdays": (0, 4), "since": monday})
    p = save_training_preferences(p, new, db_path=db)
    assert planned_days(p, before, tues, db_path=db) == {before, monday}
