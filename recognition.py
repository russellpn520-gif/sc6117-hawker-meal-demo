import base64
import io
import re

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from meals import make_draft


PHOTO_MODEL = "gpt-5-mini"
CHICKEN_RICE_PLATES = {"chicken-rice-plate", "sgstudy-steamed-chicken-rice", "sgstudy-roasted-chicken-rice"}
RICE_REFERENCES = {"white-rice", "fdc-2708407", "fdc-2708408"}
RICE_PREPARATION_UNKNOWN = "米饭（白饭或油饭，做法待确认）"
GREENS_WITH_DRESSING = re.compile(r"^(?:焯水?|白灼|烫|汆烫|水煮)(?:绿叶菜|青菜|绿色蔬菜)(?:搭配|配|拌|淋|佐|加)(.{1,30}(?:油|酱|汁))$")


class VisibleFood(BaseModel):
    english: str = Field(description="Short conventional English food name, including cooking method if visible")
    chinese: str = Field(description="Short common Chinese name")
    low_g: int = Field(description="Plausible lower bound for edible grams actually served; 0 when unknown")
    high_g: int = Field(description="Plausible upper bound for edible grams actually served; 0 when unknown")


class Dish(BaseModel):
    whole: VisibleFood
    parts: list[VisibleFood] = Field(description="Visible ingredients within this dish, if mixed")


class MealPhoto(BaseModel):
    dishes: list[Dish] = Field(description="One entry per separate dish or side")
    uncertain_items: list[str] = Field(description="Unidentified items or material uncertainties, in Chinese")
    portion_note: str = Field(description="用一句自然中文说明照片中的大小参照及估量限制。")


class BilingualMealPhoto(MealPhoto):
    uncertain_items_en: list[str] = Field(description="English translations of uncertain_items, in the same order")
    portion_note_en: str = Field(description="One short English translation of portion_note")


def portion_guess(food, seen):
    low, high = seen.low_g, seen.high_g
    if not 0 < low <= high <= 3000:
        return food.serving_g, None
    mid = (low + high) / 2
    step = 5 if mid >= 30 else 1
    return max(low, min(high, round(mid / step) * step)), [low, high]


def match_visible(seen, foods):
    if GREENS_WITH_DRESSING.fullmatch(seen.chinese):
        return None
    key = foods.photo_match(seen.english, seen.chinese)
    if key:
        return key
    # A photographed bowl can be matched generically even when the restaurant,
    # filling or market cannot be identified well enough for a labelled serving.
    if "burrito bowl" in seen.english.casefold() or re.search("墨西哥.*碗", seen.chinese):
        return foods.exact_food("burrito bowl")
    return None


def missing_item(key, seen, foods, exclude=()):
    low, high = seen.low_g, seen.high_g
    if not 0 < low <= high <= 3000:
        low = high = 0
    options = (["white-rice", "fdc-2708407"] if seen.chinese == RICE_PREPARATION_UNKNOWN
               else [k for k in foods.photo_suggestions(seen.english, seen.chinese) if k not in exclude])
    return {"key": key, "name": seen.chinese or seen.english or "未辨认食物",
            "name_en": ("Rice (plain or cooked with fat)" if seen.chinese == RICE_PREPARATION_UNKNOWN
                        else seen.english or "Unidentified food"), "alternatives": options,
            "low_g": low, "high_g": high, "replace_food_ids": []}


def dressing_rows(key, sauce):
    # The visual estimate is for the mixed side; each component needs its
    # own quantity instead of applying the mixed dish's weight to either.
    return [{"key": key + "-greens", "name": "烫青菜（只计蔬菜）", "name_en": "Blanched greens (vegetables only)",
             "alternatives": ["fdc-2709593"],
             "low_g": 0, "high_g": 0, "replace_food_ids": []},
            {"key": key + "-dressing", "name": sauce + "（单独核对调味）", "name_en": "Dressing on the greens",
             "alternatives": [],
             "low_g": 0, "high_g": 0, "replace_food_ids": []}]


def component_gap(whole, parts):
    """Check if even the highest ingredient estimates leave the dish uncovered."""
    if 0 < whole.low_g <= whole.high_g <= 3000 and all(0 < p.low_g <= p.high_g <= 3000 for _, p in parts):
        return sum(p.high_g for _, p in parts) < whole.low_g
    # With just a single topping and no scale we cannot establish coverage.
    return len(parts) == 1


