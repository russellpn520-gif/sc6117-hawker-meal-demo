"""Location choice and nearby dinner cards in the mobile coach."""

from datetime import datetime
from html import escape
from math import isfinite
from pathlib import Path
from uuid import uuid4

import streamlit as st

from coach import _today_values
from i18n import food_name, tr
from meal_plan_ui import show_booster
from meals import SG_TIME, get_profile, load_foods
from nearby_hawker import (
    LANDMARKS, NEA_SNAPSHOT_DATE, NEA_URL, SEARCH_RADIUS_M, add_nearby_draft, get_landmark,
    recommend_nearby, save_landmark,
)
from nutrition_coach import ALLERGENS, budget_cents, get_preferences
from nutrition_coach_ui import nutrition_preferences


_LOCATION = st.components.v2.component(
    "hawker_location",
    html="""<button type="button"></button><small aria-live="polite" role="status"></small>
    <style>
    button{font:600 .94rem/1.25 system-ui,sans-serif;min-height:44px;border-radius:.65rem;
    background:var(--st-secondary-background-color, #edf1e5);color:var(--st-text-color, #234634);
    border:1px solid #71927f;padding:.4rem .85rem;cursor:pointer}
    button:focus-visible{outline:3px solid #71927f;outline-offset:2px}
    small{display:block;font:.85rem/1.4 system-ui,sans-serif;margin-top:.25rem}
    small:empty{display:none}
    </style>""",
    js=Path(__file__).with_name("nearby_location.js").read_text(encoding="utf-8"),
)


