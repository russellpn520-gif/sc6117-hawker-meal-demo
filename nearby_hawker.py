"""Offline dinner cards for real Singapore venues. Distances are straight-line metres."""

import csv
import json
from contextlib import closing
from datetime import date, datetime
from functools import lru_cache
from math import asin, cos, isfinite, radians, sin, sqrt
from pathlib import Path
from urllib.parse import urlencode
from uuid import UUID

from meals import create_pending, get_pending, load_foods, make_draft, open_db, portion_items, total_nutrients
from nutrition_coach import Preferences, _dinner_fit, _valid, get_preferences


DATA = Path(__file__).resolve().parent / "data"
NEA_URL = "https://data.gov.sg/datasets/d_bda4baa634dd1cc7a6c7cad5f19e2d68/view"
NEA_SNAPSHOT_DATE = date(2026, 11, 28)
NEA_SCHEDULE_YEAR = 2026
LANDMARKS = {
    "ntu": {"names": ("NTU 北区广场", "NTU North Spine"), "coords": (1.34739, 103.68005)},
    "nus": {"names": ("NUS 大学城", "NUS UTown"), "coords": (1.30496, 103.77212)},
    "marina": {"names": ("滨海湾 · 市中心站", "Marina Bay · Downtown MRT"), "coords": (1.27949, 103.85283)},
    "river": {"names": ("里峇峇利 · 大世界站", "River Valley · Great World MRT"), "coords": (1.29389, 103.83370)},
}
SEARCH_RADIUS_M = 5000
PAGE_SIZE = 3


def _landmark_db(db_path):
    db = open_db(db_path)
    db.execute("CREATE TABLE IF NOT EXISTS nearby_landmark (id INTEGER PRIMARY KEY CHECK(id=1), landmark TEXT NOT NULL)")
    return db


def get_landmark(db_path):
    with closing(_landmark_db(db_path)) as db:
        row = db.execute("SELECT landmark FROM nearby_landmark WHERE id=1").fetchone()
    return row[0] if row and row[0] in LANDMARKS else "ntu"


def save_landmark(db_path, key):
    if key not in LANDMARKS:
        raise ValueError("unknown landmark")
    with closing(_landmark_db(db_path)) as db, db:
        db.execute("INSERT OR REPLACE INTO nearby_landmark VALUES (1, ?)", (key,))


def _coords(point):
    lat, lon = point
    if not all(isinstance(x, (int, float)) and isfinite(x) for x in (lat, lon)) or abs(lat) > 90 or abs(lon) > 180:
        raise ValueError("invalid coordinates")
    return lat, lon


def distance_m(a, b):
    lat1, lon1 = map(radians, _coords(a))
    lat2, lon2 = map(radians, _coords(b))
    hav = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return round(12_742_000 * asin(sqrt(min(1, hav))))


def _nea_date(value):
    if not value or str(value).strip().lower() in {"na", "n/a", "nil", "tbc", "-"}:
        return None
    value = str(value).strip()
    try:
        return date.fromisoformat(value)
    except ValueError:
        return datetime.strptime(value, "%d/%m/%Y").date()


def read_nea_centres(rows):
    """Read data.gov.sg datastore records / CSV rows (Singapore day/month order)."""
    centres = {}
    for row in rows:
        periods = []
        for start_key, end_key in [(f"q{n}_cleaningstartdate", f"q{n}_cleaningenddate") for n in range(1, 5)] + [
            ("other_works_startdate", "other_works_enddate")
        ]:
            start, end = _nea_date(row.get(start_key)), _nea_date(row.get(end_key))
            if start:
                periods.append((start, end or start))
        centres[row["name"]] = {"coords": (float(row["latitude_hc"]), float(row["longitude_hc"])),
                                "closure_dates": tuple(periods)}
    return centres


@lru_cache(maxsize=1)
def _directory():
    data = json.loads((DATA / "hawker_orders.json").read_text("utf-8"))
    with (DATA / "hawker_nea.csv").open(encoding="utf-8-sig", newline="") as fh:
        nea = read_nea_centres(csv.DictReader(fh))
    for venue in data["venues"].values():
        if "nea_name" in venue:
            venue.update(nea[venue["nea_name"]])
    return data


def _suitable(order, prefs):
    if not _valid(prefs) or prefs.other_restriction.strip() or "other" in (prefs.allergies or ()):
        return False
    if prefs.diet != "any" and prefs.diet not in order["diets"]:
        return False
    if prefs.avoid and (not order["ingredients_known"] or set(prefs.avoid).intersection(order["ingredients"])):
        return False
    # A missing vendor declaration is unknown, not evidence that an allergen is absent.
    # Even for documented ingredient choices the diner must check shared preparation at the counter.
    allergies = set(prefs.allergies or ())
    return allergies.issubset(order.get("checked_allergens", ())) and not allergies.intersection(order["allergens"])


