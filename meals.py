import json
import base64
import binascii
import os
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from time import time

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
        CREATE TABLE IF NOT EXISTS pending (
            id TEXT PRIMARY KEY, captured_at TEXT NOT NULL, data TEXT NOT NULL,
            photo BLOB NOT NULL, lease TEXT, lease_until REAL
        );
        CREATE TABLE IF NOT EXISTS discarded (id TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS draft_sync (
            id INTEGER PRIMARY KEY CHECK(id = 1), generation TEXT NOT NULL,
            revision INTEGER NOT NULL, hydrated INTEGER NOT NULL
        );
        INSERT OR IGNORE INTO draft_sync VALUES (1, lower(hex(randomblob(16))), 0, 0);
        CREATE TRIGGER IF NOT EXISTS pending_added AFTER INSERT ON pending BEGIN
            UPDATE draft_sync SET revision = revision + 1;
        END;
        CREATE TRIGGER IF NOT EXISTS pending_changed AFTER UPDATE OF data ON pending BEGIN
            UPDATE draft_sync SET revision = revision + 1;
        END;
        CREATE TRIGGER IF NOT EXISTS pending_removed AFTER DELETE ON pending BEGIN
            UPDATE draft_sync SET revision = revision + 1;
        END;
    """)
    return db


def _pending_data(draft, photo):
    data = {k: v for k, v in draft.items() if k not in {"photo", "captured_at", "id"}}
    data.setdefault("status", "queued" if photo else "ready")
    return json.dumps(data, ensure_ascii=False)


def create_pending(draft, photo=b"", *, db_path=None):
    now = datetime.now(SG_TIME)
    when = now
    if draft.get("captured_at"):
        try:
            supplied = datetime.fromisoformat(draft["captured_at"])
            if supplied.tzinfo and now - timedelta(days=365) <= supplied <= now + timedelta(minutes=5):
                when = supplied.astimezone(SG_TIME)
        except (TypeError, ValueError):
            pass
    with closing(open_db(db_path)) as db, db:
        return db.execute("""
            INSERT OR IGNORE INTO pending(id, captured_at, data, photo)
            SELECT ?, ?, ?, ? WHERE NOT EXISTS (SELECT 1 FROM meals WHERE id = ?)
              AND NOT EXISTS (SELECT 1 FROM discarded WHERE id = ?)
        """, (draft["id"], when.isoformat(), _pending_data(draft, photo), photo, draft["id"], draft["id"])).rowcount == 1


def _pending_record(row):
    key, captured_at, data, photo = row
    return {**json.loads(data), "id": key, "captured_at": captured_at, "photo": photo}


def list_pending(*, db_path=None):
    with closing(open_db(db_path)) as db:
        return [_pending_record(row) for row in db.execute(
            "SELECT id, captured_at, data, photo FROM pending ORDER BY captured_at DESC, id")]


def get_pending(key, *, db_path=None):
    with closing(open_db(db_path)) as db:
        row = db.execute("SELECT id, captured_at, data, photo FROM pending WHERE id = ?", (key,)).fetchone()
    return _pending_record(row) if row else None


def update_pending(draft, *, db_path=None):
    """A manual edit takes priority over an in-flight photo recognition."""
    with closing(open_db(db_path)) as db, db:
        return db.execute("UPDATE pending SET data = ?, lease = NULL, lease_until = NULL WHERE id = ?",
                          (_pending_data(draft, draft.get("photo")), draft["id"])).rowcount == 1


def claim_pending(key, *, db_path=None):
    """Allow at most one worker to recognize this dish during the model timeout."""
    token = uuid4().hex
    now = time()
    with closing(open_db(db_path)) as db, db:
        changed = db.execute("""
            UPDATE pending SET lease = ?, lease_until = ? WHERE id = ?
              AND (lease IS NULL OR lease_until < ?)
              AND json_extract(data, '$.status') IN ('queued', 'failed')
        """, (token, now + 120, key, now)).rowcount
    return token if changed else None


def finish_pending(draft, *, claim, db_path=None):
    with closing(open_db(db_path)) as db, db:
        return db.execute("""
            UPDATE pending SET data = ?, lease = NULL, lease_until = NULL WHERE id = ? AND lease = ?
        """, (_pending_data(draft, draft.get("photo")), draft["id"], claim)).rowcount == 1


def discard_pending(key, *, db_path=None):
    with closing(open_db(db_path)) as db, db:
        changed = db.execute("DELETE FROM pending WHERE id = ?", (key,)).rowcount
        if changed:
            db.execute("INSERT OR IGNORE INTO discarded VALUES (?)", (key,))
        return bool(changed)


def draft_cursor(*, db_path):
    with closing(open_db(db_path)) as db:
        return db.execute("SELECT generation, revision, hydrated FROM draft_sync").fetchone()


def export_pending(*, db_path):
    with closing(open_db(db_path)) as db:
        db.execute("BEGIN")
        generation, revision = db.execute("SELECT generation, revision FROM draft_sync").fetchone()
        rows = [{"id": k, "at": at, "data": data, "jpeg": base64.b64encode(photo).decode("ascii")}
                for k, at, data, photo in db.execute("SELECT id, captured_at, data, photo FROM pending")]
    return {"generation": generation, "revision": revision, "rows": rows}


def restore_pending(rows, *, db_path):
    """Recover only this device's unfinished meals after a cloud disk reset."""
    with closing(open_db(db_path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT hydrated FROM draft_sync").fetchone()[0]:
            return
        for row in rows if isinstance(rows, list) else ():
            try:
                key, at, raw, jpeg = (row[c] for c in ("id", "at", "data", "jpeg"))
                if not re.fullmatch(r"[a-f0-9-]{32,36}", key) or len(raw) > 250_000 or len(jpeg) > 3_000_000:
                    continue
                capture = datetime.fromisoformat(at)
                data = json.loads(raw)
                if (capture.tzinfo is None or data["status"] not in {"queued", "ready", "failed"}
                        or not isinstance(data["input"]["suggested_grams"], dict)):
                    continue
                photo = base64.b64decode(jpeg, validate=True)
            except (AttributeError, TypeError, KeyError, ValueError, binascii.Error):
                continue
            db.execute("""
                INSERT OR IGNORE INTO pending(id, captured_at, data, photo)
                SELECT ?, ?, ?, ? WHERE NOT EXISTS (SELECT 1 FROM meals WHERE id = ?)
                  AND NOT EXISTS (SELECT 1 FROM discarded WHERE id = ?)
            """, (key, at, raw, photo, key, key))
        db.execute("UPDATE draft_sync SET hydrated = 1")


class IncompleteMealError(ValueError):
    """The caller must resolve missing foods or explicitly save a partial meal."""


def save_meal(draft, items, *, db_path=None):
    if not items:
        raise ValueError("请至少选一项食物。")
    meal_input = draft["input"]
    missing = meal_input.get("unmatched_foods") or meal_input.get("missing_items")
    if missing and meal_input.get("partial_record") is not True:
        raise IncompleteMealError("这餐还有食物未计入，请补选或选择仅记录已选食物。")
    now = datetime.now(SG_TIME)
    sums = total_nutrients([item["nutrients"] for item in items])
    with closing(open_db(db_path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        saved = db.execute("SELECT captured_at FROM pending WHERE id = ?", (draft["id"],)).fetchone()
        if not saved and ("captured_at" in draft or
                          db.execute("SELECT 1 FROM discarded WHERE id = ?", (draft["id"],)).fetchone()):
            return False
        day = datetime.fromisoformat(saved[0]).astimezone(SG_TIME).date() if saved else now.date()
        original = {**draft["input"], "captured_at": saved[0]} if saved else draft["input"]
        payload = [json.dumps(part, ensure_ascii=False) for part in (original, items, sums)]
        inserted = db.execute("""
            INSERT INTO meals(id, day, confirmed_at, input, items, totals)
            VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING
        """, (draft["id"], day.isoformat(), now.isoformat(), *payload)).rowcount
        if saved:
            db.execute("DELETE FROM pending WHERE id = ?", (draft["id"],))
        return bool(inserted)


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
        db.execute("DELETE FROM pending")
        db.execute("DELETE FROM discarded")
        db.execute("DELETE FROM meals")
        db.execute("DELETE FROM workouts")
        db.execute("DELETE FROM rest_days")
        db.execute("DELETE FROM profile")
