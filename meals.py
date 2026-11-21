import csv
import json
import os
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parent
SG_TIME = timezone(timedelta(hours=8))
SOURCE = (
    "https://isomer-user-content.by.gov.sg/484/d2884b81-4dfc-4a9e-b153-1487969794d5/"
    "obesity-cpg_main_for-online-30-aug.pdf"
)
NUTRIENTS = ("kcal", "protein_g", "carb_g", "fat_g")


@dataclass(frozen=True)
class Food:
    food_id: str
    name: str
    source_name: str
    aliases: tuple[str, ...]
    serving_g: int
    nutrients: dict[str, float]
    page: int

    @property
    def source_url(self):
        return f"{SOURCE}#page={self.page + 7}"


def load_foods():
    with (ROOT / "foods.csv").open(encoding="utf-8", newline="") as file:
        return {
            row["food_id"]: Food(
                row["food_id"], row["name"], row["source_name"],
                tuple(row["aliases"].split("|")), int(row["serving_g"]),
                {key: float(row[key]) for key in NUTRIENTS}, int(row["source_page"]),
            )
            for row in csv.DictReader(file)
        }


def make_draft(method, description, suggested, unmatched):
    return {
        "id": str(uuid4()),
        "input": {"method": method, "description": description,
                  "suggested_grams": suggested, "unmatched": unmatched},
    }


def match_text(text, foods):
    """Match listed dish names. Accept an optional weight or a half portion per item."""
    aliases = {alias.casefold(): food for food in foods.values()
               for alias in (food.name, *food.aliases)}
    grams = {}
    unknown = []
    for entry in re.split(r"[、，,；;＋+\n]", text):
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
        food = aliases.get(name.casefold())
        if food is None or (weight and half):
            unknown.append(entry)
            continue
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
            "reference_g": food.serving_g, "reference_nutrients": food.nutrients,
            "source_name": food.source_name, "source_url": food.source_url,
            "nutrients": {key: value * weight / food.serving_g
                          for key, value in food.nutrients.items()},
        })
    return items


def total_nutrients(rows):
    return {key: sum(row[key] for row in rows) for key in NUTRIENTS}


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