def is_soup(seen, food_id=None):
    if food_id == "fdc-2707132":
        return True
    # Exclude a rice or other solid explicitly cooked in stock.
    return bool(re.search(r"^(?:一碗|配餐|配菜|附赠)?(?:清汤|鸡汤|高汤|例汤|蔬菜汤)(?:[（(].*)?$", seen.chinese)
                or re.fullmatch(r"(?:clear |chicken |vegetable )?(?:soup|broth)(?: with .*)?", seen.english.lower()))


def resolve_photo(result, foods, filename):
    groups = []
    embedded_broth = False
    stock_uncertain = any("饭" in line and re.search("鸡汤|鸡油|油饭|加油", line)
                          and re.search("不确定|无法|难以|是否|不明|不清楚|可能", line)
                          for line in result.uncertain_items)
    for dish in result.dishes[:20]:
        whole_key = match_visible(dish.whole, foods)
        parts = []
        chicken_rice = (whole_key in CHICKEN_RICE_PLATES or "海南鸡饭" in dish.whole.chinese
                        or "hainanese chicken rice" in dish.whole.english.casefold())
        for part in dish.parts[:25]:
            key = match_visible(part, foods)
            if chicken_rice and len(dish.parts) > 1 and (
                key in CHICKEN_RICE_PLATES or (stock_uncertain and key in RICE_REFERENCES)
            ):
                # A whole HPB plate and the study's steamed/roasted chicken
                # rice all include the chicken. None represent the rice alone.
                key = None if stock_uncertain else next(
                    (k for k in (foods.exact_food(part.chinese), foods.exact_food(part.english))
                     if k in RICE_REFERENCES), None)
                if key is None:
                    part = part.model_copy(update={"chinese": RICE_PREPARATION_UNKNOWN})
            elif key and key == whole_key and key != "boiled-chicken" and len(dish.parts) > 1:
                # E.g. an English "chicken rice" for the flavoured rice part
                # must not count the entire chicken plate next to its chicken.
                english = foods.exact_food(part.english)
                chinese = foods.exact_food(part.chinese)
                key = next((k for k in (chinese, english) if k and k != whole_key), None)
            parts.append((key, part))
        if whole_key == "fdc-2708555":
            part_ids = {key for key, _ in parts}
            has_rice = bool(part_ids & {"white-rice", "fdc-2708408", "fdc-2708414"})
            has_beans = "fdc-2707359" in part_ids
            beef = bool(part_ids & {"fdc-2705824", "fdc-2705849"})
            chicken = bool(part_ids & {"boiled-chicken", "fdc-2705968"})
            if beef != chicken:
                recipes = (("2708556", "2708557", "2708558", "2708559") if beef else
                           ("2708560", "2708561", "2708562", "2708563"))
                whole_key = "fdc-" + recipes[int(has_rice) + 2 * int(has_beans)]
        # The chicken-rice references cover the plate of rice and chicken.
        # If the model weighs a tray including broth, applying the plate's
        # energy density to that weight would count the broth as rice/chicken.
        tray_with_soup = chicken_rice and any(is_soup(p, k) for k, p in parts)
        embedded_broth |= tray_with_soup
        # The plain meat reference covers no side vegetables or dressing.
        # Use the photographed weight of the chicken pieces within this plate.
        chicken_with_sides = whole_key == "boiled-chicken" and any(k != whole_key for k, _ in parts)
        parts_only = tray_with_soup or chicken_with_sides
        groups.append(((whole_key, dish.whole), parts, parts_only))

    def variant(by_parts):
        grams, ranges, missing = {}, {}, []
        for index, (whole, parts, parts_only) in enumerate(groups):
            using_parts = (by_parts or parts_only) and bool(parts)
            items = parts if using_parts else [whole]
            exclude = {whole[0]} if using_parts else set()
            if using_parts and not whole[0]:
                exclude.update(foods.photo_suggestions(whole[1].english, whole[1].chinese))
            for subindex, (key, seen) in enumerate(items):
                item_key = f"d{index}-p{subindex}" if using_parts else f"d{index}"
                if not key:
                    if dressing := GREENS_WITH_DRESSING.fullmatch(seen.chinese):
                        missing.extend(dressing_rows(item_key, dressing[1]))
                    else:
                        missing.append(missing_item(item_key, seen, foods, exclude))
                    continue
                amount, bounds = portion_guess(foods[key], seen)
                sum_g = grams.get(key, 0) + amount
                if sum_g > 3000:
                    missing.append({"key": item_key, "name": f"{foods[key].name}超出份量范围",
                                    "name_en": f"{seen.english or 'Food'} exceeds the portion range",
                                    "alternatives": [], "low_g": 0, "high_g": 0, "replace_food_ids": []})
                    continue
                if key not in grams:
                    ranges[key] = bounds
                elif bounds and ranges[key]:
                    ranges[key] = [min(3000, a + b) for a, b in zip(ranges[key], bounds)]
                else:
                    ranges[key] = None
                grams[key] = sum_g
            same_food = len(parts) == 1 and whole[0] and parts[0][0] == whole[0]
            missing_chicken = (parts_only and whole[0] == "boiled-chicken"
                               and not any(k == whole[0] or "鸡" in p.chinese or "chicken" in p.english.casefold()
                                           for k, p in parts))
            if using_parts and not same_food and (missing_chicken or component_gap(whole[1], parts)):
                # Never suggest adding an entire dish on top of its ingredients.
                # The separate whole-dish view can replace all components at once.
                missing.append({"key": f"d{index}-gap", "name": f"{whole[1].chinese or whole[1].english}（未覆盖的配料）",
                                "name_en": f"Other ingredients in {whole[1].english or 'this dish'}",
                                "alternatives": [], "low_g": 0, "high_g": 0, "replace_food_ids": []})
        names = list(dict.fromkeys(item["name"] for item in missing))
        names_en = list(dict.fromkeys(item["name_en"] for item in missing))
        notes_en = list(getattr(result, "uncertain_items_en", []))
        alternatives = list(dict.fromkeys(k for item in missing for k in item["alternatives"]))
        return {"suggested_grams": grams, "portion_ranges": ranges, "alternatives": alternatives,
                "uncertain_items_en": notes_en, "unmatched_foods_en": names_en,
                "unmatched_en": list(dict.fromkeys([*notes_en, *names_en])),
                "uncertain_items": list(result.uncertain_items), "unmatched_foods": names, "missing_items": missing,
                "unmatched": list(dict.fromkeys(u for u in [*result.uncertain_items, *names] if u))}

    whole, parts = variant(False), variant(True)
    # If the dish has no whole reference, start with the available components.
    # Retain a separate dish-level choice for correcting the whole by name.
    prefer_parts = any(forced or (key is None and any(k for k, _ in p)) for (key, _), p, forced in groups)
    variants = {"按配料": parts, "整道菜": whole} if prefer_parts else {"整道菜": whole, "按配料": parts}
    first = next(iter(variants.values()))
    draft = make_draft("photo", filename, first["suggested_grams"], first["unmatched"])
    portion_note = result.portion_note
    portion_note_en = getattr(result, "portion_note_en", "")
    if embedded_broth:
        portion_note += " 鸡饭和汤按各自的份量分别查表。"
        portion_note_en += " Chicken rice and soup are estimated separately."
    draft["input"].update(first, portion_note=portion_note.strip(), portion_note_en=portion_note_en.strip(),
                          photo_resolution_version=3)
    if parts != whole:
        draft["variants"] = variants
    return draft


