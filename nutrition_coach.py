"""Plan one home-cooked dinner from the food catalogue and the diner's constraints."""

import json
from contextlib import closing
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from math import ceil, isfinite

from meals import load_foods, open_db, portion_items, total_nutrients


DIETS = {
    "any": ("都可以", "No dietary preference"), "vegetarian": ("蛋奶素", "Vegetarian"),
    "vegan": ("纯素", "Vegan"), "pescatarian": ("鱼素", "Pescatarian"),
}
ALLERGENS = {
    "egg": ("蛋", "Egg"), "milk": ("奶", "Milk"), "soy": ("大豆", "Soy"),
    "gluten": ("小麦或其他含麸质谷物", "Wheat or other gluten cereals"),
    "fish": ("鱼", "Fish"), "shellfish": ("甲壳类或贝类", "Crustaceans or molluscs"),
    "peanut": ("花生", "Peanut"), "tree_nut": ("坚果", "Tree nuts"),
    "sesame": ("芝麻", "Sesame"), "celery": ("芹菜", "Celery"), "mustard": ("芥末", "Mustard"),
    "lupin": ("羽扇豆", "Lupin"), "sulphites": ("亚硫酸盐", "Sulphites"),
    "other": ("其他或还不确定", "Other or unsure"),
}


@dataclass(frozen=True)
class Ingredient:
    food_id: str
    names: tuple
    cents_per_100g: int  # Assumed SGD cents per 100 g of edible shopping weight.
    yield_pct: int       # Served grams per 100 g of edible shopping weight.
    kind: str
    allergens: tuple


# Plain, single ingredients only. Cook using water and the listed ingredients.
# Quantities in the recipes are cooked/as-served weights and match the source food.
# Prices and cooking yields are local demo assumptions, never retailer quotations.
INGREDIENTS = {
    "rice": Ingredient("fdc-168878", ("干白米", "Dry white rice"), 28, 270, "plant", ()),
    "chicken": Ingredient("fdc-171478", ("去骨鸡胸", "Boneless chicken breast"), 155, 75, "meat", ()),
    "fish": Ingredient("fdc-175177", ("罗非鱼柳", "Tilapia fillet"), 225, 80, "fish", ("fish",)),
    "ginger": Ingredient("fdc-169231", ("鲜姜", "Fresh ginger"), 80, 100, "plant", ()),
    "greens": Ingredient("fdc-169967", ("西兰花", "Broccoli"), 72, 85, "plant", ()),
    "tofu": Ingredient("fdc-172475", ("原味硬豆腐", "Plain firm tofu"), 65, 100, "plant", ("soy",)),
    "egg": Ingredient("fdc-173424", ("鸡蛋", "Egg"), 76, 100, "egg", ("egg",)),
    "black_bean": Ingredient("fdc-2707361", ("干黑豆", "Dry black beans"), 70, 240, "plant", ()),
    "tomato": Ingredient("fdc-170457", ("番茄", "Tomato"), 65, 100, "plant", ()),
    "oil": Ingredient("fdc-2710186", ("橄榄油", "Olive oil"), 210, 100, "plant", ()),
    "quinoa": Ingredient("fdc-168917", ("干藜麦", "Dry quinoa"), 145, 300, "plant", ()),
    "chickpea": Ingredient("fdc-2707416", ("干鹰嘴豆", "Dry chickpeas"), 80, 235, "plant", ()),
    "cucumber": Ingredient("fdc-2709784", ("黄瓜", "Cucumber"), 43, 100, "plant", ()),
    "lentil": Ingredient("fdc-172421", ("干扁豆", "Dry lentils"), 65, 250, "plant", ()),
    "sweet_potato": Ingredient("fdc-2709699", ("红薯", "Sweet potato"), 55, 85, "plant", ()),
    "pasta": Ingredient("fdc-168928", ("纯小麦干意面", "Plain dry wheat pasta"), 55, 240, "plant", ("gluten",)),
}


@dataclass(frozen=True)
class Recipe:
    names: tuple
    grams: tuple


