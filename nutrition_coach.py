"""Offer a dinner to order or cook, using the diary's saved preferences and food catalogue."""

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
    prepare: tuple = ()


RECIPES = (
    Recipe(("姜香鸡肉西兰花饭", "Ginger chicken and broccoli rice"), (("rice", 185), ("chicken", 115), ("greens", 100), ("ginger", 6)),
           ("煮好米饭。鸡肉加姜蒸熟，西兰花蒸软后一起配饭。", "Cook the rice. Steam the chicken with ginger until cooked through, steam the broccoli and serve together.")),
    Recipe(("姜香鱼柳饭", "Tilapia and ginger rice"), (("fish", 130), ("rice", 180), ("greens", 100), ("ginger", 6)),
           ("鱼柳铺姜片蒸熟，配米饭和蒸西兰花。", "Steam the fish with ginger until cooked through. Serve with rice and steamed broccoli.")),
    Recipe(("番茄黑豆饭碗", "Tomato and black bean rice bowl"), (("black_bean", 160), ("rice", 170), ("tomato", 110), ("oil", 5)),
           ("煮熟的黑豆和番茄用少量橄榄油炖软，盖在米饭上。", "Simmer cooked black beans and tomato in a little olive oil, then spoon over rice.")),
    Recipe(("豆腐西兰花饭", "Tofu and broccoli rice"), (("tofu", 145), ("rice", 170), ("greens", 100), ("ginger", 5)),
           ("豆腐和西兰花铺上姜片一起蒸热，配一碗米饭。", "Steam the tofu and broccoli with sliced ginger and serve over rice.")),
    Recipe(("鸡蛋豆腐饭", "Egg and tofu rice"), (("egg", 100), ("tofu", 100), ("rice", 175), ("cucumber", 90)),
           ("鸡蛋煮熟切半，豆腐蒸热，和黄瓜片一起铺在饭上。", "Halve the boiled eggs, steam the tofu and serve over rice with sliced cucumber.")),
    Recipe(("番茄鹰嘴豆藜麦碗", "Chickpea, tomato and quinoa bowl"), (("chickpea", 145), ("quinoa", 160), ("tomato", 100), ("oil", 5)),
           ("把煮熟的藜麦和鹰嘴豆拌匀，加番茄丁和少许橄榄油。", "Mix the cooked quinoa and chickpeas with diced tomato and a little olive oil.")),
    Recipe(("扁豆烤红薯", "Baked sweet potato with lentils"), (("sweet_potato", 225), ("lentil", 170), ("tomato", 90), ("oil", 6)),
           ("红薯烤软切开，填入煮熟的扁豆与番茄，淋少许橄榄油。", "Bake the sweet potato until tender, split it and top with cooked lentils, tomato and a little olive oil.")),
    Recipe(("番茄扁豆意面", "Tomato and lentil pasta"), (("pasta", 170), ("lentil", 130), ("tomato", 110), ("oil", 5)),
           ("意面煮熟，拌入用少许橄榄油炖好的番茄和熟扁豆。", "Cook the pasta and toss with cooked lentils and tomato simmered in a little olive oil.")),
)


@dataclass(frozen=True)
class Preferences:
    budget_cents: int | None
    diet: str
    allergies: tuple | None  # None = unreported; () = explicitly no known allergies.
    avoid: tuple = ()
    other_restriction: str = ""


