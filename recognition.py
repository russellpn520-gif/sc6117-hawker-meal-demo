import base64
import io
import os

from langchain_openai import ChatOpenAI
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from meals import make_draft


class MealPhoto(BaseModel):
    food_ids: list[str] = Field(description="Distinct matching IDs from the provided food table")
    uncertain_items: list[str] = Field(description="Unidentified or unsupported food, in Chinese")
    question: str = Field(description="One short clarification in Chinese if needed, otherwise empty")


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


def identify_photo(jpeg, filename, foods, *, api_key=None):
    menu = "\n".join(f"{food.food_id} = {food.name} ({food.source_name})" for food in foods.values())
    instructions = (
        "Help a diner identify visible foods for confirmation. Only return food IDs from the "
        "menu below. Choose either a whole-dish entry or its components for the same food, "
        "never both. Put unsupported or ambiguous items in uncertain_items. Do not infer "
        "grams or calories. The diner will confirm the portions.\n" + menu
    )
    model_name = os.environ.get("TRACK3_MODEL") or "gpt-5.4-mini"
    model = ChatOpenAI(model=model_name, api_key=api_key, use_responses_api=True, timeout=35,
                       max_retries=0, store=False)
    reader = model.with_structured_output(MealPhoto, method="json_schema", strict=True, include_raw=True)
    data = base64.b64encode(jpeg).decode("ascii")
    response = reader.invoke([
        ("system", instructions),
        ("human", [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}}]),
    ])
    result = response["parsed"]
    if not isinstance(result, MealPhoto):
        raise ValueError("模型未返回可核对的菜名，可重新选择照片或按菜名查表。")
    suggested = {food_id: foods[food_id].serving_g for food_id in result.food_ids if food_id in foods}
    unmatched = [*result.uncertain_items, *(key for key in result.food_ids if key not in foods)]
    draft = make_draft("photo", filename, suggested, unmatched)
    draft["input"].update(model=model_name, question=result.question)
    usage = response["raw"].usage_metadata
    if usage:
        draft["input"]["token_usage"] = {
            field: usage[field] for field in ("input_tokens", "output_tokens", "total_tokens")
        }
    return draft
