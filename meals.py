import json
import os
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from planning import Profile
from catalog import NUTRIENTS, ROOT, load_foods


SG_TIME = timezone(timedelta(hours=8))


def make_draft(method, description, suggested, unmatched):
    return {
        "id": str(uuid4()),
        "input": {"method": method, "description": description,
                  "suggested_grams": suggested, "unmatched": unmatched},
    }


def match_text(text, foods):
    """Match listed dish names. Accept an optional weight or a half portion per item."""
    grams = {}
    unknown = []
    # Database names may themselves contain a comma (e.g. "Salsa, red").
    entries = re.split(r"[、，；;＋+\n]", text)
    parts = []
    for entry in entries:
        raw_name = re.sub(r"\s*\d+\s*(?:g|克)\s*$", "", entry.strip(), flags=re.I).removeprefix("半份").strip()
        parts.extend([entry] if foods.exact_food(raw_name) else entry.split(","))
    for entry in parts:
        entry = entry.strip()
        if not entry:
            continue
        name = entry
        weight = re.search(r"(\d+)\s*(?:克|g)\s*$", name, re.IGNORECASE)
        if weight:
            name = name[:weight.start()].strip()
        half = name.startswith("半份") or name.endswith("半份")
        if half:
            name = name.removeprefix("半份").removesuffix("半份").strip()
        key = foods.exact_food(name)
        if key is None or (weight and half):
            unknown.append(entry)
            continue
        food = foods[key]
        amount = int(weight[1]) if weight else food.serving_g // (2 if half else 1)
        combined = grams.get(food.food_id, 0) + amount
        if not 1 <= amount <= 3000 or combined > 3000:
            unknown.append(entry)
            continue
        grams[food.food_id] = combined
    return make_draft("text", text, grams, unknown)


def portion_items(foods, grams):
    """Keep the reference and the confirmed portion together for later inspection."""
    items = []
    for food_id, weight in grams.items():
        if type(weight) is not int or not 1 <= weight <= 3000:
            raise ValueError("请将每项重量设为 1–3000 克。")
        food = foods[food_id]
        items.append({
            "food_id": food_id, "name": food.name, "confirmed_g": weight,
            "reference_g": food.reference_g, "reference_nutrients": food.nutrients,
            "source_name": food.source_name, "source_url": food.source_url,
            "source_label": food.source_label, "source_code": food.code,
            "nutrients": {key: value * weight / food.reference_g
                          for key, value in food.nutrients.items()},
        })
    return items


def total_nutrients(rows):
    return {key: sum(row[key] for row in rows) for key in NUTRIENTS}


def allocate_grams(weights, total, minimum=0):
    """Round proportional amounts to whole grams while preserving the given total."""
    remaining = total - minimum * len(weights)
    if not weights or remaining < 0:
        raise ValueError("总重不足以分配给所选项目。")
    ratios = {k: max(0, v - minimum) for k, v in weights.items()}
    if not any(ratios.values()):
        ratios = dict.fromkeys(weights, 1)
    denominator = sum(ratios.values())
    divisions = {k: divmod(v * remaining, denominator) for k, v in ratios.items()}
    grams = {k: minimum + q for k, (q, _) in divisions.items()}
    ordered = sorted(grams, key=lambda k: divisions[k][1], reverse=True)
    for k in ordered[:total - sum(grams.values())]:
        grams[k] += 1
    return grams


