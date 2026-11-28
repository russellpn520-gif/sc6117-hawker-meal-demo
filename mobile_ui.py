"""Compact, mobile-first presentation for the meal diary."""

from datetime import datetime, timedelta
from html import escape

import streamlit as st

from i18n import tr, food_name
from meals import SG_TIME, coverage_status, load_foods, meal_thumbnail, recent_activity, total_nutrients
from meal_targets import daily_hint, meal_target
from planning import THEMES, span


def apply_mobile_style():
    st.html("""
    <style>
      :root {
        --meal-green: #216650;
        --meal-selected: #285e4b;
        --meal-focus: #5a9874;
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
      .st-key-hawker_drinks {flex-wrap: wrap; gap: .4rem .45rem;}
      .st-key-hawker_drinks .stButton button {
        min-height: 44px; max-width: 100%; padding: .4rem .8rem;
        border: 1px solid #6f927a; border-radius: 2rem;
        color: inherit; background-color: rgba(114, 157, 119, .12);
      }
      .st-key-hawker_drinks .stButton button:is(:hover,:active,:focus-visible):not(:disabled) {
        color: inherit; border-color: #518766; background-color: rgba(114, 157, 119, .23);
      }
      .st-key-hawker_drinks .stButton button:disabled {color: inherit; border-style: dashed; opacity: .8;}
      .st-key-hawker_drinks .stButton button p {color: inherit; overflow-wrap: anywhere;}
      .stMain button[kind="primary"]:not(:disabled),
      .stMain [data-testid="stBaseButton-primaryFormSubmit"]:not(:disabled) {
        border-color: var(--meal-green);
        background: var(--meal-green);
        color: white;
      }
      .stMain [role="radiogroup"] button[aria-checked="true"],
      .stMain .stButtonGroup [role="radiogroup"] [role="radio"][data-selected]:not([data-disabled]),
      .stMain [data-testid="stBaseButton-segmented_controlActive"] {
        border-color: var(--meal-selected);
        background: var(--meal-selected);
        color: white;
      }
      .stMain .stMultiSelect [data-tag]:not([aria-disabled="true"]) {
        background-color: var(--meal-green);
        color: #fff;
      }
      .stMain :is(.stMultiSelect, .stSelectbox) [data-focus-within]:not([data-invalid]),
      .stMain .stTextInput [data-baseweb="input"]:focus-within {
        border-color: #538971;
        outline: 2px solid #64a48a;
        outline-offset: 1px;
      }
      .stMain .stButtonGroup [role="radio"]:not(:disabled):is(:hover, :active) {
        border-color: #538971;
      }
      .stMain .stButtonGroup [role="radio"]:not([data-selected], [data-disabled]):is([data-hovered], [data-pressed]) {
        border-color: #538971;
        background-color: rgba(100, 151, 121, .16);
        color: inherit;
      }
      .stMain button:focus-visible, .stMain summary:focus-visible {
        outline: 3px solid var(--meal-focus);
        outline-offset: 2px;
      }
      .st-key-day_strip {
        border: 1px solid rgba(106, 143, 113, .38);
        border-radius: .85rem;
        background: rgba(113, 156, 110, .10);
        padding: .72rem .85rem;
        gap: .35rem;
      }
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
      .meal-meter-line .meal-label {font-size: .88rem; margin-inline-end: auto;}
      .meal-meter-line strong {font-size: 1.18rem; line-height: 1.15;}
      .meal-meter-line small {font-size: .78rem; color: inherit; opacity: .83;}
      .meal-track {
        height: 6px; margin-top: .3rem; border-radius: 1rem; overflow: hidden;
        background: rgba(115, 146, 123, .22);
      }
      .meal-track span {display: block; height: 100%; border-radius: inherit; background: #659779;}
      .meal-track.in-range span {background: #b59a59;}
      .meal-track.above-range span {background: #c18950;}
      .meal-track.no-target {height: 2px;}
      .meal-rhythm {display: grid; grid-template-columns: repeat(7,minmax(0,1fr)); gap: 2px; margin: .15rem 0 .35rem;
                    list-style: none; padding: 0; padding-inline-start: 0 !important;}
      .meal-rhythm li {display: grid; justify-items: center; gap: .3rem; font-size: .78rem; font-variant-numeric: tabular-nums;}
      .meal-rhythm i {box-sizing: border-box; width: .72rem; height: .72rem; border: 1px solid #779281; border-radius: 50%;}
      .meal-rhythm .logged i {background: #77a987; border-color: #577e63;}
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


def day_strip(today, plan, eaten, meal_count, partial_count=0, legacy_count=0, records=()):
    kcal, protein = eaten["kcal"], eaten["protein_g"]
    note = coverage_note(partial_count, legacy_count)
    kcal_target, protein_target = "", ""
    heading = tr("今天已记", "Logged today")
    if plan:
        kcal_target = tr(f"参考 {span(plan.kcal)}", f"Target {span(plan.kcal)}")
        protein_target = tr(f"目标 {plan.protein_g} g", f"Target {plan.protein_g} g")
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
        macros.append(_meter(name, f"{amount:.0f}", "g", amount, f"/ {goal} g" if goal else "",
                             (goal, goal) if goal else None, not note))
    with st.container(key="day_strip"):
        st.markdown(f"**{heading}**")
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
                if meal_count and not note:
                    left = max(0, plan.protein_g - protein)
                    st.caption(tr(f"蛋白质还余 {left:.1f} g", f"{left:.1f} g protein left"))
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
    values = tr(f"约 {totals['kcal']:.0f} kcal · 蛋白质 {totals['protein_g']:.1f} g",
                f"About {totals['kcal']:.0f} kcal · {totals['protein_g']:.1f} g protein")
    adjustment = _adjusted_portion(record["input"]) if just_saved else None
    if adjustment:
        values = tr(f"约 {totals['kcal']:.0f} kcal", f"About {totals['kcal']:.0f} kcal")
    st.text(" · ".join(filter(None, (names, values))))
    if adjustment:
        protein = totals["protein_g"]
        st.caption(tr(f"{adjustment}，已按实吃份量记好。这餐记入了 {protein:.1f} g 蛋白质。",
                      f"{adjustment}. Logged as eaten, with {protein:.1f} g of protein recorded for this meal."))
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
    st.caption(tr(f"蛋白质 {total['protein_g']:.1f} g · 碳水 {total['carb_g']:.1f} g · 脂肪 {total['fat_g']:.1f} g", f"Protein {total['protein_g']:.1f} g · Carbs {total['carb_g']:.1f} g · Fat {total['fat_g']:.1f} g"))
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
                continue
            weight = sum(item["confirmed_g"] for item in items)
            served = original.get("served_grams")
            if served:
                st.write(tr(f"盘中 {sum(served.values())} g · 实际计入 {weight} g", f"Served {sum(served.values())} g · Eaten {weight} g"))
            else:
                st.write(tr(f"实际计入 {weight} g", f"Eaten: {weight} g"))
            for item in items:
                st.markdown(f"{_record_name(item)} · {item['confirmed_g']} g · "
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
