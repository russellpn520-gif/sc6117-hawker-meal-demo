from datetime import date, timedelta

from streamlit.testing.v1 import AppTest

from meals import save_profile
from planning import Profile, TrainingPreferences
from training_coach import read_logs, save_training_log, session_for_day


MONDAY = date(2026, 11, 23)
TODAY = MONDAY + timedelta(days=5)


def open_calendar(db, profile):
    save_profile(profile, db_path=db)
    script = f"""
from datetime import date
import streamlit as st
from meals import get_profile
from plan_ui import calendar_for_view, training_plan
db = {str(db)!r}
today = date.fromisoformat("{TODAY}")
p = get_profile(db_path=db)
training_plan(p, today, calendar_for_view(p, today, db), db,
              eaten={{"kcal": 600, "protein_g": 21, "carb_g": 90, "fat_g": 17}})
"""
    return AppTest.from_string(script, default_timeout=20).run()


def cell(app, day):
    return next(b for b in app.button if (b.key or "").startswith(f"cal_day_{day}_"))


def test_fortnight_selection_bilingual_labels_and_logged_cardio(tmp_path):
    db = tmp_path / "calendar.db"
    prefs = TrainingPreferences(mode="mixed", equipment="gym", weekdays=(0, 2, 4, 5),
                                cardio="swim", minutes=45, since=MONDAY)
    profile = Profile(age=29, height_cm=173, weight_kg=68, activity="regular", start=MONDAY, training=prefs)
    app = open_calendar(db, profile)
    assert not app.exception and not app.expander
    cells = [b for b in app.button if (b.key or "").startswith("cal_day_")]
    assert len(cells) == 14 and str(MONDAY) in cells[0].key and "2026-12-06" in cells[-1].key
    assert cell(app, TODAY).key.endswith("cardio_today_selected")
    assert any("已记 600" in c.value for c in app.caption)
    app.button(key="open_workout_log").click().run()
    app.number_input[0].set_value(24)
    next(b for b in app.button if b.label == "保存训练记录").click().run()
    assert cell(app, TODAY).key.endswith("done_today_selected")
    assert read_logs(TODAY, TODAY, db_path=db)[0]["actuals"]["minutes"] == 24
    assert not any(b.key == "open_move_days" for b in app.button)
    cell(app, MONDAY).click().run()
    assert "推" in cell(app, MONDAY).label
    app.button(key="open_workout_log").click().run()
    app.radio[0].set_value("missed").run()
    next(b for b in app.button if b.label == "保存训练记录").click().run()
    assert "漏" in cell(app, MONDAY).label
    app.session_state.ui_lang = "en"
    app.run()
    assert "Miss" in cell(app, MONDAY).label and app.session_state.selected_day == MONDAY
    assert app.button(key="open_workout_log").label == "Edit workout log"
    assert not any("Logged 600" in c.value for c in app.caption)
    assert not app.exception


def test_pre_setup_session_can_be_logged_on_suggested_day(tmp_path):
    db = tmp_path / "before-setup.db"
    profile = Profile(age=25, height_cm=170, weight_kg=65, activity="occasional", start=TODAY)
    save_profile(profile, db_path=db)
    assert session_for_day(profile, TODAY, db_path=db)["exercises"]
    save_training_log(profile, TODAY, TODAY, "comfortable", {"squat": [{"reps": 8, "kg": 0}]}, db_path=db)
    assert read_logs(TODAY, TODAY, db_path=db)[0]["actuals"]["squat"][0]["reps"] == 8