def open_db(db_path=None):
    path = Path(db_path or os.environ.get("TRACK3_DB") or ROOT / ".local" / "meals.sqlite3")
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS meals (
            id TEXT PRIMARY KEY, day TEXT NOT NULL, confirmed_at TEXT NOT NULL,
            input TEXT NOT NULL, items TEXT NOT NULL, totals TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS meals_by_day ON meals(day);
        CREATE TABLE IF NOT EXISTS workouts (day TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS rest_days (day TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS profile (id INTEGER PRIMARY KEY CHECK(id = 1), data TEXT NOT NULL);
    """)
    return db


def save_meal(draft, items, *, db_path=None):
    if not items:
        raise ValueError("请至少选一项食物。")
    now = datetime.now(SG_TIME)
    sums = total_nutrients([item["nutrients"] for item in items])
    payload = [json.dumps(part, ensure_ascii=False) for part in (draft["input"], items, sums)]
    with closing(open_db(db_path)) as db, db:
        db.execute("""
            INSERT INTO meals(id, day, confirmed_at, input, items, totals)
            VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING
        """, (draft["id"], now.date().isoformat(), now.isoformat(), *payload))


def list_meals(day, *, db_path=None):
    with closing(open_db(db_path)) as db:
        records = db.execute("""
            SELECT confirmed_at, input, items, totals FROM meals
            WHERE day = ? ORDER BY confirmed_at DESC
        """, (day.isoformat(),)).fetchall()
    return [{"at": datetime.fromisoformat(at), "input": json.loads(raw),
             "items": json.loads(items), "totals": json.loads(totals)}
            for at, raw, items, totals in records]


def workout_days(start, end, *, db_path=None):
    with closing(open_db(db_path)) as db:
        rows = db.execute("SELECT day FROM workouts WHERE day BETWEEN ? AND ?",
                          (start.isoformat(), end.isoformat()))
        return {row[0] for row in rows}


def schedule_workout(destination, origin=None, *, db_path=None):
    with closing(open_db(db_path)) as db, db:
        if origin is None:
            result = db.execute("INSERT OR IGNORE INTO workouts(day) VALUES (?)",
                                (destination.isoformat(),))
        else:
            result = db.execute("UPDATE OR IGNORE workouts SET day = ? WHERE day = ?",
                                (destination.isoformat(), origin.isoformat()))
        return result.rowcount == 1


def get_profile(*, db_path=None):
    with closing(open_db(db_path)) as db:
        row = db.execute("SELECT data FROM profile WHERE id = 1").fetchone()
    return Profile.model_validate_json(row[0]) if row else None


def save_profile(profile, *, db_path=None):
    with closing(open_db(db_path)) as db, db:
        db.execute("INSERT INTO profile VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                   (profile.model_dump_json(),))


def _planned_days(db, profile, start, end):
    days = {start + timedelta(days=i) for i in range((end - start).days + 1)
            if profile.scheduled_by_default(start + timedelta(days=i))}
    bounds = (start.isoformat(), end.isoformat())
    days.update(date.fromisoformat(d) for d, in db.execute("SELECT day FROM workouts WHERE day BETWEEN ? AND ?", bounds))
    days.difference_update(date.fromisoformat(d) for d, in db.execute("SELECT day FROM rest_days WHERE day BETWEEN ? AND ?", bounds))
    return days


def planned_days(profile, start, end, *, db_path=None):
    with closing(open_db(db_path)) as db:
        return _planned_days(db, profile, start, end)


def move_workout(profile, origin, destination, *, db_path=None):
    if origin == destination:
        return False
    with closing(open_db(db_path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        active = _planned_days(db, profile, min(origin, destination), max(origin, destination))
        if origin not in active or destination in active:
            return False
        old, new = (origin.isoformat(),), (destination.isoformat(),)
        db.execute("DELETE FROM workouts WHERE day = ?", old)
        db.execute("INSERT OR IGNORE INTO rest_days VALUES (?)", old)
        db.execute("DELETE FROM rest_days WHERE day = ?", new)
        db.execute("INSERT OR IGNORE INTO workouts VALUES (?)", new)
        return True


def clear_diary(*, db_path=None):
    with closing(open_db(db_path)) as db, db:
        db.execute("DELETE FROM meals")
        db.execute("DELETE FROM workouts")
        db.execute("DELETE FROM rest_days")
        db.execute("DELETE FROM profile")
