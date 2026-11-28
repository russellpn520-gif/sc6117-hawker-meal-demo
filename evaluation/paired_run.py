"""Run the frozen two-arm photo benchmark. Provide the directory of preprocessed ID.jpg files.
Usage from repo root: python -m evaluation.paired_run IMAGE_DIRECTORY NEW_OR_EXISTING_LEDGER
"""
import argparse
import base64
import csv
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from langchain_openai import ChatOpenAI
from langsmith import tracing_context
from pydantic import BaseModel, Field
from api_credentials import read_api_key
from meals import load_foods, portion_items, total_nutrients
from recognition import PHOTO_MODEL, identify_photo, reviewable_photo


class Estimate(BaseModel):
    kcal: float = Field(ge=0)
    protein_g: float = Field(ge=0)
    carb_g: float = Field(ge=0)
    fat_g: float = Field(ge=0)


def direct(jpeg, hint, key):
    llm = ChatOpenAI(model=PHOTO_MODEL, api_key=key, base_url="https://api.openai.com/v1",
                     use_responses_api=True, store=False, reasoning_effort="minimal",
                     max_tokens=2000, timeout=45, max_retries=0)
    task = "Identify the meal and estimate each portion.\nSize reference: " + hint
    photo = base64.b64encode(jpeg).decode("ascii")
    with tracing_context(enabled=False):
        out = llm.with_structured_output(Estimate, strict=True, method="json_schema", include_raw=True).invoke([
            ("system", "Estimate total calories (kcal), protein, carbohydrate and fat (grams) directly for the specified food portion from the image. Return your best numerical estimate."),
            ("human", [{"type": "text", "text": task}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + photo}}]),
        ])
    return {"status": "complete", "prediction": out["parsed"].model_dump(),
            "usage": out["raw"].usage_metadata, "model": out["raw"].response_metadata.get("model_name")}


def pipeline(jpeg, hint, key, foods):
    draft = reviewable_photo(identify_photo(jpeg, "meal.jpg", foods, api_key=key, ui_lang="en", portion_hint=hint))
    data = draft["input"]
    items = portion_items(foods, data["suggested_grams"])
    missing = [m["name"] for m in data.get("missing_items", [])]
    return {"status": "no_match" if not items else "partial" if missing else "complete",
            "prediction": total_nutrients([i["nutrients"] for i in items]) if items else None,
            "missing": missing, "items": [{"food_id": i["food_id"], "g": i["confirmed_g"], "name": i["name"]} for i in items],
            "usage": data["token_usage"], "model": data["model"]}


def label_pipeline(jpeg, row, key):
    from label_scan import read_label, label_item

    data = read_label(jpeg, api_key=key, ui_lang="en")["input"]
    try:
        item = label_item(data["label"], float(row["amount"]), row["unit"])
    except ValueError:
        prediction = None
    else:
        prediction = item["nutrients"]
    return {"status": "complete" if prediction is not None else "needs_review",
            "prediction": prediction, "label": data["label"], "usage": data["token_usage"], "model": PHOTO_MODEL}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", type=Path)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--release", action="store_true", help="Use held-out meal photos and back labels")
    args = parser.parse_args()
    filename = "release_samples.csv" if args.release else "paired_samples.csv"
    records = list(csv.DictReader(Path(__file__).with_name(filename).open(encoding="utf-8")))
    if len(records) != 30 or len({r["sha256"] for r in records}) != 30 or PHOTO_MODEL != "gpt-5-mini":
        raise ValueError("Benchmark requires the frozen cohort of 30 different images and gpt-5-mini")
    key, foods = read_api_key(), load_foods()
    if not key:
        raise ValueError("No server-side API credential")
    args.ledger.mkdir(parents=True, exist_ok=True)
    manifest = args.ledger / "cohort.txt"
    # Ignore checkout-specific newlines while protecting images, portions and reference rows.
    signature = filename + " " + hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()
    if not manifest.exists() and any(args.ledger.glob("*-*.json")):
        raise ValueError("Unmarked ledger already contains calls. Score it offline; use a new directory for a new run.")
    try:
        with manifest.open("x", encoding="utf-8") as f:
            f.write(signature)
    except FileExistsError:
        if manifest.read_text(encoding="utf-8").strip() != signature:
            raise ValueError("Ledger belongs to another cohort. Choose a separate directory.")
    stop = threading.Event()
    def run(row):
        jpeg = (args.images / (row["id"] + ".jpg")).read_bytes()
        if hashlib.sha256(jpeg).hexdigest() != row["sha256"] or len(row["hint"]) > 150:
            raise ValueError("Photo or portion hint does not match the protocol")
        for arm in ("direct", "pipeline"):
            if stop.is_set():
                return
            file = args.ledger / (row["id"] + "-" + arm + ".json")
            # Exclusive reservation survives interruptions. An uncertain charge is never retried.
            try:
                with file.open("x", encoding="utf-8") as f:
                    json.dump({"status": "reserved"}, f)
            except FileExistsError:
                continue
            try:
                if arm == "direct":
                    result = direct(jpeg, row["hint"], key)
                elif args.release and row["category"] == "label":
                    result = label_pipeline(jpeg, row, key)
                else:
                    result = pipeline(jpeg, row["hint"], key, foods)
            except Exception as exc:
                result = {"status": "api_error", "error": type(exc).__name__}
                if getattr(exc, "status_code", None) in (401, 402, 403, 429):
                    stop.set()
            result["sha256"] = row["sha256"]
            file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            print(row["id"], arm, result["status"], flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(run, records))


if __name__ == "__main__":
    main()
