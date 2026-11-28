import base64
import io
import os
import re

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from meals import make_draft


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


def portion_guess(food, seen):
    low, high = seen.low_g, seen.high_g
    if not 0 < low <= high <= 3000:
        return food.serving_g, None
    mid = (low + high) / 2
    step = 5 if mid >= 30 else 1
    return max(low, min(high, round(mid / step) * step)), [low, high]


def match_visible(seen, foods):
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
    return {"key": key, "name": seen.chinese or seen.english or "未辨认食物",
            "alternatives": [k for k in foods.photo_suggestions(seen.english, seen.chinese) if k not in exclude],
            "low_g": low, "high_g": high, "replace_food_ids": []}


def component_gap(whole, parts):
    """Check if even the highest ingredient estimates leave the dish uncovered."""
    if 0 < whole.low_g <= whole.high_g <= 3000 and all(0 < p.low_g <= p.high_g <= 3000 for _, p in parts):
        return sum(p.high_g for _, p in parts) < whole.low_g
    # With just a single topping and no scale we cannot establish coverage.
    return len(parts) == 1


def resolve_photo(result, foods, filename):
    groups = []
    for dish in result.dishes[:20]:
        whole_key = match_visible(dish.whole, foods)
        parts = []
        for part in dish.parts[:25]:
            key = match_visible(part, foods)
            if key and key == whole_key and len(dish.parts) > 1:
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
        groups.append(((whole_key, dish.whole), parts))

    def variant(by_parts):
        grams, ranges, missing = {}, {}, []
        for index, (whole, parts) in enumerate(groups):
            using_parts = by_parts and bool(parts)
            items = parts if using_parts else [whole]
            exclude = {whole[0]} if using_parts else set()
            if using_parts and not whole[0]:
                exclude.update(foods.photo_suggestions(whole[1].english, whole[1].chinese))
            for subindex, (key, seen) in enumerate(items):
                item_key = f"d{index}-p{subindex}" if using_parts else f"d{index}"
                if not key:
                    missing.append(missing_item(item_key, seen, foods, exclude))
                    continue
                amount, bounds = portion_guess(foods[key], seen)
                sum_g = grams.get(key, 0) + amount
                if sum_g > 3000:
                    missing.append({"key": item_key, "name": f"{foods[key].name}超出份量范围",
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
            if using_parts and not same_food and component_gap(whole[1], parts):
                # Never suggest adding an entire dish on top of its ingredients.
                # The separate whole-dish view can replace all components at once.
                missing.append({"key": f"d{index}-gap", "name": f"{whole[1].chinese or whole[1].english}（未覆盖的配料）",
                                "alternatives": [], "low_g": 0, "high_g": 0, "replace_food_ids": []})
        names = list(dict.fromkeys(item["name"] for item in missing))
        alternatives = list(dict.fromkeys(k for item in missing for k in item["alternatives"]))
        return {"suggested_grams": grams, "portion_ranges": ranges, "alternatives": alternatives,
                "uncertain_items": list(result.uncertain_items), "unmatched_foods": names, "missing_items": missing,
                "unmatched": list(dict.fromkeys(u for u in [*result.uncertain_items, *names] if u))}

    whole, parts = variant(False), variant(True)
    # If the dish has no whole reference, start with the available components.
    # Retain a separate dish-level choice for correcting the whole by name.
    prefer_parts = any(key is None and any(k for k, _ in p) for (key, _), p in groups)
    variants = {"按配料": parts, "整道菜": whole} if prefer_parts else {"整道菜": whole, "按配料": parts}
    first = next(iter(variants.values()))
    draft = make_draft("photo", filename, first["suggested_grams"], first["unmatched"])
    draft["input"].update(first, portion_note=result.portion_note)
    if parts != whole:
        draft["variants"] = variants
    return draft


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


def identify_photo(jpeg, filename, foods, *, api_key=None, use_qwen=False, portion_hint=""):
    from langchain_openai import ChatOpenAI

    instructions = (
        "Identify plated foods from ANY cuisine in English and Chinese for a searchable nutrition database. "
        "Use short, familiar food names such as 蒸米饭 or 白切鸡. Name the main food as well as toppings. "
        "Give a common dish name (e.g. burrito bowl), plus recognizable components separately. Group visible "
        "toppings with their dish. Count a separate side, e.g. chips alongside a bowl, as its own dish, "
        "even in the same container. Exclude the separate side's weight from the main dish. "
        "Do not repeat components as separate dishes. "
        "Use generic names when the image cannot distinguish the variety, e.g. shredded cheese or cooked meat chunks. "
        "Brand logos do not establish recipe, market, size or meat type. "
        "Estimate edible mass as a plausible low/high gram range, for the WHOLE dish and separately for each "
        "visible component. Use relative area, depth, item counts, the container and any diner-supplied scale. "
        "Widen ranges when scale/depth is unclear. Use 0,0 if there is no defensible estimate. "
        "Estimate what is served, before the diner adjusts how much they ate. Never output nutrient values. "
        "Do not invent hidden oil/fillings or label weights. "
        "份量说明和待核对项只用自然简短的中文，例如‘可以参考餐盒大小，碗底深度看不清。’"
    )
    if use_qwen:
        model_name = "qwen4-max"
        model = ChatOpenAI(model=model_name, api_key=api_key,
                           base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                           use_responses_api=False, extra_body={"enable_thinking": False},
                           timeout=60, max_retries=0)
    else:
        model_name = os.environ.get("TRACK3_MODEL") or "gpt-5.4-mini"
        model = ChatOpenAI(model=model_name, api_key=api_key, use_responses_api=True,
                           timeout=35, max_retries=0, store=False)
    reader = model.with_structured_output(MealPhoto, method="json_schema", strict=True, include_raw=True)
    data = base64.b64encode(jpeg).decode("ascii")
    response = reader.invoke([
        ("system", instructions),
        ("human", [{"type": "text", "text": "辨认这餐及盘中份量。用户提供的大小参照：" + (portion_hint[:150] or "无")},
                   {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}}]),
    ])
    result = response["parsed"]
    if not isinstance(result, MealPhoto):
        raise ValueError("模型未返回可核对的菜名，可重新选择照片或按菜名查表。")
    draft = resolve_photo(result, foods, filename)
    draft["input"].update(model=model_name, portion_hint=portion_hint[:150])
    usage = response["raw"].usage_metadata
    if usage:
        draft["input"]["token_usage"] = {
            field: usage[field] for field in ("input_tokens", "output_tokens", "total_tokens")
        }
    return draft
