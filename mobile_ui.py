"""Compact, mobile-first presentation for the meal diary."""

from datetime import datetime, timedelta
from html import escape

import streamlit as st

from health_ui import energy_ledger, sync_button
from i18n import tr, food_name
from meals import SG_TIME, coverage_status, delete_meal, load_foods, meal_thumbnail, recent_activity, total_nutrients
from meal_targets import daily_hint, meal_target
from planning import THEMES, span


def apply_mobile_style():
    st.html("""
    <style>
      :root {
        --meal-cta: #D96B38;
        --meal-card: var(--st-secondary-background-color, light-dark(#fff, #272B29));
        --meal-ink: var(--st-text-color, light-dark(#1B201E, #F6F5F1));
        --meal-edge: light-dark(#E6E4DC, #4B4F4D);
        --meal-soft: light-dark(#F3F2EE, #343937);
        --meal-selected: #1B201E;
        --meal-focus: #98613E;
      }
      .stMainBlockContainer {
        max-width: 46rem;
        padding-bottom: max(5rem, calc(env(safe-area-inset-bottom) + 4rem));
      }
      .stMain h1, .stMain h2, .stMain h3 {
        font-family: 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif;
        letter-spacing: -.025em;
        line-height: 1.3;
      }
      .stMain h1 {font-size: clamp(1.75rem, 5vw, 2.3rem);}
      .stMain h2 {font-size: 1.42rem;}
      .stMain h3 {font-size: 1.18rem;}
      .st-key-meal_header {flex-wrap: nowrap; gap: .5rem;}
      .st-key-meal_header .st-key-language_cache {display: none;}
      /* Storage components have no UI. Leave them mounted without adding flex gaps. */
      .st-key-diary_device, .st-key-pending_device {
        position: absolute; width: 0 !important; height: 0; overflow: hidden; pointer-events: none;
      }
      .st-key-meal_header h1 {margin: 0; padding: 0; white-space: nowrap;}
      .st-key-meal_header .st-key-ui_language_control {width: max-content; flex: none;}
      .st-key-meal_header .st-key-ui_language_control button {font-size: .84rem;}
      [class*="st-key-food_hits_"] .stButton button {
        justify-content: flex-start; text-align: start; white-space: normal; height: auto;
        min-height: 44px; padding-block: .55rem;
      }
      [class*="st-key-food_hits_"] .stButton button p {text-align: start; overflow-wrap: anywhere;}
      .st-key-review_header {flex-wrap: nowrap; align-items: center;}
      .st-key-review_photo {position: relative; flex: 0 0 92px; gap: 0;}
      .st-key-review_photo img {width: 92px; height: 92px; object-fit: cover; border-radius: .75rem;}
      .st-key-review_photo .stElementContainer:has(.stButton) {position: absolute; inset: 0; z-index: 1;}
      .st-key-review_photo .stButton button {width: 92px; height: 92px; background: transparent;
        border: 0; border-radius: .75rem; color: transparent;}
      .st-key-review_photo .stButton button * {color: transparent;}
      .st-key-review_photo .stButton button::after {content: ""; position: absolute; right: 5px; bottom: 5px;
        width: 21px; height: 21px; border-radius: 5px;
        background: linear-gradient(white,white) right 4px top 4px / 7px 2px,
                    linear-gradient(white,white) right 4px top 4px / 2px 7px,
                    linear-gradient(white,white) left 4px bottom 4px / 7px 2px,
                    linear-gradient(white,white) left 4px bottom 4px / 2px 7px, rgba(20,38,30,.72);
        background-repeat: no-repeat;}
      .st-key-review_photo .stButton button:is(:hover,:active) {background: rgba(0,0,0,.06);}
      .st-key-review_actions {flex: 1 1 0; min-width: 0; gap: .25rem;}
      .st-key-review_actions .stMarkdown [data-testid="stMarkdownContainer"],
      .st-key-review_summary .stMarkdown [data-testid="stMarkdownContainer"] {margin-bottom: 0;}
      .st-key-review_actions p {margin: 0;}
      .st-key-review_actions button {min-height: 44px; padding-inline: .6rem;}
      .st-key-review_summary {gap: .15rem;}
      [class*="st-key-review_row_"] {flex-wrap: nowrap; border-bottom: 1px solid rgba(119,148,127,.22);}
      [class*="st-key-review_row_"] .stElementContainer:has(.stMarkdown) {flex: 1 1 0; min-width: 0;}
      [class*="st-key-review_row_"] .stMarkdown p {margin: 0; line-height: 1.4; overflow-wrap: anywhere;}
      [class*="st-key-review_row_"] .stButton button {width: 44px; min-height: 44px; padding: 0;
        border: 0; color: inherit; background: transparent; font-size: 1.2rem;}
      :is(.stMain,[role="dialog"]) button:is([kind="primary"],[data-testid="stBaseButton-primaryFormSubmit"]):not(:disabled) {
        background:var(--meal-cta); border-color:var(--meal-cta); color:white;
      }
      :is(.stMain,[role="dialog"]) button:is([kind="primary"],[data-testid="stBaseButton-primaryFormSubmit"]) p {
        font-size:1.18rem; font-weight:700;
      }
      :is(.stMain,[role="dialog"]) button:is([kind="primary"],[data-testid="stBaseButton-primaryFormSubmit"]):hover:not(:disabled) {
        background:#C45B2A; border-color:#C45B2A;
      }
      :where(.stMain,[role="dialog"]) button[kind="secondary"] {
        background:var(--meal-soft);border-color:light-dark(#D7D5CC,#565A57);color:var(--meal-ink);
      }
      :is(.stMain,[role="dialog"]) [role="radiogroup"] button[aria-checked="true"],
      .stMain .stButtonGroup [role="radiogroup"] [role="radio"][data-selected]:not([data-disabled]),
      :is(.stMain,[role="dialog"]) [data-testid="stBaseButton-segmented_controlActive"] {
        border-color: var(--meal-selected);
        background: var(--meal-selected);
        color: white;
      }
      .stMain .stMultiSelect [data-tag]:not([aria-disabled="true"]) {
        background-color: var(--meal-selected);
        color: #fff;
      }
      .stMain :is(.stMultiSelect, .stSelectbox) [data-focus-within]:not([data-invalid]),
      .stMain .stTextInput [data-baseweb="input"]:focus-within {
        border-color: #8D684F;
        outline: 2px solid #BC9277;
        outline-offset: 1px;
      }
      .stMain .stButtonGroup [role="radio"]:not(:disabled):is(:hover, :active) {
        border-color: #8D684F;
      }
      .stMain .stButtonGroup [role="radio"]:not([data-selected], [data-disabled]):is([data-hovered], [data-pressed]) {
        border-color: #8D684F;
        background-color: rgba(164, 133, 106, .12);
        color: inherit;
      }
      .stMain button:focus-visible, .stMain summary:focus-visible {
        outline: 3px solid var(--meal-focus);
        outline-offset: 2px;
      }
      :is(.st-key-day_strip,.st-key-training_calendar,.st-key-training_focus,[class*="st-key-hawker_card_"]) {
        background:var(--meal-card);border:1px solid var(--meal-edge);border-radius:1rem;
        box-shadow:0 2px 10px rgba(18,22,20,.05);padding:.85rem;
      }
      .st-key-day_strip {gap:.35rem;}
      .st-key-training_header {flex-wrap:nowrap;justify-content:space-between;}
      .st-key-training_header h3,.focus-heading h3 {margin:0;padding:0;}
      .st-key-training_header .stElementContainer:has(.stButton) {flex:0 0 auto;}
      .st-key-training_calendar {padding:.65rem .45rem;gap:.35rem;}
      .cal-weekdays,[class*="st-key-cal_week_"] {display:grid !important;grid-template-columns:repeat(7,minmax(0,1fr));gap:2px;}
      .cal-weekdays {text-align:center;font-size:.72rem;font-weight:600;}
      [class*="st-key-cal_day_"] {min-width:0 !important;width:100% !important;}
      [class*="st-key-cal_day_"] button {width:100%;min-height:54px;padding:3px 0;border:1px solid transparent;
        background:color-mix(in srgb,var(--day-tone) 12%,var(--meal-card));color:var(--meal-ink);border-radius:.55rem;}
      [class*="st-key-cal_day_"] button p {font-size:.69rem;line-height:1.15;white-space:normal;}
      [class*="st-key-cal_day_"] button em {position:absolute;width:1px;height:1px;padding:0;overflow:hidden;
        white-space:nowrap;clip-path:inset(50%);}
      [class*="st-key-cal_day_"] button strong {font-size:.95rem;font-variant-numeric:tabular-nums;}
      [class*="st-key-cal_day_"][class*="_today"] button {border-color:var(--meal-ink);}
      [class*="st-key-cal_day_"][class*="_selected"] button {background:color-mix(in srgb,var(--day-tone) 76%,#14201B);color:#FFFFFF;}
      [class*="st-key-cal_day_"][class*="_strength"],.focus-badge.strength {--day-tone:#D96B38;}
      [class*="st-key-cal_day_"][class*="_cardio"],.focus-badge.cardio {--day-tone:#2E7CF6;}
      [class*="st-key-cal_day_"][class*="_done"] {--day-tone:#1E9B75;}
      [class*="st-key-cal_day_"][class*="_rest"] {--day-tone:#9A9E9B;}
      .focus-badge.recovery {--day-tone:#8566E3;}
      .focus-heading {display:flex;flex-wrap:wrap;align-items:center;gap:.4rem .65rem;}
      .focus-badge {padding:.25rem .55rem;border-radius:.6rem;font-size:.83rem;font-weight:600;
        background:color-mix(in srgb,var(--day-tone) 15%,var(--meal-card));color:color-mix(in srgb,var(--day-tone) 62%,var(--meal-ink));}
      .focus-exercises {list-style:none;margin:0;padding:0 !important;}
      .focus-exercises li {padding:.48rem .25rem;border-top:1px solid var(--meal-edge);font-size:.94rem;line-height:1.4;}
      .st-key-move_choices button {border-radius:1.5rem;min-height:44px;}
      .st-key-training_sources button {font-size:.86rem;text-decoration:underline;text-underline-offset:.22em;}
      .st-key-day_strip :is([data-testid="stMarkdownContainer"], [data-testid="stCaptionContainer"]) {
        margin-bottom: 0;
      }
      .st-key-day_strip p {margin: 0; line-height: 1.4;}
      .meal-meters {display: grid; gap: .75rem; margin-block: .25rem;}
      .macro-meters {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.6rem}
      .macro-meters .meal-meter-line {display:grid;gap:0}
      .macro-meters .meal-meter-line strong {font-size:1rem}
      .macro-meters .meal-meter-line small {font-size:.75rem}
      .meal-meter-line {
        display: flex; align-items: baseline; flex-wrap: wrap; column-gap: .5rem;
        font-variant-numeric: tabular-nums; line-height: 1.35;
      }
      .meal-meter-line > :not(.meal-label) {white-space:nowrap;}
      .st-key-health_heading {align-items:center;flex-wrap:nowrap;justify-content:space-between;}
      .st-key-health_heading .stElementContainer:has(.stButton) {flex:0 0 auto;}
      .meal-meter-line .meal-label {font-size: .88rem; margin-inline-end: auto;}
      .meal-meter-line strong {font-size: 1.18rem; line-height: 1.15;}
      .meal-meter-line small {font-size: .78rem; color: inherit; opacity: .83;}
      .meal-track {
        height: 6px; margin-top: .3rem; border-radius: 1rem; overflow: hidden;
        background: light-dark(rgba(27,32,30,.10),rgba(245,245,240,.16));
      }
      .meal-track span {display: block; height: 100%; border-radius: inherit; background: #D96B38;}
      .macro-meters > :nth-child(1) .meal-track span {background:#1E9B75;}
      .macro-meters > :nth-child(2) .meal-track span {background:#2E7CF6;}
      .macro-meters > :nth-child(3) .meal-track span {background:#8566E3;}
      .meal-meters > :first-child .meal-track.above-range span {background:#C88A2E;}
      .meal-track.no-target {height: 2px;}
      .meal-rhythm {display: grid; grid-template-columns: repeat(7,minmax(0,1fr)); gap: 2px; margin: .15rem 0 .35rem;
                    list-style: none; padding: 0; padding-inline-start: 0 !important;}
      .meal-rhythm li {display: grid; justify-items: center; gap: .3rem; font-size: .78rem; font-variant-numeric: tabular-nums;}
      .meal-rhythm i {box-sizing: border-box; width: .72rem; height: .72rem; border: 1px solid #779281; border-radius: 50%;}
      .meal-rhythm .logged i {background: #1E9B75; border-color: #1E9B75;}
      .meal-rhythm .is-today {font-weight: 650;}
      :is(.st-key-day_strip, .st-key-home_before, .st-key-home_pending) [data-testid="stCaptionContainer"] {
        color: inherit; opacity: .84;
      }
      .st-key-home_after [data-testid="stText"] {
        font-family: inherit; white-space: pre-wrap; overflow-wrap: anywhere;
      }
      :is(.st-key-day_strip, .st-key-mituan_panel) button[kind="tertiary"] {
        min-height: 44px; padding: .4rem .75rem;
        border: 1px solid rgba(106, 143, 113, .6);
        border-radius: .65rem; background: rgba(113, 156, 110, .09);
        color: inherit; font-weight: 550;
      }
      @media (max-width: 640px) {
        .stMainBlockContainer {padding: 4.2rem 1rem max(6rem, calc(env(safe-area-inset-bottom) + 5rem));}
        .st-key-meal_header h1 {font-size: clamp(1.45rem, 6vw, 1.85rem);}
        .stMain :is(.stButton, .stFormSubmitButton, .stButtonGroup) button {min-height: 44px;}
        [class*="-eaten-"] [role="radiogroup"] {
          display: grid;
          grid-template-columns: repeat(5, minmax(44px, 1fr));
          width: 100%; gap: 0; overflow-x: auto;
        }
        [class*="-eaten-"] [role="radio"] {
          min-height: 44px; min-width: 44px; width: 100%; padding-inline: .18rem;
          white-space: nowrap;
        }
        .stMain details > summary {min-height: 44px; align-content: center;}
        .st-key-body_measurements [data-testid="stHorizontalBlock"] {flex-direction: column; gap: .45rem;}
        .st-key-body_measurements [data-testid="stColumn"] {min-width: 100% !important;}
        :is(.st-key-daily_balance,.st-key-meal_totals) [data-testid="stHorizontalBlock"] {
          flex-direction: row; flex-wrap: nowrap; gap: .7rem;
        }
        :is(.st-key-daily_balance,.st-key-meal_totals) [data-testid="stColumn"] {
          flex: 1 1 0 !important; min-width: 0 !important; width: auto !important;
        }
        :is(.st-key-daily_balance,.st-key-meal_totals) [data-testid="stMetricValue"] {font-size: 1.35rem;}
      }
    </style>
    """)


