"""Deterministic adult strength templates, actual sessions, and the coach's read-only view."""

import json
from contextlib import closing
from datetime import date, timedelta
from math import isfinite

from meals import _planned_days, open_db, planned_days
from planning import ACTIVITIES, CARDIO, THEMES, Profile, training_theme, valid_training_move


EXERCISES = {
    "squat": ("徒手浅蹲", "Bodyweight mini squat"),
    "wall_push": ("靠墙俯卧撑", "Wall push-up"),
    "heel_raise": ("站姿提踵", "Standing heel raise"),
    "curl": ("哑铃弯举", "Dumbbell curl"),
}
# Three complementary movements per region, using only the selected equipment.
MOVEMENTS = {
    "bodyweight": {
        "chest": ("wall_push|靠墙俯卧撑|Wall push-up", "incline_push|上斜俯卧撑|Incline push-up", "pushup|俯卧撑|Push-up"),
        "back": ("self_row|单臂自抗阻划船|Self-resisted single-arm row", "prone_w|俯卧 W 收肩|Prone W raise", "self_curl|自抗阻弯举|Self-resisted biceps curl"),
        "shoulder": ("pike|折刀俯卧撑|Pike push-up", "wall_slide|靠墙滑臂|Wall slide", "scap_push|肩胛俯卧撑|Scapular push-up"),
        "legs": ("squat|徒手浅蹲|Bodyweight mini squat", "bridge|臀桥|Glute bridge", "lunge|后撤箭步蹲|Reverse lunge"),
        "core": ("deadbug|死虫式|Dead bug", "side_lift|侧桥抬髋|Side plank hip lift", "march|仰卧交替抬腿|Supine march"),
    },
    "dumbbells": {
        "chest": ("floor_press|哑铃地板卧推|Dumbbell floor press", "squeeze|哑铃夹胸推|Dumbbell squeeze press", "single_press|单臂地板卧推|Single-arm floor press"),
        "back": ("db_row|单臂哑铃划船|One-arm dumbbell row", "reverse_fly|哑铃反向飞鸟|Dumbbell reverse fly", "curl|哑铃弯举|Dumbbell curl"),
        "shoulder": ("db_press|哑铃肩推|Dumbbell overhead press", "lateral|哑铃侧平举|Dumbbell lateral raise", "scaption|哑铃肩胛平面举|Dumbbell scaption"),
        "legs": ("goblet|高脚杯深蹲|Goblet squat", "rdl|哑铃罗马尼亚硬拉|Dumbbell Romanian deadlift", "split|哑铃分腿蹲|Dumbbell split squat"),
        "core": ("suitcase|单侧负重原地踏步|Suitcase march", "db_deadbug|哑铃死虫式|Dumbbell dead bug", "chop|哑铃对角举|Dumbbell diagonal lift"),
    },
    "gym": {
        "chest": ("bench|杠铃卧推|Barbell bench press", "incline|上斜器械推胸|Incline machine press", "pec|蝴蝶机夹胸|Pec deck fly"),
        "back": ("pulldown|高位下拉|Lat pulldown", "row|坐姿绳索划船|Seated cable row", "cable_curl|绳索弯举|Cable curl"),
        "shoulder": ("machine_press|器械肩推|Machine shoulder press", "face_pull|绳索面拉|Cable face pull", "cable_raise|绳索侧平举|Cable lateral raise"),
        "legs": ("leg_press|腿举|Leg press", "leg_curl|坐姿腿弯举|Seated leg curl", "hip_thrust|器械臀推|Machine hip thrust"),
        "core": ("pallof|绳索抗旋推|Pallof press", "cable_chop|绳索伐木|Cable chop", "crunch|跪姿绳索卷腹|Kneeling cable crunch"),
    },
}
SPLITS = {
    "full": ("legs", "chest", "back", "core"), "upper": ("chest", "back", "shoulder", "back"),
    "lower": ("legs", "legs", "core", "legs"), "push": ("chest", "shoulder", "chest", "shoulder"),
    "pull": ("back", "back", "back", "shoulder"), "legs": ("legs", "legs", "legs", "core"),
    "chest": ("chest", "shoulder", "chest", "shoulder"), "back": ("back", "back", "back", "shoulder"),
    "core": ("core", "core", "legs", "core"),
}
WEIGHTED = {"curl"}
for equipment, regions in MOVEMENTS.items():
    for region, movements in regions.items():
        for movement in movements:
            key, zh, en = movement.split("|")
            EXERCISES[key] = (zh, en)
            if equipment != "bodyweight":
                WEIGHTED.add(key)


