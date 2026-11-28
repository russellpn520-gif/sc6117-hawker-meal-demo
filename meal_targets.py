"""Per-meal estimates derived from the current diary and local food portions."""
from dataclasses import dataclass

from catalog import NUTRIENTS
from planning import CARDIO, LARGE

# Only count identifiable non-starchy vegetable components. A mixed dish may
# contain unquantified vegetables, so the UI describes the logged components.
VEGETABLES = {"stir-fried-broccoli", "fdc-169967", "fdc-170457", "fdc-2709784", "fdc-168463", "fdc-2709593"}


VEGETABLE_NAMES = {"broccoli", "spinach", "cabbage", "carrots", "kale", "cauliflower", "bok choy",
                   "lettuce", "tomatoes", "cucumber", "asparagus", "eggplant", "zucchini", "green beans"}


def vegetable_grams(items):
    return sum(i.get("confirmed_g", 0) for i in items if i.get("food_id") in VEGETABLES
               or i.get("source_name", "").partition(",")[0].strip().lower() in VEGETABLE_NAMES)


@dataclass(frozen=True)
class MealTarget:
    mode: str
    amounts: dict
    remaining: dict
    veg_gap: bool


def meal_target(plan, eaten, rows, partial=False, choice=None):
    remaining = {}
    if plan and not partial:
        daily = dict(kcal=sum(plan.kcal)/2, protein_g=plan.protein_g, carb_g=plan.carb_g, fat_g=plan.fat_g)
        remaining = {key: max(0, daily[key] - eaten.get(key, 0)) for key in NUTRIENTS}
    mode = choice or ("snack" if remaining.get("kcal", 350) < 350 else "one" if len(rows) >= 2 else "two")
    if mode not in {"one", "two", "snack"}:
        raise ValueError("meal count")
    factor = .5 if mode == "two" else 1
    if mode == "snack" and remaining.get("kcal", 0) > 300:
        factor = 300 / remaining["kcal"]
    veg_gap = bool(rows and not partial and sum(vegetable_grams(r.get("items", [])) for r in rows) < 65 * len(rows))
    return MealTarget(mode, {k: v * factor for k, v in remaining.items()}, remaining, veg_gap)


SCALES = {"kcal": 200, "protein_g": 14, "carb_g": 30, "fat_g": 12}
NAMES = {"protein_g": ("蛋白质", "protein"), "carb_g": ("碳水", "carbohydrate"),
         "fat_g": ("脂肪", "fat"), "kcal": ("能量", "energy")}


def fit_score(target, totals, veg_g):
    score = sum(abs(totals[k] - v) / SCALES[k] for k, v in target.amounts.items())
    if target.veg_gap:
        score += max(0, 1 - veg_g / 80)
    return score


def fit_reason(target, totals, veg_g):
    if target.veg_gap and veg_g >= 60:
        return ("这份搭配带一份青菜，补上日记里较少见的蔬菜。", "A vegetable serving rounds out what you have logged today.")
    if not target.amounts or not any(target.amounts.values()):
        return ("按你的饮食偏好挑选，份量照胃口调整。", "Picked for your food preferences. Adjust the portion to your appetite.")
    k = max(NAMES, key=lambda k: min(totals[k], target.amounts[k]) / SCALES[k])
    zh, en = NAMES[k]
    return (f"按这顿的余量，这份搭配最能帮你补{zh}。", f"For this meal, this choice helps most with {en}.")


def daily_hint(plan, eaten, veg_gap, hour):
    slot = {"morning": 8, "afternoon": 14, "evening": 18}.get(plan.time_slot)
    if slot is not None and 0 <= slot - hour <= 3:
        return ("快到平常训练的时间了，下一顿可选清淡主食。", "Your usual workout is coming up. Try an easy-to-digest carb.")
    if slot is not None and 0 < hour - slot <= 3:
        return ("如果已经练完，下一顿给蛋白质留个位置。", "If you have finished training, include some protein in your next meal.")
    if (plan.theme in CARDIO or plan.theme in LARGE) and eaten.get("carb_g", 0) < plan.carb_g * .5:
        return ("今天的训练要用到碳水，下一顿给主食留个位置。", "Carbs help fuel today’s session. Keep a staple in your next meal.")
    if veg_gap:
        return ("日记里单独记下的蔬菜较少，下一顿可以加一份青菜。", "Few vegetables were logged separately. Try a side of greens next time.")
    if eaten.get("fat_g", 0) >= plan.fat_g:
        return ("下一顿想吃清爽些，可以试试清汤或蒸菜。", "For a lighter next meal, try clear soup or a steamed dish.")
    return ("下一顿按胃口来，目标是一天的参考。", "Let your appetite guide the next meal. Targets are a daily guide.")