def coverage_note(partial_count, legacy_count):
    notes = []
    if partial_count:
        notes.append(tr(f"{partial_count} 餐部分记录", f"partial meals: {partial_count}"))
    if legacy_count:
        notes.append(tr(f"{legacy_count} 餐旧记录待核对", f"older meals to check: {legacy_count}"))
    return tr("、", "; ").join(notes)


def _open_training():
    st.session_state.section = "训练安排"


def _meter(label, value, unit, current, target, bounds, complete):
    value_text = f"{value} {unit}"
    tone = "no-target"
    attrs = 'aria-hidden="true"'
    fill = 0
    if bounds and bounds[0] > 0:
        low, high = bounds
        fill = min(100, max(0, current / low * 100))
        tone = "in-range" if complete and current >= low else ""
        if complete and high is not None and current > high:
            tone = "above-range"
        attrs = (f'role="progressbar" aria-label="{escape(label)}" aria-valuemin="0" aria-valuemax="100" '
                 f'aria-valuenow="{round(fill)}" aria-valuetext="{escape(value_text + ", " + target)}"')
    reference = f' <small>{escape(target)}</small>' if target else ""
    return (f'<div><div class="meal-meter-line"><span class="meal-label">{escape(label)}</span>'
            f'<span><strong>{escape(value)}</strong> <small>{unit}</small></span>{reference}</div>'
            f'<div class="meal-track {tone}" {attrs}><span style="width:{fill:.2f}%"></span></div></div>')


