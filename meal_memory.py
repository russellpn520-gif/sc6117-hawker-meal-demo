"""Reuse only this diary's confirmed, complete plate portions; each repeat starts a new draft."""
import json
from contextlib import closing

from catalog import normalize
from meals import coverage_status, make_draft, open_db


def recent_complete(db_path):
    with closing(open_db(db_path)) as db:
        recent = db.execute("SELECT input, items FROM meals ORDER BY confirmed_at DESC, id DESC LIMIT 120")
        for raw, snapshot in recent:
            source, items = json.loads(raw), json.loads(snapshot)
            if source.get("label") or coverage_status({"input": source, "items": items}) != "complete":
                continue
            yield source


def usual_meals(foods, db_path=None):
    patterns = {}
    for source in recent_complete(db_path):
        # Old rows without plate weights can contain post-meal leftovers only.
        grams = source.get("served_grams")
        if not isinstance(grams, dict) or not grams or any(
            key not in foods or type(value) is not int or not 1 <= value <= 3000 for key, value in grams.items()
        ):
            continue
        signature = tuple(sorted(grams))
        patterns.setdefault(signature, grams)
        if len(patterns) == 6:
            break
    return list(patterns.values())


def _names(entry):
    names = {normalize(entry.get(key) or "") for key in ("name", "name_en")}
    return names - {"", "food", "dish", "unidentified food", "unknown", "unknown food", "食物", "未知", "未识别食物"}


def suggest_corrections(draft, foods, db_path):
    """Move a previously confirmed match to the front; still require an explicit tap."""
    if draft["input"].get("method") != "photo":
        return False
    views = [draft["input"], *(draft.get("variants") or {}).values()]
    rows = [(scope, row) for view in views for field, scope in
            (("main_dishes", "whole_dish"), ("missing_items", "ingredient")) for row in view.get(field, [])]
    if not rows:
        return False
    choices = {}
    for source in recent_complete(db_path):
        for decision in source.get("coverage_decisions", []):
            for name in _names(decision):
                choices.setdefault((decision.get("scope", "ingredient"), name), set()).add(decision.get("food_id"))
    suggested = False
    for scope, row in rows:
        matches = set().union(*(choices.get((scope, name), set()) for name in _names(row)))
        if len(matches) == 1:
            key = next(iter(matches))
            if key in foods:
                row["alternatives"] = list(dict.fromkeys([key, *row.get("alternatives", [])]))
                row["remembered_id"] = key
                suggested = True
    return suggested


def start_repeat(served):
    return {**make_draft("repeat", "Repeat confirmed meal", dict(served), []), "status": "ready"}


def usual_meals_ui(db_path):
    import streamlit as st
    from catalog import load_foods
    from i18n import food_name, tr
    from meals import create_pending

    foods = load_foods()
    options = usual_meals(foods, db_path)
    if not options:
        return
    with st.expander(tr("再吃上次那餐", "Repeat a previous meal")):
        st.caption(tr("沿用你上次核对过的菜名和上桌份量。这次吃了多少，饭后再确认。",
                      "Start from the foods and served portions you last confirmed. Adjust this meal before logging."))
        for i, grams in enumerate(options):
            label = " · ".join(f"{food_name(foods[key])} {amount} g" for key, amount in grams.items())
            if st.button(label, key=f"repeat-confirmed-{i}", width="stretch"):
                draft = start_repeat(grams)
                if create_pending(draft, db_path=db_path):
                    st.session_state.active_draft = draft["id"]
                    st.session_state.pop("receipt", None)
                    st.rerun()
