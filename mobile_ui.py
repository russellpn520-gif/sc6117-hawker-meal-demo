"""Compact, mobile-first presentation for the meal diary."""

from datetime import datetime

import streamlit as st

from i18n import tr, food_name
from meals import SG_TIME, coverage_status, load_foods, total_nutrients
from planning import span


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
      .st-key-meal_header h1 {margin: 0; padding: 0; white-space: nowrap;}
      .st-key-meal_header .st-key-ui_language_control {width: max-content; flex: none;}
      .st-key-meal_header .st-key-ui_language_control button {font-size: .84rem;}
      [class*="st-key-food_hits_"] .stButton button {
        justify-content: flex-start; text-align: start; white-space: normal; height: auto;
        min-height: 44px; padding-block: .55rem;
      }
      [class*="st-key-food_hits_"] .stButton button p {text-align: start; overflow-wrap: anywhere;}
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


def day_strip(today, plan, eaten, meal_count, partial_count=0, legacy_count=0):
    low, high = plan.kcal
    kcal = eaten["kcal"]
    protein = eaten["protein_g"]
    note = coverage_note(partial_count, legacy_count)
    if not meal_count:
        summary = tr(f"今日参考目标 {span(plan.kcal)} kcal", f"Today's energy target · {span(plan.kcal)} kcal")
        detail = tr(f"蛋白质目标 {plan.protein_g} g", f"Protein target · {plan.protein_g} g")
    elif note:
        summary = tr(f"已记小计约 {kcal:.0f} kcal · 蛋白质 {protein:.1f} g",
                     f"Logged subtotal · {kcal:.0f} kcal and {protein:.1f} g protein")
        detail = note
    elif kcal < low:
        remaining = span((low - kcal, high - kcal))
        summary = tr(f"今天还余约 {remaining} kcal", f"About {remaining} kcal left today")
    elif kcal <= high:
        summary = tr("今日已在热量参考范围内", "Within today's energy target")
    else:
        summary = tr(f"今日已记 {kcal:.0f} kcal，参考范围 {span(plan.kcal)} kcal", f"{kcal:.0f} kcal logged · Target {span(plan.kcal)} kcal")
    if meal_count and not note:
        left = plan.protein_g - protein
        detail = (tr(f"蛋白质还差 {left:.1f} g", f"{left:.1f} g protein left") if left > 0
                  else tr("蛋白质已达今日目标", "Protein target reached"))
    with st.container(key="day_strip"):
        st.markdown(tr(f"**{today.month} 月 {today.day} 日 · {plan.label}**", f"**{today:%d %b} · {'Training day' if plan.training else 'Rest day'}**"))
        st.write(summary)
        st.caption(detail)
        st.button(tr("调整训练安排", "Adjust training"), on_click=_open_training, key="home_training")


def saved_receipt(record, *, just_saved):
    status = coverage_status(record)
    if status == "complete":
        title = tr("这餐已记入日记", "Meal added to diary") if just_saved else tr("最近一餐", "Last meal")
    else:
        title = tr("这餐已记录的小计", "Logged meal subtotal")
    st.markdown(f"**{title}**")
    names = tr("、", ", ").join(_record_name(item) for item in record.get("items", [])[:2])
    totals = record["totals"]
    values = tr(f"约 {totals['kcal']:.0f} kcal · 蛋白质 {totals['protein_g']:.1f} g",
                f"About {totals['kcal']:.0f} kcal · {totals['protein_g']:.1f} g protein")
    st.text(" · ".join(filter(None, (names, values))))
    if status == "partial" and (missing := record["input"].get("unmatched_foods")):
        st.caption(tr("未计入：", "Not counted: ") + tr("、".join(missing), ", ".join(record["input"].get("unmatched_foods_en") or missing)))


def _record_name(item):
    if item.get("source_code") == "package-label":
        return item.get("name") or tr("包装食品", "Packaged food")
    if st.session_state.get("ui_lang") == "en":
        food = load_foods().get(item.get("food_id"))
        if food:
            return food_name(food)
        return item.get("source_name") or item["name"]
    return item["name"]


def meal_history(records, day=None):
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
    for record, status in zip(records, statuses):
        items = record["items"]
        if not items:
            continue
        title = tr("、", ", ").join(_record_name(item) for item in items[:2])
        if len(items) > 2:
            title += tr(f" 等 {len(items)} 项", f" + {len(items) - 2} more")
        original = record["input"]
        if status == "partial":
            title += tr("（部分记录）", " (partial)")
        elif status == "legacy_review":
            title += tr("（旧记录待核对）", " (older entry to review)")
        stamp = (datetime.fromisoformat(original["captured_at"]).astimezone(SG_TIME)
                 if original.get("captured_at") else record["at"])
        with st.expander(tr(f"{stamp:%H:%M}　{title}　·　约 {record['totals']['kcal']:.0f} kcal", f"{stamp:%H:%M} · {title} · About {record['totals']['kcal']:.0f} kcal")):
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