def day_strip(today, plan, eaten, meal_count, partial_count=0, legacy_count=0, records=(), *, db_path=None, health=None):
    kcal, protein = eaten["kcal"], eaten["protein_g"]
    note = coverage_note(partial_count, legacy_count)
    kcal_target, protein_target = "", ""
    heading = tr("今天已记", "Logged today")
    if plan:
        kcal_target = tr(f"参考 {span(plan.kcal)}", f"Target {span(plan.kcal)}")
        protein_target = tr(f"目标 {plan.protein_g}\u00a0g", f"Target {plan.protein_g}\u00a0g")
        theme = tr(*THEMES[plan.theme if plan.training else "rest"])
        heading = tr(f"{today.month} 月 {today.day} 日 · {theme}", f"{today:%d %b} · {theme}")
        if not meal_count:
            heading += tr(" · 今日热量参考", " · Today's energy target")
    energy_meter = _meter(tr("热量", "Energy"), f"{kcal:.0f}", "kcal", kcal, kcal_target,
                          plan.kcal if plan else None, not note)
    macros = []
    for key, name in (("protein_g", tr("蛋白", "Protein")), ("carb_g", tr("碳水", "Carbs")), ("fat_g", tr("脂肪", "Fat"))):
        amount = eaten.get(key, 0)
        goal = getattr(plan, key, None)
        macros.append(_meter(name, f"{amount:.0f}", "g", amount, f"/ {goal}\u00a0g" if goal else "",
                             (goal, goal) if goal else None, not note))
    with st.container(key="day_strip"):
        with st.container(horizontal=True, gap="small", key="health_heading"):
            st.markdown(f"**{heading}**")
            sync_button(today, db_path, health)
        energy_ledger(plan, kcal, health, bool(note))
        st.html(f'<div class="meal-meters">{energy_meter}<div class="macro-meters">{"".join(macros)}</div></div>')
        if note:
            st.markdown(tr(f"以上是已记小计，含{note}。", f"Logged subtotal, including {note}."))
        elif plan and meal_count:
            low, high = plan.kcal
            if kcal < low:
                remaining = span((low - kcal, high - kcal))
                feedback = tr(f"今天还余约 {remaining} kcal", f"About {remaining} kcal left today")
            elif kcal <= high:
                feedback = tr("今天的热量已在参考范围内", "Today's energy is within your reference range")
            else:
                feedback = tr("今天吃得很扎实，下一餐照自己的胃口来。", "A hearty day. Let your appetite guide your next meal.")
            st.markdown(feedback)
            target = meal_target(plan, eaten, records)
            st.caption(tr(*daily_hint(plan, eaten, target.veg_gap, datetime.now(SG_TIME).hour)))
        if plan:
            with st.expander(tr("目标明细", "Target details")):
                if health:
                    st.caption(tr("穿戴设备的活动能量是估算值，部分设备与活动的误差会超过 20%。",
                                  "Wearable activity energy is an estimate. Errors can exceed 20% depending on the device and activity.") +
                               " [Shcherbina et al.](https://doi.org/10.3390/jpm7020003)")
                if meal_count and not note:
                    left = max(0, plan.protein_g - protein)
                    st.caption(tr(f"蛋白质还余 {left:.1f}\u00a0g", f"{left:.1f}\u00a0g protein left"))
                st.caption(tr("三大营养素按热量区间中点估算，碳水和蛋白每克 4 kcal，脂肪每克 9 kcal。训练日配比是可调整的计划参考。",
                              "Macro estimates use the midpoint of your energy range, at 4/4/9 kcal per gram of carbs, protein and fat. Workout-day splits are planning estimates."))
                st.markdown("[HPB · My Healthy Plate](https://www.healthhub.sg/well-being-and-lifestyle/food-diet-and-nutrition/plan-your-meals-with-my-healthy-plate) · [DRI · AMDR](https://www.nationalacademies.org/read/27957/chapter/5)")
                st.button(tr("调整训练安排", "Adjust training"), on_click=_open_training, key="home_training")
        else:
            st.caption(tr("个人目标可按需设置。", "You can set personal targets whenever you like."))


