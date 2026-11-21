import base64
import io
import os
import re

from langchain_openai import ChatOpenAI
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
    portion_note: str = Field(description="One short Chinese sentence describing visible size cues and limits")


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


def resolve_photo(result, foods, filename):
    groups = []
    for dish in result.dishes[:20]:
        whole_key = match_visible(dish.whole, foods)
        parts = [(match_visible(p, foods), p) for p in dish.parts[:25]]
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
        whole = [(whole_key, dish.whole)]
        groups.append((whole, parts))

    def variant(by_parts):
        grams, ranges, unknown = {}, {}, list(result.uncertain_items)
        alternatives = []
        for whole, parts in groups:
            items = parts if parts and (by_parts or not whole[0][0]) and any(k for k, _ in parts) else whole
            for key, seen in items:
                if not key:
                    unknown.append(seen.chinese or seen.english)
                    alternatives.extend(foods.search(seen.english, 3))
                    alternatives.extend(foods.search(seen.chinese, 3))
                    continue
                amount, bounds = portion_guess(foods[key], seen)
                sum_g = grams.get(key, 0) + amount
                if sum_g > 3000:
                    unknown.append(f"{foods[key].name}合计超过 3000 g，请核对份量")
                    continue
                if key not in grams:
                    ranges[key] = bounds
                elif bounds and ranges[key]:
                    ranges[key] = [a + b for a, b in zip(ranges[key], bounds)]
                else:
                    ranges[key] = None
                grams[key] = sum_g
        return {"suggested_grams": grams, "portion_ranges": ranges, "alternatives": list(dict.fromkeys(alternatives)),
                "unmatched": list(dict.fromkeys(u for u in unknown if u))}

    whole, parts = variant(False), variant(True)
    draft = make_draft("photo", filename, whole["suggested_grams"], whole["unmatched"])
    draft["input"].update(whole, portion_note=result.portion_note)
    if parts != whole:
        draft["variants"] = {"整道菜": whole, "按配料": parts}
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
    instructions = (
        "Identify plated foods from ANY cuisine in English and Chinese for a searchable nutrition database. "
        "Give a common dish name (e.g. burrito bowl), plus recognizable components separately. Group visible "
        "toppings with their dish. Count a separate side, e.g. chips alongside a bowl, as its own dish, "
        "even in the same container. Do not repeat components as separate dishes. "
        "Use generic names; brand logos do not establish recipe, market, size or meat type. "
        "Estimate edible mass as a plausible low/high gram range, for the WHOLE dish and separately for each "
        "visible component. Use relative area, depth, item counts, the container and any diner-supplied scale. "
        "Widen ranges when scale/depth is unclear. Use 0,0 if there is no defensible estimate. "
        "Estimate what is served, before the diner adjusts how much they ate. Never output nutrient values. "
        "Do not invent hidden oil/fillings or label weights. Flag material uncertainty concisely in Chinese."
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
        ("human", [{"type": "text", "text": "Identify the meal and portions. Diner's optional size reference: "
                                            + (portion_hint[:150] or "none")},
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