def _closed(venue, today):
    return any(start <= today <= end for start, end in venue.get("closure_dates", ()))


def _room_for_special(training, remaining_kcal):
    low = remaining_kcal[0] if isinstance(remaining_kcal, (list, tuple)) and len(remaining_kcal) == 2 else remaining_kcal
    return training and isinstance(low, (int, float)) and isfinite(low) and low >= 850


def recommend_nearby(coords, today, *, preferences=None, remaining_kcal=None, remaining_protein=None, training=False, page=0):
    data = _directory()
    prefs = preferences if preferences is not None else Preferences(None, "any", None)
    special = _room_for_special(training, remaining_kcal)
    closed = {}
    ranked = []
    foods = load_foods()
    for order in data["orders"]:
        venue = data["venues"][order["venue"]]
        distance = distance_m(coords, venue["coords"])
        if distance > SEARCH_RADIUS_M or not _suitable(order, prefs):
            continue
        if _closed(venue, today):
            closed[order["venue"]] = venue["names"]
            continue
        if today.weekday() in order.get("closed_evenings", venue.get("closed_evenings", ())):
            continue
        items = portion_items(foods, order["portion_items"])
        totals = total_nutrients([i["nutrients"] for i in items])
        # Compare menus within walking-distance bands. A signature dish can lead nearby
        # alternatives on a training evening, but cannot displace venues across the island.
        style_mismatch = special != order["treat_friendly"]
        fit = min(3.0, _dinner_fit(totals, remaining_kcal, remaining_protein))
        score = (distance // 1000, style_mismatch, distance + 140 * fit,
                 -min(35, totals["protein_g"]), distance, order["id"])
        if special and order["treat_friendly"]:
            reason = ("今天有训练，余量也宽裕，今晚可以试试这份招牌。", "Training day with room in your target. This is a good evening for the house special.")
        elif not order["treat_friendly"] and remaining_protein is not None:
            reason = ("这份搭配就近，也把蛋白质算进了今天的余量。", "A nearby order picked with your remaining protein target in mind.")
        elif order["treat_friendly"]:
            reason = ("想吃本地招牌时，这份就在附近。", "A local speciality when you fancy one nearby.")
        else:
            reason = ("就在这一带，想简单吃顿饭可以照着点。", "A nearby option with an easy order for tonight.")
        maps_url = "https://www.google.com/maps/dir/?" + urlencode(
            {"api": 1, "destination": order["maps_query"], "travelmode": "walking"})
        card = {key: order[key] for key in ("id", "dish", "stall", "order", "note", "treat_friendly")}
        card.update(centre=venue["names"], distance_m=distance, maps_url=maps_url,
                    venue_url=data["sources"][order["source"]], centre_url=data["sources"][venue["source"]],
                    reason=reason, items=items, totals=totals)
        ranked.append((score, card))
    ranked.sort(key=lambda candidate: candidate[0])
    cards = [card for _, card in ranked]
    pages = (len(cards) + PAGE_SIZE - 1) // PAGE_SIZE
    start = max(0, page) % pages * PAGE_SIZE if pages else 0
    page_cards = (cards + cards)[start:start + min(PAGE_SIZE, len(cards))]
    return {"cards": page_cards, "total": len(cards), "closed": list(closed.values()),
            "schedule_covered": today.year == NEA_SCHEDULE_YEAR}


def add_nearby_draft(db_path, order_id, today, *, draft_id=None):
    """Recheck the saved restrictions and venue date before saving an editable, local draft."""
    data = _directory()
    order = next((item for item in data["orders"] if item["id"] == order_id), None)
    prefs = get_preferences(db_path) or Preferences(None, "any", None)
    if order is None or not _suitable(order, prefs):
        raise ValueError("unavailable")
    venue = data["venues"][order["venue"]]
    if _closed(venue, today) or today.weekday() in order.get("closed_evenings", venue.get("closed_evenings", ())):
        raise ValueError("unavailable")
    grams = dict(order["portion_items"])
    portion_items(load_foods(), grams)
    draft = make_draft("text", " / ".join(order["dish"]), grams, [])
    draft["status"] = "ready"
    draft["input"]["nearby_order_id"] = order_id
    if draft_id is not None:
        draft["id"] = str(UUID(str(draft_id)))
    if not create_pending(draft, db_path=db_path):
        existing = get_pending(draft["id"], db_path=db_path)
        if not existing or existing["input"].get("nearby_order_id") != order_id:
            raise ValueError("unavailable")
    return draft["id"]