RECIPES = (
    Recipe(("姜香鸡肉西兰花饭", "Ginger chicken and broccoli rice"), (("rice", 185), ("chicken", 115), ("greens", 100), ("ginger", 6))),
    Recipe(("姜香鱼柳饭", "Tilapia and ginger rice"), (("fish", 130), ("rice", 180), ("greens", 100), ("ginger", 6))),
    Recipe(("番茄黑豆饭碗", "Tomato and black bean rice bowl"), (("black_bean", 160), ("rice", 170), ("tomato", 110), ("oil", 5))),
    Recipe(("豆腐西兰花饭", "Tofu and broccoli rice"), (("tofu", 145), ("rice", 170), ("greens", 100), ("ginger", 5))),
    Recipe(("鸡蛋豆腐饭", "Egg and tofu rice"), (("egg", 100), ("tofu", 100), ("rice", 175), ("cucumber", 90))),
    Recipe(("番茄鹰嘴豆藜麦碗", "Chickpea, tomato and quinoa bowl"), (("chickpea", 145), ("quinoa", 160), ("tomato", 100), ("oil", 5))),
    Recipe(("扁豆烤红薯", "Baked sweet potato with lentils"), (("sweet_potato", 225), ("lentil", 170), ("tomato", 90), ("oil", 6))),
    Recipe(("番茄扁豆意面", "Tomato and lentil pasta"), (("pasta", 170), ("lentil", 130), ("tomato", 110), ("oil", 5))),
)


@dataclass(frozen=True)
class Preferences:
    budget_cents: int
    diet: str
    allergies: tuple
    avoid: tuple = ()
    other_restriction: str = ""


def _valid(prefs):
    return (isinstance(prefs, Preferences) and type(prefs.budget_cents) is int and prefs.budget_cents > 0
            and prefs.diet in DIETS and set(prefs.allergies) <= ALLERGENS.keys()
            and set(prefs.avoid) <= INGREDIENTS.keys() and isinstance(prefs.other_restriction, str))


def budget_cents(value):
    try:
        amount = Decimal(str(value))
        return int((amount * 100).to_integral_value(rounding=ROUND_FLOOR)) if amount.is_finite() and amount >= 0 else None
    except (ValueError, TypeError, InvalidOperation, OverflowError):
        return None


def _prefs_db(db_path):
    db = open_db(db_path)
    db.execute("CREATE TABLE IF NOT EXISTS nutrition_preferences (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)")
    return db


def get_preferences(db_path):
    with closing(_prefs_db(db_path)) as db:
        row = db.execute("SELECT data FROM nutrition_preferences WHERE id=1").fetchone()
    if row:
        try:
            data = json.loads(row[0])
            data["allergies"], data["avoid"] = tuple(data["allergies"]), tuple(data["avoid"])
            prefs = Preferences(**data)
            return prefs if _valid(prefs) else None
        except (ValueError, TypeError, KeyError):
            return None
    return None


def save_preferences(db_path, prefs):
    if not _valid(prefs):
        raise ValueError("Invalid dinner preferences")
    with closing(_prefs_db(db_path)) as db, db:
        db.execute("INSERT OR REPLACE INTO nutrition_preferences VALUES (1, ?)", (json.dumps(asdict(prefs)),))


def _purchase(ingredient, grams):
    raw_g = ceil(grams * 100 / ingredient.yield_pct)
    return raw_g, ceil(raw_g * ingredient.cents_per_100g / 100)


def _target(value):
    if isinstance(value, (tuple, list)) and len(value) == 2:
        low, high = (_target(n) for n in value)
        return (low + high) / 2 if low is not None and high is not None else None
    if isinstance(value, (float, int)) and isfinite(value):
        return max(0, value)
    return None


def plan_dinner(preferences, *, remaining_kcal=None, remaining_protein=None, budget_sgd=None, recipe_name=None):
    if not _valid(preferences) or preferences.other_restriction.strip() or "other" in preferences.allergies:
        return None
    limit = preferences.budget_cents
    if budget_sgd is not None:
        temporary = budget_cents(budget_sgd)
        if temporary is None:
            return None
        limit = min(limit, temporary)
    allowed_kinds = {"any": {"plant", "egg", "fish", "meat"}, "vegan": {"plant"},
                     "vegetarian": {"plant", "egg"}, "pescatarian": {"plant", "egg", "fish"}}[preferences.diet]
    excluded, allergy = set(preferences.avoid), set(preferences.allergies)
    foods = load_foods()
    kcal, protein = _target(remaining_kcal), _target(remaining_protein)
    choices = []
    for recipe in RECIPES:
        if recipe_name is not None and recipe.names[1] != recipe_name:
            continue
        ingredients = [(key, INGREDIENTS.get(key), weight) for key, weight in recipe.grams]
        if any(item is None or item.food_id not in foods or key in excluded or item.kind not in allowed_kinds
               or allergy.intersection(item.allergens) for key, item, _ in ingredients):
            continue
        shopping = [(key, *_purchase(item, weight)) for key, item, weight in ingredients]
        cost = sum(cents for _, _, cents in shopping)
        if cost > limit:
            continue
        portions = portion_items(foods, {item.food_id: grams for _, item, grams in ingredients})
        totals = total_nutrients([part["nutrients"] for part in portions])
        # Targets rank feasible dinners; a small remainder never forces a tiny serving.
        score = (abs(totals["kcal"] - kcal) / 150 if kcal is not None else 0)
        if protein is not None:
            score += max(0, protein - totals["protein_g"]) / 15
        choices.append((score, cost, {"recipe": recipe, "shopping": shopping, "cost_cents": cost,
                                     "limit_cents": limit, "nutrients": totals, "items": portions}))
    return min(choices, key=lambda choice: choice[:2])[2] if choices else None