def _recover_bilingual_components(draft):
    """Version 2 retained the bilingual descriptions, group IDs and portions of unresolved foods."""
    from catalog import load_foods, mixed_soy_ginger_sauce

    foods = load_foods()
    original = draft["input"]
    variants = draft.get("variants", {})
    ingredient_groups = {}

    def rematch(view, *, ingredients=False):
        grams = dict(view.get("suggested_grams", {}))
        ranges = dict(view.get("portion_ranges", {}))
        remaining = []
        changed = False
        for row in view.get("missing_items", ()):
            key = re.fullmatch(r"(d\d+)(-p\d+)?", row["key"])
            if not key or not row.get("name_en") or row["name"] == RICE_PREPARATION_UNKNOWN:
                remaining.append(row)
                continue
            seen = VisibleFood(english=row["name_en"], chinese=row["name"],
                               low_g=row.get("low_g", 0), high_g=row.get("high_g", 0))
            food_id = match_visible(seen, foods)
            mixed_dressing = mixed_soy_ginger_sauce(seen.english, seen.chinese)
            if ingredients and key[2] and (food_id or mixed_dressing):
                ingredient_groups.setdefault(key[1], set()).add(food_id or "dressing")
            # Only newly understood preparations are safe to add automatically.
            # E.g. the plain/oiled rice question still needs its explicit answer.
            if food_id in {"boiled-chicken", "white-rice", "fdc-2707132", "fdc-2709593", "tfda-P0200601"}:
                amount, bounds = portion_guess(foods[food_id], seen)
                if bounds and grams.get(food_id, 0) + amount <= 3000:
                    if food_id not in grams:
                        ranges[food_id] = bounds
                    elif ranges.get(food_id):
                        ranges[food_id] = [min(3000, a + b) for a, b in zip(ranges[food_id], bounds)]
                    grams[food_id] = grams.get(food_id, 0) + amount
                    changed = True
                    continue
            if row.get("alternatives") and mixed_dressing:
                row = {**row, "alternatives": []}
                changed = True
            remaining.append(row)
        if not changed:
            return view
        update = {**view, "suggested_grams": grams, "portion_ranges": ranges, "missing_items": remaining,
                  "alternatives": list(dict.fromkeys(k for row in remaining for k in row.get("alternatives", [])))}
        for suffix in ("", "_en"):
            names = list(dict.fromkeys(row.get("name" + suffix) or row["name"] for row in remaining))
            update["unmatched_foods" + suffix] = names
            update["unmatched" + suffix] = list(dict.fromkeys([*view.get("uncertain_items" + suffix, []), *names]))
        return update

    updated = {name: rematch(view, ingredients=name == "按配料") for name, view in variants.items()}
    whole = variants.get("整道菜", original)
    unresolved_wholes = {row["key"] for row in whole.get("missing_items", ())}
    mixed_chicken = ("boiled-chicken" in whole.get("suggested_grams", {})
                     and any(index not in unresolved_wholes and "boiled-chicken" in group and len(group) > 1
                             for index, group in ingredient_groups.items()))
    if mixed_chicken:
        # The v2 whole view combined the weight of the meat with its sides.
        # Group-specific rows survive only in the ingredient view.
        current = updated["按配料"]
        updated = {}
    else:
        current = next(iter(updated.values())) if updated else rematch(original)
        if all(updated[n] is v for n, v in variants.items()) and (variants or current is original):
            return draft
    return {**draft, "variants": updated, "input": {**original, **current, "photo_resolution_version": 3}}


