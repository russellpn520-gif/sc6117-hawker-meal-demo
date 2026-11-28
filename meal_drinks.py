"""Editable reference cups for the hawker drinks counter."""
import json
from contextlib import closing
from dataclasses import dataclass

from meals import open_db
from nutrition_coach import get_preferences


@dataclass(frozen=True)
class Drink:
    names: tuple
    portions: dict
    allergen: str = ""


# Cup sizes are example servings. All nutrients come from these catalog items.
DRINKS = {
    "kopi": Drink(("Kopi O Kosong", "Kopi O Kosong"), {"fdc-2710375": 200}),
    "kopi_c": Drink(("Kopi C Siu Dai", "Kopi C Siu Dai"),
                    {"fdc-2710375": 175, "fdc-2705399": 20, "fdc-169655": 5}, "milk"),
    "teh": Drink(("Teh O Kosong", "Teh O Kosong"), {"fdc-173227": 200}),
    "soy": Drink(("无糖豆浆", "Unsweetened soy milk"), {"fdc-2705405": 200}, "soy"),
}


def available_drinks(preferences):
    if not preferences:
        return DRINKS
    allergens = set(preferences.allergies or ())
    if preferences.other_restriction or "other" in allergens:
        return {}
    if preferences.diet == "vegan":
        allergens.add("milk")
    return {key: drink for key, drink in DRINKS.items() if drink.allergen not in allergens}


def add_drink(db_path, draft_id, drink_id):
    return set_drink(db_path, draft_id, drink_id, added=True)


def set_drink(db_path, draft_id, drink_id, *, added):
    drinks = available_drinks(get_preferences(db_path)) if added else DRINKS
    drink = drinks.get(drink_id)
    if not drink:
        return False
    with closing(open_db(db_path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT data FROM pending WHERE id = ?", (draft_id,)).fetchone()
        if not row:
            return False
        data = json.loads(row[0])
        cups = data.setdefault("quick_drinks", [])
        if data.get("status") != "ready" or data["input"]["method"] == "label" or (drink_id in cups) == added:
            return False
        for option in (data["input"], *data.get("variants", {}).values()):
            grams = option["suggested_grams"]
            for food, amount in drink.portions.items():
                weight = grams.get(food, 0) + (amount if added else -amount)
                if weight > 3000:
                    return False
                if weight > 0:
                    grams[food] = weight
                else:
                    grams.pop(food, None)
        for edits in data.get("review_edits", {}).values():
            for food in drink.portions.keys() & edits.keys():
                weight = edits[food] + (drink.portions[food] if added else -drink.portions[food])
                if weight > 3000:
                    return False
                edits[food] = max(0, weight)
        if added:
            cups.append(drink_id)
        else:
            cups.remove(drink_id)
        db.execute("UPDATE pending SET data = ? WHERE id = ?", (json.dumps(data, ensure_ascii=False), draft_id))
        return True