def split_exercises(equipment, theme):
    used, result = {}, []
    for region in SPLITS[theme]:
        index = used.get(region, 0)
        result.append(MOVEMENTS[equipment][region][index].split("|")[0])
        used[region] = index + 1
    return result


DAYS = (("一", "Mon"), ("二", "Tue"), ("三", "Wed"), ("四", "Thu"),
        ("五", "Fri"), ("六", "Sat"), ("日", "Sun"))
LOG_SCHEMA = """CREATE TABLE IF NOT EXISTS training_log
    (day TEXT PRIMARY KEY, status TEXT NOT NULL, actuals TEXT NOT NULL, targets TEXT NOT NULL)"""


def save_training_preferences(profile, prefs, *, db_path=None):
    """Keep past dates and compatible future overrides when the user edits availability."""
    with closing(open_db(db_path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT data FROM profile WHERE id = 1").fetchone()
        if not row:
            raise ValueError("A saved profile is required.")
        current = Profile.model_validate_json(row[0])
        history = current.training_history
        if current.training:
            old = current.training
            if old.model_dump(exclude={"since"}) == prefs.model_dump(exclude={"since"}):
                return current
            if already_logged(db, prefs.since):
                prefs = prefs.model_copy(update={"since": prefs.since + timedelta(days=1)})
            if old.since < prefs.since:
                history = (*history, old)
        updated = current.model_copy(update={"training": prefs, "training_history": history})
        start = prefs.since
        # Prefer already-confirmed moves as long as they allow a recovery day.
        overrides = [date.fromisoformat(day) for day, in
                     db.execute("SELECT day FROM workouts WHERE day >= ? ORDER BY day", (start.isoformat(),))]
        rests = {date.fromisoformat(day) for day, in db.execute("SELECT day FROM rest_days WHERE day >= ?",
                                                               (start.isoformat(),))}
        kept = set()
        for day in overrides:
            adjacent = [day - timedelta(days=1), day + timedelta(days=1)]
            neighbors = {d for d in adjacent if d in kept or (updated.scheduled_by_default(d) and d not in rests)}
            moved = db.execute("SELECT original_day FROM workout_moves WHERE day=?", (day.isoformat(),)).fetchone()
            # A changed weekly split can retire the original appointment or
            # assign another workout at the destination. Release that override.
            original = date.fromisoformat(moved[0]) if moved else None
            conflict = original and (not updated.scheduled_by_default(original) or updated.scheduled_by_default(day))
            if not conflict and valid_training_move(updated, day, day, neighbors):
                kept.add(day)
            else:
                db.execute("DELETE FROM workouts WHERE day=?", (day.isoformat(),))
                db.execute("DELETE FROM workout_moves WHERE day=?", (day.isoformat(),))
                if original and original >= start:
                    db.execute("DELETE FROM rest_days WHERE day=?", (original.isoformat(),))
        db.execute("UPDATE profile SET data=? WHERE id=1", (updated.model_dump_json(),))
    return updated


def read_logs(start, end, *, db_path=None):
    with closing(open_db(db_path)) as db:
        db.execute(LOG_SCHEMA)
        rows = db.execute("SELECT day, status, actuals, targets FROM training_log WHERE day BETWEEN ? AND ? ORDER BY day",
                          (start.isoformat(), end.isoformat())).fetchall()
    return [{"date": day, "status": status, "actuals": json.loads(actuals), "targets": json.loads(targets)}
            for day, status, actuals, targets in rows]


def already_logged(db, day):
    db.execute(LOG_SCHEMA)
    return db.execute("SELECT 1 FROM training_log WHERE day=?", (day.isoformat(),)).fetchone() is not None


def _template(profile):
    prefs = profile.training
    exercises = ["squat", "wall_push"]
    if prefs.minutes >= 20:
        exercises.append("curl" if prefs.equipment == "dumbbells" else "heel_raise")
    sets = 2 if prefs.minutes >= 20 and profile.activity in {"regular", "athlete"} else 1
    return exercises, sets


def _session(profile, day, active, history, lang):
    prefs = profile.training
    en = lang == "en"
    base = {"date": day.isoformat(), "mode": "rest", "minutes": 0, "exercises": []}
    if day not in active or day < prefs.since:
        return base
    past = [r for r in history if prefs.since.isoformat() <= r["date"] < day.isoformat()]
    recent = past[-1] if past else {}
    days_since = (day - date.fromisoformat(recent["date"])).days if recent else 0
    week = (day - prefs.since).days // 7 + 1
    recent_difficult = [r["status"] for r in past[-2:]] == ["challenging", "challenging"]
    lighter = week % 4 == 0 or recent_difficult
    recovering = recent.get("status") == "missed" or days_since >= 14
    theme = training_theme(profile, day, active)
    base["theme"] = theme
    if theme in CARDIO:
        # The easy blocks include warm-up and cool-down. Harder work is optional
        # and appears only for established exercisers outside recovery weeks.
        level = "easy"
        if profile.activity in {"regular", "athlete"} and not (lighter or recovering) and prefs.minutes >= 20:
            level = ("easy", "tempo", "interval")[(week - 1) % 3]
        duration = min(prefs.minutes, max(10, round(prefs.minutes * .7))) if lighter or recovering else prefs.minutes
        return {**base, "mode": "cardio", "intensity": level, "week": week, "minutes": duration,
                "planned_minutes": duration}
    exercises, sets = _template(profile)
    if theme in SPLITS:
        exercises = split_exercises(prefs.equipment, theme)[:2 if prefs.minutes == 10 else 4 if prefs.minutes >= 30 else 3]
        sets = min(3, max(1, (prefs.minutes - 4) // (3 * len(exercises))))
        if profile.activity in {"inactive", "occasional"}:
            sets = min(2, sets)
    mode = "deload" if lighter else "return" if recovering else "strength"
    for key in exercises:
        baseline = 6 if profile.activity in {"inactive", "occasional"} else 8
        start_reps = max(4, baseline - 2) if lighter else baseline
        target_sets, reps = (1 if lighter or recovering else sets), start_reps
        load = None if key in WEIGHTED else 0
        previous = [r for r in past if r["actuals"].get(key)]
        if previous:
            last = previous[-1]
            done = last["actuals"][key]
            target_sets = min(target_sets, len(done))
            if key in WEIGHTED:
                load = min(s["kg"] for s in done)
            last_min = min(s["reps"] for s in done)
            reps = min(reps, last_min) if lighter or recovering else min(max(1, last_min), 12)
            # Two consecutive comfortable completions of every prescribed set at
            # the same load qualify for one extra repetition. No automatic kg jump.
            comparable = (not lighter and not recovering and len(previous) >= 2
                          and all(r["status"] == "comfortable" and key in r["targets"]
                                  and len(r["actuals"].get(key, [])) >= target_sets
                                  and all(s["reps"] >= max(reps, r["targets"][key]["reps"]) and s["kg"] == load
                                          for s in r["actuals"][key]) for r in previous[-2:]))
            if comparable and reps >= 5:
                reps = min(12, reps + 1)
        base["exercises"].append({"id": key, "name": EXERCISES[key][en], "sets": target_sets,
                                  "reps": reps, "kg": load})
    # Budget 3 minutes for the warm-up and 2.5 minutes per set including rest.
    working_minutes = 3 + (5 * sum(ex["sets"] for ex in base["exercises"]) + 1) // 2
    finish_walk = min(5, prefs.minutes - working_minutes) if profile.goal_factor < 1 and not (lighter or recovering) else 0
    if prefs.mode == "mixed" and len(prefs.weekdays) == 1:
        base["aerobic_finish"] = prefs.cardio
        finish_walk = max(1, prefs.minutes - working_minutes)
    return {**base, "mode": mode, "minutes": prefs.minutes, "week": week,
            "walk_minutes": max(0, finish_walk), "planned_minutes": working_minutes + max(0, finish_walk)}


def training_context(profile, today, *, db_path=None, lang="zh"):
    if not profile or not profile.training_for(today):
        return {"configured": False, "next_step": "training_setup", "sessions": [], "recent_logs": []}
    prefs = profile.training_for(today)
    end = today + timedelta(days=6)
    history = read_logs(prefs.since, end, db_path=db_path)
    active = planned_days(profile, today, end, db_path=db_path)
    dates = [today + timedelta(days=i) for i in range(7)]
    sessions = [_session(profile.model_copy(update={"training": profile.training_for(d)}), d, active, history, lang)
                for d in dates]
    return {"configured": True, "period_start": today.isoformat(), "sessions": sessions,
            "equipment": prefs.equipment, "available_weekdays": list(prefs.weekdays),
            "session_minutes": prefs.minutes, "recent_logs": [r for r in history if r["date"] <= today.isoformat()][-4:]}


def session_lines(session, lang):
    en = lang == "en"
    if session["mode"] == "rest":
        return ["Recovery day. Your next strength session stays on the calendar." if en else "今天安排恢复，下一次力量训练见日程。"]
    if session["mode"] == "cardio":
        minutes = session["planned_minutes"]
        warm = min(5, minutes // 4)
        middle = minutes - 2 * warm
        cues = {
            "easy": ("轻松匀速，能完整说一句话", "Steady conversational effort"),
            "tempo": ("中段舒适偏快，仍能说短句", "Steady tempo at a short-sentence effort"),
            "interval": ("中段交替 1 分钟稍快、2 分钟轻松", "Alternate 1 minute brisk and 2 minutes easy"),
        }
        return [f"{THEMES[session['theme']][en]} · {minutes} min",
                (f"Easy {warm} min · {cues[session['intensity']][en]} {middle} min · easy {warm} min" if en else
                 f"轻松热身 {warm} 分钟 · {cues[session['intensity']][en]} {middle} 分钟 · 放松 {warm} 分钟")]
    labels = {"strength": ("力量训练", "Strength session"), "return": ("恢复训练节奏", "Return session"),
              "deload": ("减量训练", "Lighter session")}
    lines = [f"{labels[session['mode']][en]} · {session['planned_minutes']} min"]
    if session.get("theme") in SPLITS:
        lines[0] = THEMES[session["theme"]][en] + " · " + lines[0]
        lines.append("Warm-up · Bodyweight mini squat and easy arm circles" if en else "热身 · 徒手浅蹲和轻松绕肩")
    for ex in session["exercises"]:
        line = f"{ex['name']} · {ex['sets']} × {ex['reps']}"
        if ex["id"] in WEIGHTED:
            line += (f" · {ex['kg']:g} kg" if ex["kg"] is not None else
                     " · choose a familiar light weight" if en else " · 选熟悉、轻松的重量")
        lines.append(line)
    if session.get("walk_minutes"):
        lines.append((THEMES[session["aerobic_finish"]][en] if session.get("aerobic_finish") else "Easy walk" if en else "轻松步行") + f" · {session['walk_minutes']} min")
    return lines


def training_reply(profile, day, *, db_path=None, lang="zh"):
    context = training_context(profile, day, db_path=db_path, lang=lang)
    if not context["configured"]:
        en = lang == "en"
        if not profile:
            return ("Create your personal plan to see a training schedule based on your activity level."
                    if en else "先建立个人计划，就能看到按你的运动习惯安排的训练日。")
        if day < profile.start:
            return (f"Your training plan starts on {profile.start.isoformat()}." if en
                    else f"你的训练计划从 {profile.start.isoformat()} 开始。")
        active = day in planned_days(profile, day, day, db_path=db_path)
        label = ("Training day" if active else "Rest day") if en else ("训练日" if active else "休息日")
        if en:
            # Reuse the baseline recommendation shown on the training screen.
            from plan_ui import ACTIVITY_EN
            tier = ACTIVITY_EN[profile.activity]
            advice = tier.training if active else tier.rest
        else:
            tier = ACTIVITIES[profile.activity]
            advice = (tier.advice if active else tier.recovery).replace("今天", "这天")
        suggestion = ("For specific exercises, open Training and add your equipment, available days and session length."
                      if en else "想看具体动作，可以在「训练安排」补充器械、可训练日和每次时长。")
        return f"{day.isoformat()} · {label}\n\n{advice}\n\n{suggestion}"
    session = context["sessions"][0]
    lines = [day.isoformat(), *session_lines(session, lang)]
    if session["mode"] == "rest":
        following = next((s for s in context["sessions"][1:] if s["mode"] != "rest"), None)
        if following:
            lines.extend([("Next" if lang == "en" else "下次") + " · " + following["date"], *session_lines(following, lang)])
    return "\n\n".join(lines)


def save_training_log(profile, day, today, status, actuals, *, db_path=None):
    if day > today or not profile.training_for(day):
        raise ValueError("date")
    if status not in {"missed", "comfortable", "challenging"}:
        raise ValueError("status")
    session = training_context(profile, day, db_path=db_path)["sessions"][0]
    if session["mode"] == "rest":
        raise ValueError("rest")
    targets = {e["id"]: {"sets": e["sets"], "reps": e["reps"], "kg": e["kg"]} for e in session["exercises"]}
    if status == "missed":
        actuals = {}
    elif session["mode"] == "cardio":
        if (set(actuals) != {"minutes", "rpe"} or type(actuals["minutes"]) is not int
                or not 1 <= actuals["minutes"] <= 600 or type(actuals["rpe"]) is not int or not 1 <= actuals["rpe"] <= 10):
            raise ValueError("duration/effort")
        targets = {"minutes": session["planned_minutes"], "theme": session["theme"]}
    elif not actuals or not set(actuals) <= targets.keys():
        raise ValueError("exercises")
    for key, sets in (actuals.items() if session["mode"] != "cardio" else ()):
        if not 1 <= len(sets) <= 20:
            raise ValueError("sets")
        for item in sets:
            rep, kg = item.get("reps"), item.get("kg")
            if (type(rep) is not int or not 1 <= rep <= 200 or type(kg) not in (int, float)
                    or not isfinite(kg) or not 0 <= kg <= 300 or (key not in WEIGHTED and kg != 0)):
                raise ValueError("reps/load")
    with closing(open_db(db_path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT data FROM profile WHERE id=1").fetchone()
        if not row:
            raise ValueError("profile")
        current = Profile.model_validate_json(row[0])
        if (current.training_for(day) != profile.training_for(day)
                or day not in _planned_days(db, current, day, day)):
            raise ValueError("schedule changed")
        db.execute(LOG_SCHEMA)
        db.execute("INSERT INTO training_log VALUES (?,?,?,?) ON CONFLICT(day) DO UPDATE SET "
                   "status=excluded.status, actuals=excluded.actuals",
                   (day.isoformat(), status, json.dumps(actuals), json.dumps(targets)))