def reviewable_photo(draft):
    """Repair older pending tray estimates from their stored components, without another photo call."""
    original = draft["input"]
    if original.get("method") != "photo" or original.get("photo_resolution_version", 0) >= 3:
        return draft
    if original.get("photo_resolution_version") == 2:
        return _recover_bilingual_components(draft)
    variants = draft.get("variants", {})
    whole = variants.get("整道菜", original)
    ingredients = variants.get("按配料", {})
    solids = whole.get("suggested_grams", {})
    parts = ingredients.get("suggested_grams", {})
    chicken_plate = bool(CHICKEN_RICE_PLATES.intersection(solids))
    embedded_soup = chicken_plate and parts.get("fdc-2707132", 0) > solids.get("fdc-2707132", 0)
    plate_in_rice = ({k for k in CHICKEN_RICE_PLATES.intersection(parts) if parts[k] != solids.get(k)}
                     if chicken_plate else set())

    def repaired(view, remove_plates=()):
        rows = view.get("missing_items")
        if rows is None:
            rows = [{"name": name, "key": f"legacy-{i}"} for i, name in enumerate(view.get("unmatched_foods", []))]
        changes = []
        changed = bool(remove_plates)
        for row in rows:
            if sauce := GREENS_WITH_DRESSING.fullmatch(row["name"]):
                changes.extend(dressing_rows(row["key"], sauce[1]))
                changed = True
            elif row["name"] in {"黄瓜片", "黃瓜片", "青瓜片", "鲜黄瓜片"}:
                changes.append({**row, "alternatives": ["fdc-2709784"]})
                changed = True
            else:
                changes.append(row)
        if not changed:
            return view
        grams = dict(view.get("suggested_grams", {}))
        ranges = dict(view.get("portion_ranges", {}))
        for key in sorted(remove_plates):
            grams.pop(key)
            low, high = ranges.pop(key, None) or (0, 0)
            changes.append({"key": "legacy-rice-" + key, "name": RICE_PREPARATION_UNKNOWN,
                            "alternatives": ["white-rice", "fdc-2708407"],
                            "low_g": low, "high_g": high, "replace_food_ids": []})
        names = list(dict.fromkeys(r["name"] for r in changes))
        return {**view, "suggested_grams": grams, "portion_ranges": ranges, "missing_items": changes,
                "unmatched_foods": names, "unmatched": list(dict.fromkeys([*view.get("uncertain_items", []), *names])),
                "alternatives": list(dict.fromkeys(k for r in changes for k in r.get("alternatives", [])))}

    if embedded_soup:
        updated = {**original, **repaired(ingredients, plate_in_rice)}
        updated["portion_note"] = "鸡饭和汤按各自的份量分别查表，请核对盘中的米饭。"
        return {**draft, "input": {**updated, "photo_resolution_version": 2}, "variants": {}}
    modes = {name: repaired(view, plate_in_rice if name == "按配料" else ()) for name, view in variants.items()}
    current = next(iter(modes.values())) if modes else repaired(original)
    if all(modes[n] is view for n, view in variants.items()) and (variants or current is original):
        return draft
    return {**draft, "variants": modes, "input": {**original, **current, "photo_resolution_version": 2}}