def dinner_result(db_path, *, lang="zh", remaining_kcal=None, remaining_protein=None,
                  shopping=False, budget_sgd=None, recipe_name=None):
    en = lang == "en"
    index = int(en)
    prefs = get_preferences(db_path)
    if prefs is None:
        return ("Set your one-person dinner budget, food preferences and allergies first."
                if en else "先填写一人份晚餐预算、饮食偏好和过敏情况，再为你配餐。"), None
    if prefs.other_restriction.strip() or "other" in prefs.allergies:
        return ("Your restrictions go beyond the ingredients we can check. A verified dinner and shopping list are unavailable."
                if en else "你有目前食材表无法核实的过敏或忌口。这次没有可核实的晚餐和购物单。"), None
    plan = plan_dinner(prefs, remaining_kcal=remaining_kcal, remaining_protein=remaining_protein,
                       budget_sgd=budget_sgd, recipe_name=recipe_name)
    if not plan:
        if recipe_name is not None:
            return ("This dinner no longer fits your saved preferences or budget. Choose a new dinner."
                    if en else "这份晚餐已不符合当前饮食偏好或预算，请重新选择晚餐。"), None
        return ("No dinner in the current recipe list meets this budget and all your food restrictions."
                if en else "现有餐单中没有同时符合本次预算、过敏要求和忌口的一人份晚餐。"), None
    recipe, totals = plan["recipe"], plan["nutrients"]
    cost = f"S${plan['cost_cents'] / 100:.2f}"
    limit = f"S${plan['limit_cents'] / 100:.2f}"
    title = recipe.names[index]
    lines = [f"**{title}**", (f"One serving · estimated {cost} of {limit}" if en else f"一人份 · 食材约 {cost}，预算 {limit}"),
             (f"About {totals['kcal']:.0f} kcal · protein {totals['protein_g']:.1f} g · carbs {totals['carb_g']:.1f} g · fat {totals['fat_g']:.1f} g"
              if en else f"约 {totals['kcal']:.0f} kcal · 蛋白质 {totals['protein_g']:.1f} g · 碳水 {totals['carb_g']:.1f} g · 脂肪 {totals['fat_g']:.1f} g")]
    if shopping:
        lines.append("**Shopping list**" if en else "**购物清单**")
        rows = []
        for key, grams, cents in plan["shopping"]:
            item = INGREDIENTS[key]
            weight = (f"{grams // 50} eggs" if en else f"{grams // 50} 个") if key == "egg" else f"{grams} g"
            rows.append(f"- {item.names[index]} · {weight} · S${cents / 100:.2f} (S${item.cents_per_100g / 100:.2f}/100 g)")
        lines.append("\n".join(rows))
    else:
        names = []
        for key, weight in recipe.grams:
            name = INGREDIENTS[key].names[index]
            name = name.removeprefix("Dry ").removeprefix("干")
            if key == "pasta":
                name = "Wheat pasta" if en else "小麦意面"
            names.append(f"{name} {weight} g")
        lines.append(("Edible portions as served: " if en else "上桌时的可食份量为 ") + (", " if en else "、").join(names))
    lines.append("Prices use assumed ingredient rates and edible quantities for home cooking. Full packs at checkout can cost more."
                 if en else "按家常烹饪的用量和假设单价估算，整包购买的结账金额可能更高。")
    if prefs.allergies:
        lines.append("Check the actual product labels and preparation area for cross-contact."
                     if en else "购买时请核对实际商品标签及备餐时的交叉接触情况。")
    return "\n\n".join(lines), {"recipe_name": recipe.names[1], "budget_sgd": plan["limit_cents"] / 100}


def dinner_reply(db_path, **options):
    return dinner_result(db_path, **options)[0]