def _adjusted_portion(input_data):
    labels = {0: ("没吃", "none eaten"), .25: ("吃了四分之一", "a quarter eaten"),
              .5: ("吃了半份", "half eaten"), .75: ("吃了四分之三", "three quarters eaten")}
    for key, share in input_data.get("eaten_fractions", {}).items():
        if share in labels and (food := load_foods().get(key)):
            return f"{food_name(food)}{tr('，', ' · ')}{tr(*labels[share])}"
    return None


def _meal_names(items):
    names = tr("、", ", ").join(_record_name(item) for item in items[:2])
    if len(items) > 2:
        names += tr(f" 等 {len(items)} 项", f" + {len(items) - 2} more")
    return names


def meal_time(record):
    if stamp := record["input"].get("captured_at"):
        try:
            return datetime.fromisoformat(stamp).astimezone(SG_TIME)
        except (TypeError, ValueError):
            pass
    return record["at"]


def saved_receipt(record, *, just_saved, number=None):
    status = coverage_status(record)
    if status == "complete":
        title = tr("这餐已记入日记", "Meal added to diary") if just_saved else tr("最近一餐", "Last meal")
    else:
        title = tr("这餐已记录的小计", "Logged meal subtotal")
    if number:
        title = tr(f"第 {number} 餐", f"Meal {number}") + " · " + title
    st.markdown(f"**{title}**")
    names = _meal_names(record.get("items", []))
    totals = record["totals"]
    values = tr(f"约 {totals['kcal']:.0f} kcal · 蛋白质 {totals['protein_g']:.1f}\u00a0g",
                f"About {totals['kcal']:.0f} kcal · {totals['protein_g']:.1f}\u00a0g protein")
    adjustment = _adjusted_portion(record["input"]) if just_saved else None
    if adjustment:
        values = tr(f"约 {totals['kcal']:.0f} kcal", f"About {totals['kcal']:.0f} kcal")
    st.text(" · ".join(filter(None, (names, values))))
    if adjustment:
        protein = totals["protein_g"]
        st.caption(tr(f"{adjustment}，已按实吃份量记好。这餐记入了 {protein:.1f}\u00a0g 蛋白质。",
                      f"{adjustment}. Logged as eaten, with {protein:.1f}\u00a0g of protein recorded for this meal."))
    if status == "partial" and (missing := record["input"].get("unmatched_foods")):
        st.caption(tr("未计入：", "Not counted: ") + tr("、".join(missing), ", ".join(record["input"].get("unmatched_foods_en") or missing)))