def _location(radar, db_path):
    selected = get_landmark(db_path)
    captions = dict(origin=selected, button=tr("用我的位置", "Use my location"),
                    privacy=tr("只取大致位置，用完即清除。", "Use an approximate location for this panel only."),
                    working=tr("正在获取大致位置…", "Finding your approximate location…"))
    with st.container(key="hawker_heading", horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        st.markdown("### " + tr("附近食阁雷达", "Nearby hawker spots"), width="content")
        event = _LOCATION(key="hawker_location", data=captions, width="content", on_result_change=lambda: None).result
    if isinstance(event, dict):
        coords = (event.get("lat"), event.get("lon"))
        if all(type(v) in (int, float) and isfinite(v) for v in coords):
            if 1.13 <= coords[0] <= 1.49 and 103.57 <= coords[1] <= 104.12:
                radar.update(coords=tuple(round(v, 3) for v in coords), location_error=None)
            else:
                radar.update(coords=None, location_error="outside")
        else:
            radar.update(coords=None, location_error="denied")
        radar["page"] = 0

    short = {"ntu": "NTU", "nus": "NUS", "marina": tr("滨海湾", "Marina Bay"),
             "river": tr("里峇峇利", "River Valley")}
    custom = radar.get("coords")
    control = f"radar_landmarks_{st.session_state.get('ui_lang', 'zh')}_{selected}_{bool(custom)}"

    def select_landmark():
        choice = st.session_state.get(control)
        if choice in LANDMARKS:
            save_landmark(db_path, choice)
            radar.update(coords=None, page=0, location_error=None)

    st.pills(tr("或选一个地标", "Or choose a landmark"), list(LANDMARKS), format_func=short.__getitem__,
             default=None if custom else selected, key=control, required=not custom, on_change=select_landmark,
             label_visibility="collapsed")
    origin = tr(*LANDMARKS[selected]["names"])
    if radar.get("location_error") == "outside":
        description = tr(f"名单覆盖新加坡，已按{origin}推荐。", f"Singapore venues · using {origin}.")
    elif radar.get("location_error") == "denied":
        description = tr(f"暂时取不到位置，已按{origin}推荐。", f"Location unavailable. Using {origin}.")
    elif custom:
        description = tr("按大致位置计算直线距离，关闭即清除。", "Distances are straight-line from your approximate location. Closing this panel clears it.")
    else:
        description = tr(f"从{origin}出发 · 约直线距离", f"From {origin} · straight-line distances")
    return custom or LANDMARKS[selected]["coords"], description


def _distance(metres):
    if metres < 50:
        return tr("50 米内", "within 50 m")
    if metres < 1000:
        return tr(f"约 {round(metres / 10) * 10:.0f} 米", f"~{round(metres / 10) * 10:.0f} m")
    return tr(f"约 {metres / 1000:.1f} 公里", f"~{metres / 1000:.1f} km")


def _show_card(card, request_id, today, db_path):
    with st.container(key=f"hawker_card_{card['id']}", border=True, gap="xsmall"):
        centre, dish, stall, order, note, reason = (escape(tr(*card[k])) for k in ("centre", "dish", "stall", "order", "note", "reason"))
        totals = card["totals"]
        nutrition = tr(f"约 {totals['kcal']:.0f} kcal · 蛋白质 {totals['protein_g']:.1f} g",
                       f"About {totals['kcal']:.0f} kcal · {totals['protein_g']:.1f} g protein")
        st.html(f'''<div class="hawker-card">
        <p class="hawker-place">{centre} · {_distance(card["distance_m"])}</p>
        <h4>{dish}</h4><p class="hawker-reason">{reason}</p>
        <blockquote aria-label="{tr("点单口令", "Order at the stall")}">“{order}”</blockquote>
        <p class="hawker-nutrition">{nutrition}</p>
        <p class="hawker-note">{stall} · {note}</p></div>''')
        side_key = show_booster(card.get("booster"), totals, request_id)
        with st.container(key=f"hawker_actions_{card['id']}", horizontal=True, gap="xsmall"):
            st.link_button(tr("Google Maps 怎么走", "Google Maps directions"), card["maps_url"], width="stretch")
            if st.button(tr("这顿就吃这个（加入草稿）", "Add to meal draft"), key=f"radar_add_{request_id}", type="primary", width="stretch"):
                try:
                    return add_nearby_draft(db_path, card["id"], today, draft_id=request_id, side_key=side_key,
                                            evening=datetime.now(SG_TIME).hour >= 17)
                except ValueError as exc:
                    if str(exc) != "unavailable":
                        raise
                    st.info(tr("这份搭配已不符合当前偏好或休业安排，请重新选。", "This order no longer fits your preferences or the closure schedule. Choose another."))
        with st.expander(tr("参考份量与来源", "Portions and sources")):
            st.caption(tr(f"主餐碳水 {totals['carb_g']:.1f} g · 脂肪 {totals['fat_g']:.1f} g",
                          f"Main · carbs {totals['carb_g']:.1f} g · fat {totals['fat_g']:.1f} g"))
            for item in card["items"]:
                name = food_name(load_foods()[item["food_id"]])
                st.markdown(f"[{name} · {item['confirmed_g']} g]({item['source_url']})")
            if card["centre_url"] == card["venue_url"]:
                st.markdown(f"[{tr('场所与档口资料', 'Venue and stall information')}]({card['centre_url']})")
            else:
                st.markdown(f"[{tr('档口与菜品资料', 'Stall and dish information')}]({card['venue_url']}) · "
                            f"[{tr('场所资料', 'Venue information')}]({card['centre_url']})")
    return None


def nearby_dinner(state, today, db_path, budget_sgd=None, target=None):
    """Return the new pending meal id only when an order is chosen."""
    radar = state.setdefault("radar", {})
    with st.container(key="hawker_radar", gap="small"):
        coords, origin = _location(radar, db_path)
        location_bar = st.container(key="hawker_origin", horizontal=True, vertical_alignment="center", gap="small")
        prefs = get_preferences(db_path)
        preferences_label = tr("饮食偏好与预算", "Food preferences and budget")
        if not prefs or prefs.allergies is None:
            preferences_label = tr("饮食偏好 · 过敏信息未填写", "Food preferences · Allergies not provided.")
        with st.expander(preferences_label):
            if nutrition_preferences(db_path, key="radar_food_preferences"):
                radar["page"] = 0
                st.rerun()
        profile = get_profile(db_path=db_path)
        rows, eaten, partial, plan = _today_values(profile, today, db_path)
        known_balance = rows and plan and not partial
        remaining_kcal = max(0, plan.kcal[0] - eaten["kcal"]) if known_balance else None
        remaining_protein = max(0, plan.protein_g - eaten["protein_g"]) if known_balance else None
        limits = [x for x in (prefs.budget_cents if prefs else None, budget_cents(budget_sgd)) if x is not None]
        options = recommend_nearby(coords, today, preferences=prefs, remaining_kcal=remaining_kcal,
                                   remaining_protein=remaining_protein, training=bool(plan and plan.training),
                                   page=radar.get("page", 0), target=target, budget_limit=min(limits, default=None),
                                   evening=datetime.now(SG_TIME).hour >= 17)
        with location_bar:
            st.caption(origin)
            if options["total"] > 3:
                def next_set():
                    count = (options["total"] + 2) // 3
                    radar["page"] = (radar.get("page", 0) + 1) % count

                st.button(tr("换一批 ↻", "More picks ↻"), key="hawker_next", on_click=next_set)
        if limits:
            cap = min(limits) / 100
            st.caption(tr(f"预算 S${cap:.2f}，点单时请看档口菜单。", f"Budget S${cap:.2f}. Check the price at the stall."))
        if prefs and prefs.allergies:
            allergens = tr("、", ", ").join(tr(*ALLERGENS[a]) for a in prefs.allergies)
            st.write(tr(f"已按你的过敏信息筛选。请向档主确认{allergens}及共用厨具。", f"Filtered for your allergies. Ask the stall about {allergens} and shared equipment."))
        if options["closed"]:
            closed = tr("、", ", ").join(tr(*pair) for pair in options["closed"])
            st.caption(tr(f"今日清洗休业，已跳过：{closed}", f"Closed for cleaning today, skipped: {closed}"))
        if not options["schedule_covered"]:
            st.caption(tr(f"该日期超出本地清洗表，出发前请查看 [NEA 官方安排]({NEA_URL})。",
                          f"This date is outside the saved schedule. Check [NEA cleaning dates]({NEA_URL}) before heading out."))
        if not options["cards"]:
            radius = SEARCH_RADIUS_M / 1000
            st.write(tr(f"这里 {radius:g} 公里内，收录的档口暂时没有符合条件的餐食。可以换个地标，或查看上方饮食偏好。",
                        f"No matching meal among the listed stalls within {radius:g} km. Try another landmark or review your preferences above."))
        keys = radar.setdefault("draft_ids", {})
        for card in options["cards"]:
            if card["id"] not in keys:
                keys[card["id"]] = str(uuid4())
            created = _show_card(card, keys[card["id"]], today, db_path)
            if created:
                return created
        with st.expander(tr("清洗安排与营业时间", "Cleaning dates and opening hours")):
            st.write(tr(f"清洗表更新于 {NEA_SNAPSHOT_DATE}。校园食堂另有校历，出发前可在 Google Maps 查看营业时间，点单时以档口菜单为准。",
                        f"Cleaning schedule as of {NEA_SNAPSHOT_DATE}. Campus canteens have their own calendar. Check Google Maps for hours and the stall menu for prices."))
            st.markdown(f"[{tr('NEA 小贩中心清洗数据', 'NEA hawker centre cleaning data')}]({NEA_URL})")
    return None