def _valid(prefs):
    return (isinstance(prefs, Preferences)
            and (prefs.budget_cents is None or type(prefs.budget_cents) is int and prefs.budget_cents > 0)
            and prefs.diet in DIETS and set(prefs.allergies or ()) <= ALLERGENS.keys()
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
    db.execute("""CREATE TABLE IF NOT EXISTS dinner_mode (
        id INTEGER PRIMARY KEY CHECK(id=1), mode TEXT NOT NULL CHECK(mode IN ('out','home'))
    )""")
    return db


def get_dinner_mode(db_path):
    with closing(_prefs_db(db_path)) as db:
        row = db.execute("SELECT mode FROM dinner_mode WHERE id=1").fetchone()
        return row[0] if row else None


def save_dinner_mode(db_path, mode):
    if mode not in ("out", "home"):
        raise ValueError("Unknown dinner mode")
    with closing(_prefs_db(db_path)) as db, db:
        db.execute("INSERT OR REPLACE INTO dinner_mode VALUES (1, ?)", (mode,))


def get_preferences(db_path):
    with closing(_prefs_db(db_path)) as db:
        row = db.execute("SELECT data FROM nutrition_preferences WHERE id=1").fetchone()
    if row:
        try:
            data = json.loads(row[0])
            if data.get("allergies") is not None:
                data["allergies"] = tuple(data["allergies"])
            data["avoid"] = tuple(data["avoid"])
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


def _dinner_fit(totals, remaining_kcal, remaining_protein):
    kcal, protein = _target(remaining_kcal), _target(remaining_protein)
    score = abs(totals["kcal"] - kcal) / 150 if kcal is not None else 0
    if protein is not None:
        score += max(0, protein - totals["protein_g"]) / 15
    return score


def _allows(key, prefs):
    ingredient = INGREDIENTS.get(key)
    allowed_kinds = {"any": {"plant", "egg", "fish", "meat"}, "vegan": {"plant"},
                     "vegetarian": {"plant", "egg"}, "pescatarian": {"plant", "egg", "fish"}}[prefs.diet]
    return (ingredient is not None and ingredient.kind in allowed_kinds and key not in prefs.avoid
            and not set(prefs.allergies or ()).intersection(ingredient.allergens))


def plan_dinner(preferences, *, remaining_kcal=None, remaining_protein=None, budget_sgd=None, recipe_name=None):
    if not _valid(preferences) or preferences.other_restriction.strip() or "other" in (preferences.allergies or ()):
        return None
    limit = preferences.budget_cents
    if budget_sgd is not None:
        temporary = budget_cents(budget_sgd)
        if temporary is None:
            return None
        limit = min(limit, temporary) if limit is not None else temporary
    foods = load_foods()
    choices = []
    for recipe in RECIPES:
        if recipe_name is not None and recipe.names[1] != recipe_name:
            continue
        ingredients = [(key, INGREDIENTS.get(key), weight) for key, weight in recipe.grams]
        if any(not _allows(key, preferences) or item.food_id not in foods for key, item, _ in ingredients):
            continue
        shopping = [(key, *_purchase(item, weight)) for key, item, weight in ingredients]
        cost = sum(cents for _, _, cents in shopping)
        if limit is not None and cost > limit:
            continue
        portions = portion_items(foods, {item.food_id: grams for _, item, grams in ingredients})
        totals = total_nutrients([part["nutrients"] for part in portions])
        # Targets rank feasible dinners; a small remainder never forces a tiny serving.
        score = _dinner_fit(totals, remaining_kcal, remaining_protein)
        choices.append((score, cost, {"recipe": recipe, "shopping": shopping, "cost_cents": cost,
                                     "limit_cents": limit, "nutrients": totals, "items": portions}))
    return min(choices, key=lambda choice: choice[:2])[2] if choices else None


@dataclass(frozen=True)
class DinnerOrder:
    names: tuple
    order: tuple
    portions: tuple  # Ingredient key for exclusions, catalogue ID and as-served grams.


ORDERS = (
    DinnerOrder(("蒸鱼青菜饭", "Steamed fish with rice and greens"),
                ("一份白饭，配蒸鱼和西兰花，酱汁另放。", "Rice with steamed fish and broccoli, sauce on the side."),
                (("rice", "white-rice", 180), ("fish", "steamed-fish", 90), ("greens", "stir-fried-broccoli", 100))),
    DinnerOrder(("鸡肉蔬菜饭碗", "Chicken and vegetable rice bowl"),
                ("白饭配白切鸡和西兰花，酱汁另放。", "Plain rice with poached chicken and broccoli, sauce on the side."),
                (("rice", "white-rice", 180), ("chicken", "boiled-chicken", 90), ("greens", "stir-fried-broccoli", 100))),
    DinnerOrder(("豆腐黄瓜饭碗", "Tofu and cucumber rice bowl"),
                ("白饭配原味豆腐和黄瓜，调味汁另放。", "Rice with plain firm tofu and cucumber, dressing on the side."),
                (("rice", "white-rice", 180), ("tofu", "fdc-172475", 140), ("cucumber", "fdc-2709784", 80))),
    DinnerOrder(("鹰嘴豆藜麦碗", "Chickpea and quinoa bowl"),
                ("藜麦做底，加鹰嘴豆、番茄，调味汁另放。", "Quinoa with chickpeas and tomato, dressing on the side."),
                (("quinoa", "fdc-168917", 170), ("chickpea", "fdc-2707416", 150), ("tomato", "fdc-170457", 90))),
)


def _outside_dinner(prefs, lang, remaining_kcal, remaining_protein, budget_sgd):
    en = lang == "en"
    foods = load_foods()
    choices = []
    for order in ORDERS:
        if not all(_allows(key, prefs) and food_id in foods for key, food_id, _ in order.portions):
            continue
        portions = portion_items(foods, {food_id: grams for _, food_id, grams in order.portions})
        totals = total_nutrients([p["nutrients"] for p in portions])
        choices.append((_dinner_fit(totals, remaining_kcal, remaining_protein), order, portions, totals))
    if not choices:
        return ("No order in this short menu fits your saved preferences." if en
                else "这几种外食搭配暂时没有符合你已填偏好的选项。"), []

    _, order, portions, totals = min(choices, key=lambda item: item[0])
    lines = [f"**{order.names[int(en)]}**",
             (f'At the counter: “{order.order[1]}”' if en else f'可以这样点：「{order.order[0]}」'),
             (f"About {totals['kcal']:.0f} kcal · {totals['protein_g']:.1f} g protein" if en
              else f"约 {totals['kcal']:.0f} kcal · 蛋白质 {totals['protein_g']:.1f} g")]
    references = []
    for (key, _, _), item in zip(order.portions, portions):
        food = foods[item["food_id"]]
        if food.source == "hpb":
            name = food.source_name if en else food.name
        else:
            name = INGREDIENTS[key].names[int(en)].removeprefix("Dry ").removeprefix("干")
        references.append({"name": name, "grams": item["confirmed_g"], "source_url": food.source_url})
    if budget_sgd is not None or prefs.budget_cents is not None:
        limit = budget_cents(budget_sgd) if budget_sgd is not None else prefs.budget_cents
        if prefs.budget_cents is not None and limit is not None:
            limit = min(prefs.budget_cents, limit)
        if limit is not None:
            lines.append((f"Your limit is S${limit/100:.2f}. Check the menu price before ordering." if en
                          else f"预算 S${limit/100:.2f}，点单前请核对店内菜单价格。"))
    if prefs.allergies:
        allergens = ", ".join(ALLERGENS[a][int(en)] for a in prefs.allergies)
        lines.append((f"Tell the vendor about {allergens} and check sauces and shared equipment before ordering." if en
                      else f"点单前请向店家说明过敏原（{allergens}），核对酱料和共用厨具。"))
    if prefs.diet != "any":
        lines.append("Confirm the stock and seasoning match your diet." if en else "请向店家确认汤底与调味符合你的饮食偏好。")
    return "\n\n".join(lines), references


def dinner_result(db_path, *, lang="zh", remaining_kcal=None, remaining_protein=None,
                  shopping=False, budget_sgd=None, recipe_name=None, mode="home"):
    en = lang == "en"
    index = int(en)
    prefs = get_preferences(db_path) or Preferences(None, "any", None)
    if prefs.other_restriction.strip() or "other" in (prefs.allergies or ()):
        return ("Your restrictions go beyond the ingredients we can check. A verified dinner and shopping list are unavailable."
                if en else "你有目前食材表无法核实的过敏或忌口。这次没有可核实的晚餐和购物单。"), None
    if mode == "out":
        text, sources = _outside_dinner(prefs, lang, remaining_kcal, remaining_protein, budget_sgd)
        if prefs.allergies is None:
            text += "\n\n" + ("Allergies not provided." if en else "过敏信息未填写。")
        return text, {"reference_portions": sources} if sources else None
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
    limit = f"S${plan['limit_cents'] / 100:.2f}" if plan["limit_cents"] is not None else None
    title = recipe.names[index]
    price = f"One serving · ingredients about {cost}" if en else f"一人份 · 食材约 {cost}"
    if limit:
        price += f" · budget {limit}" if en else f" · 预算 {limit}"
    lines = [f"**{title}**", price,
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
        if recipe.prepare:
            lines.append(recipe.prepare[index])
    lines.append("Prices use assumed ingredient rates and edible quantities for home cooking. Full packs at checkout can cost more."
                 if en else "按家常烹饪的用量和假设单价估算，整包购买的结账金额可能更高。")
    if prefs.allergies:
        lines.append("Check the actual product labels and preparation area for cross-contact."
                     if en else "购买时请核对实际商品标签及备餐时的交叉接触情况。")
    elif prefs.allergies is None:
        lines.append("Allergies not provided." if en else "过敏信息未填写。")
    return "\n\n".join(lines), {"recipe_name": recipe.names[1], "budget_sgd": plan["limit_cents"] / 100 if limit else None}


def dinner_reply(db_path, **options):
    return dinner_result(db_path, **options)[0]