def _record_name(item):
    if item.get("source_code") == "package-label":
        return item.get("name") or tr("包装食品", "Packaged food")
    food = load_foods().get(item.get("food_id"))
    if food:
        return food_name(food)
    if st.session_state.get("ui_lang") == "en":
        return item.get("source_name") or item["name"]
    return item["name"]


def diary_rhythm(today, *, db_path=None):
    logged = recent_activity(today, db_path=db_path)
    title = tr("最近 7 天", "Last 7 days")
    st.markdown(f"**{title}**")
    dots = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        active = day in logged
        state = tr("有记录", "activity logged") if active else tr("暂无记录", "no activity logged")
        label = f"{day.isoformat()} · {state}"
        text = tr("今天", "Today") if day == today else str(day.day)
        classes = ("logged " if active else "") + ("is-today" if day == today else "")
        dots.append(f'<li class="{classes}" aria-label="{label}" title="{label}"><i aria-hidden="true"></i>{text}</li>')
    st.html(f'<ol class="meal-rhythm" aria-label="{title}">{"".join(dots)}</ol>')
    st.caption(tr("记过餐或完成训练的日子会亮起。", "A green dot marks a meal or a completed workout."))


def meal_history(records, day=None, *, db_path=None):
    st.subheader(tr(f"{day:%m 月 %d 日}的记录", f"Diary · {day:%d %b}") if day else tr("今日记录", "Today's diary"))
    if not records:
        st.caption(tr("确认吃下的份量后，这餐就会出现在这里。", "Confirm a meal to see your food and portions here."))
        return
    total = total_nutrients([record["totals"] for record in records])
    statuses = [coverage_status(record) for record in records]
    note = coverage_note(statuses.count("partial"), statuses.count("legacy_review"))
    qualifier = tr(f"（含 {note}）", f" ({note})") if note else ""
    st.markdown(tr(f"**{len(records)} 餐 · 约 {total['kcal']:.0f} kcal{qualifier}**", f"**Meals: {len(records)} · About {total['kcal']:.0f} kcal{qualifier}**"))
    st.caption(tr(f"蛋白质 {total['protein_g']:.1f}\u00a0g · 碳水 {total['carb_g']:.1f}\u00a0g · 脂肪 {total['fat_g']:.1f}\u00a0g", f"Protein {total['protein_g']:.1f}\u00a0g · Carbs {total['carb_g']:.1f}\u00a0g · Fat {total['fat_g']:.1f}\u00a0g"))
    ordered = sorted(zip(records, statuses), key=lambda pair: (meal_time(pair[0]), pair[0]["id"]), reverse=True)
    for index, (record, status) in enumerate(ordered):
        items = record["items"]
        if not items:
            continue
        number = len(ordered) - index
        title = tr(f"第 {number} 餐", f"Meal {number}") + " · " + _meal_names(items)
        original = record["input"]
        if status == "partial":
            title += tr("（部分记录）", " (partial)")
        elif status == "legacy_review":
            title += tr("（旧记录待核对）", " (older entry to review)")
        stamp = (datetime.fromisoformat(original["captured_at"]).astimezone(SG_TIME)
                 if original.get("captured_at") else record["at"])
        details = st.expander(tr(f"{stamp:%H:%M}　{title}　·　约 {record['totals']['kcal']:.0f} kcal",
                                 f"{stamp:%H:%M} · {title} · About {record['totals']['kcal']:.0f} kcal"),
                              key=f"meal_history_{record['id']}", on_change="rerun")
        with details:
            if details.open and record.get("has_thumbnail") and (photo := meal_thumbnail(record["id"], db_path=db_path)):
                st.image(photo, width=240, alt=tr("这餐的照片", "Photo of this meal"))
            if original.get("method") == "label":
                from label_ui import label_history
                label_history(items[0])
                if usage := original.get("token_usage"):
                    st.caption(tr(f"标签识别 · 输入 {usage['input_tokens']}，输出 {usage['output_tokens']} tokens",
                                  f"Label scan · {usage['input_tokens']} input and {usage['output_tokens']} output tokens"))
            else:
                weight = sum(item["confirmed_g"] for item in items)
                served = original.get("served_grams")
                if served:
                    st.write(tr(f"盘中 {sum(served.values())}\u00a0g · 实际计入 {weight}\u00a0g", f"Served {sum(served.values())}\u00a0g · Eaten {weight}\u00a0g"))
                else:
                    st.write(tr(f"实际计入 {weight}\u00a0g", f"Eaten: {weight}\u00a0g"))
                for item in items:
                    st.markdown(f"{_record_name(item)} · {item['confirmed_g']}\u00a0g · "
                                + tr(f"约 {item['nutrients']['kcal']:.0f} kcal　[来源]", f"About {item['nutrients']['kcal']:.0f} kcal · [Source]")
                                + f"({item['source_url']})")
                if status == "partial" and original.get("unmatched_foods"):
                    st.caption(tr("尚未计入：", "Not counted: ") + tr("、".join(original["unmatched_foods"]), ", ".join(original.get("unmatched_foods_en") or original["unmatched_foods"])))
                elif status == "legacy_review":
                    st.caption(tr("当时未自动匹配：", "Unmatched items: ") + tr("、".join(original["unmatched_foods"]), ", ".join(original.get("unmatched_foods_en") or original["unmatched_foods"])))
                    st.caption(tr("旧版未保存逐项核对结果，以上为当时记入的食物小计。", "This older entry shows the subtotal of foods that were logged."))
                notes = original.get("uncertain_items", original.get("unmatched", []))
                if notes:
                    st.caption(tr("识别备注：", "Photo notes: ") + tr("、".join(notes), ", ".join(original.get("uncertain_items_en") or notes)))
                if usage := original.get("token_usage"):
                    with st.expander(tr("本次识别用量", "Recognition usage")):
                        st.caption(tr(f"{original.get('model', '照片识别')} · 输入 {usage['input_tokens']:,} · "
                                      f"输出 {usage['output_tokens']:,} · 合计 {usage['total_tokens']:,} tokens",
                                      f"{original.get('model', 'Photo scan')} · Input {usage['input_tokens']:,} · "
                                      f"Output {usage['output_tokens']:,} · Total {usage['total_tokens']:,} tokens"))
            if details.open:
                _delete_history_entry(record["id"], db_path)


def _delete_history_entry(meal_id, db_path):
    confirming = st.session_state.get("delete_diary_entry") == meal_id
    if not confirming:
        st.button(tr("删除这餐", "Delete meal"), key=f"delete-meal-{meal_id}",
                  on_click=st.session_state.update, args=({"delete_diary_entry": meal_id},))
        return
    st.caption(tr("删除后，当天的营养合计也会更新。", "Deleting this meal also updates the day's totals."))
    with st.container(horizontal=True):
        if st.button(tr("确认删除这餐", "Confirm deletion"), key=f"delete-confirm-{meal_id}"):
            delete_meal(meal_id, db_path)
            if (st.session_state.get("receipt") or {}).get("id") == meal_id:
                st.session_state.pop("receipt")
            st.session_state.pop("delete_diary_entry", None)
            st.rerun()
        st.button(tr("取消", "Cancel"), key=f"delete-cancel-{meal_id}",
                  on_click=st.session_state.pop, args=("delete_diary_entry", None))