def prepare_photo(photo):
    if not photo or len(photo) > 8 * 1024 * 1024:
        raise ValueError("请选择一张不超过 8 MB 的 JPG 或 PNG 照片。")
    try:
        with Image.open(io.BytesIO(photo)) as original:
            if original.format not in {"JPEG", "PNG"} or original.width * original.height > 25_000_000:
                raise ValueError("请使用不超过 2500 万像素的 JPG 或 PNG 照片。")
            prepared = ImageOps.exif_transpose(original).convert("RGB")
            prepared.thumbnail((1200, 1200))
            encoded = io.BytesIO()
            prepared.save(encoded, format="JPEG", quality=82)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("图片无法读取，请重新选择 JPG 或 PNG。") from exc
    return encoded.getvalue()


def identify_photo(jpeg, filename, foods, *, api_key, ui_lang="zh", portion_hint=""):
    from langchain_openai import ChatOpenAI
    from langsmith import tracing_context

    if not api_key or not api_key.strip():
        raise ValueError("Photo recognition requires a configured API key")
    language = "en" if ui_lang == "en" else "zh"

    instructions = (
        "Identify plated foods from ANY cuisine in English and Chinese for a searchable nutrition database. "
        "Use short, familiar food names such as 蒸米饭 or 白切鸡. Name the main food as well as toppings. "
        "Give a common dish name (e.g. burrito bowl), plus recognizable components separately. Group visible "
        "toppings with their dish. Count a separate side, e.g. chips alongside a bowl, as its own dish, "
        "even in the same container. Exclude the separate side's weight from the main dish. "
        "A bowl of broth beside chicken rice is a separate dish. Rice within chicken rice is rice alone: "
        "say plain, cooked with fat, or preparation unknown; do not give it the full chicken-rice dish name. "
        "Do not repeat components as separate dishes. "
        "Use generic names when the image cannot distinguish the variety, e.g. shredded cheese or cooked meat chunks. "
        "Brand logos do not establish recipe, market, size or meat type. "
        "Estimate edible mass as a plausible low/high gram range, for the WHOLE dish and separately for each "
        "visible component. Use relative area, depth, item counts, the container and any diner-supplied scale. "
        "Widen ranges when scale/depth is unclear. Use 0,0 if there is no defensible estimate. "
        "Estimate what is served, before the diner adjusts how much they ate. Never output nutrient values. "
        "Do not invent hidden oil/fillings or label weights. "
        "Use natural, concise Chinese for portion_note and uncertain_items. "
        "Translate them into idiomatic English in portion_note_en and uncertain_items_en. "
        "Give only notes that affect portion size or identification; omit unnecessary notes."
    )
    model = ChatOpenAI(model=PHOTO_MODEL, api_key=api_key, base_url="https://api.openai.com/v1",
                       use_responses_api=True, store=False, max_tokens=2000, reasoning_effort="minimal",
                       timeout=45, max_retries=0)
    reader = model.with_structured_output(BilingualMealPhoto, method="json_schema", strict=True, include_raw=True)
    data = base64.b64encode(jpeg).decode("ascii")
    task = ("Identify the meal and estimate each portion." if language == "en" else "请辨认餐食并估算份量。")
    if portion_hint:
        task += "\nSize reference: " + portion_hint[:150]
    with tracing_context(enabled=False):
        response = reader.invoke([
            ("system", instructions),
            ("human", [{"type": "text", "text": task},
                       {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}}]),
        ])
    result = response["parsed"]
    if not isinstance(result, MealPhoto):
        raise ValueError("模型未返回可核对的菜名，可重新选择照片或按菜名查表。")
    draft = resolve_photo(result, foods, filename)
    draft["input"].update(model=PHOTO_MODEL, ui_lang=language, portion_hint=portion_hint[:150])
    usage = response["raw"].usage_metadata
    if usage:
        draft["input"]["token_usage"] = {
            field: usage[field] for field in ("input_tokens", "output_tokens", "total_tokens")
        }
    return draft
