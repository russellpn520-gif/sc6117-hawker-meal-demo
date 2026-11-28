"""A device-specific practice diary for the no-credit chicken rice walk-through."""
import os
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from catalog import ROOT
from meals import create_pending, get_profile, list_pending, make_draft, save_profile
from nutrition_coach import get_preferences, save_preferences
from planning import Profile


PHOTO = ROOT / "assets/sample-chicken-rice.jpg"


def practice_path(diary_path, today):
    path = Path(diary_path or os.environ.get("TRACK3_DB") or ROOT / ".local/meals.sqlite3")
    return path.with_name(f"{path.stem}-practice-{today.isoformat()}.sqlite3")


def start_practice(diary_path, today, *, restart=False):
    path = practice_path(diary_path, today)
    first_visit = get_profile(db_path=path) is None
    if first_visit:
        # Fictional values live only in the practice database. The regular
        # planner schedules today and leaves tomorrow available for a move.
        save_profile(Profile(age=24, height_cm=168, weight_kg=64, activity="occasional", goal="recomp", start=today),
                     db_path=path)
    if first_visit or restart:
        if prefs := get_preferences(diary_path):
            save_preferences(path, prefs)
        for pending in list_pending(db_path=path):
            if pending["input"].get("sample"):
                return path, pending["id"]
        draft = make_draft("photo", "Sample chicken rice", {
            "fdc-2708407": 180, "fdc-2705933": 110, "fdc-2707132": 120,
        }, [])
        if first_visit:
            draft["id"] = str(uuid5(NAMESPACE_URL, f"sc6117/practice/chicken/{today}"))
        draft["input"].update(sample=True, photo_resolution_version=3,
                              portion_note="示例份量按油饭、烧鸡和清汤分别估算，蘸料另计。",
                              portion_note_en="Example portions for seasoned rice, roast chicken and broth. Dipping sauces are separate.")
        draft["status"] = "ready"
        create_pending(draft, PHOTO.read_bytes(), db_path=path)
        return path, draft["id"]
    return path, None
