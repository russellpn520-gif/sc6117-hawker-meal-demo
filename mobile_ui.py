"""Compact, mobile-first presentation for the meal diary."""

from datetime import datetime

import streamlit as st

from meals import SG_TIME, total_nutrients
from planning import span


def apply_mobile_style():
    # Tint the existing Streamlit canvas so its light/dark text stays readable.
    st.html("""
    <style>
      .stApp {
        --meal-green: #216650;
        --meal-selected: #285e4b;
        background-image: linear-gradient(135deg, #b99b5920, #73a78b0b 38%, transparent 72%);
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
        outline: 3px solid #64a48a;
        outline-offset: 2px;
      }
      .st-key-day_strip, .st-key-saved_receipt {
        border-inline-start: 3px solid #538971;
        border-radius: 0 .65rem .65rem 0;
        background: rgba(100, 151, 121, .11);
        padding: .75rem .95rem 1.05rem;
        gap: .45rem;
      }
      .st-key-day_strip p, .st-key-saved_receipt p {margin: 0;}
      @media (max-width: 640px) {
        .stMainBlockContainer {padding: 3.5rem 1rem max(6rem, calc(env(safe-area-inset-bottom) + 5rem));}
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


def coverage_status(record):
    """Describe the evidence stored at confirmation without rewriting an old meal."""
    source = record.get("input", {})
    if "partial_record" in source:
        return "partial" if source["partial_record"] else "complete"
    if source.get("method") == "photo" and source.get("unmatched_foods"):
        confirmed = {item["food_id"] for item in record.get("items", [])}
        if confirmed and confirmed.issubset(source.get("suggested_grams", {})):
            return "legacy_review"
    return "complete"


def coverage_note(partial_count, legacy_count):
    notes = []
    if partial_count:
        notes.append(f"{partial_count} 餐部分记录")
    if legacy_count:
        notes.append(f"{legacy_count} 餐旧记录待核对")
    return "、".join(notes)


def day_strip(today, plan, eaten, partial_count=0, legacy_count=0):
    """Keep today's training and remaining energy visible in two lines."""
    low, high = plan.kcal
    kcal = eaten["kcal"]
    if note := coverage_note(partial_count, legacy_count):
        summary = f"今日已记约 {kcal:.0f} kcal，含 {note}"
    elif kcal < low:
        remaining = span((low - kcal, high - kcal))
        summary = f"今日剩余参考量约 {remaining} kcal"
    elif kcal <= high:
        summary = "今日已在热量参考范围内"
    else:
        summary = f"今日已记 {kcal:.0f} kcal，参考范围 {span(plan.kcal)} kcal"
    with st.container(key="day_strip"):
        st.markdown(f"**{today.month} 月 {today.day} 日 · {plan.label}**")
        st.caption(f"{summary} · 蛋白质 {eaten['protein_g']:.1f} / {plan.protein_g} g")


def saved_receipt(record):
    with st.container(key="saved_receipt"):
        status = coverage_status(record) if record else "complete"
        title, label = {
            "partial": ("已将选中的食物记入日记", "已选小计"),
            "legacy_review": ("这餐的旧记录待核对", "已记食物小计"),
            "complete": ("这餐已记入日记", "这餐"),
        }[status]
        st.markdown(f"**{title}**")
        if record is None:
            return
        totals = record["totals"]
        st.write(f"{label}约 {totals['kcal']:.0f} kcal · 蛋白质 {totals['protein_g']:.1f} g")
        if status == "partial" and (names := record["input"].get("unmatched_foods")):
            st.caption("未计入：" + "、".join(names))


def meal_history(records, day=None):
    st.subheader(f"{day:%m 月 %d 日}的记录" if day else "今日记录")
    if not records:
        st.caption("确认吃下的份量后，这餐就会出现在这里。")
        return
    total = total_nutrients([record["totals"] for record in records])
    statuses = [coverage_status(record) for record in records]
    note = coverage_note(statuses.count("partial"), statuses.count("legacy_review"))
    qualifier = f"（含 {note}）" if note else ""
    st.markdown(f"**{len(records)} 餐 · 约 {total['kcal']:.0f} kcal{qualifier}**")
    st.caption(f"蛋白质 {total['protein_g']:.1f} g · 碳水 {total['carb_g']:.1f} g · 脂肪 {total['fat_g']:.1f} g")
    for record, status in zip(records, statuses):
        items = record["items"]
        if not items:
            continue
        title = "、".join(item["name"] for item in items[:2])
        if len(items) > 2:
            title += f" 等 {len(items)} 项"
        original = record["input"]
        if status == "partial":
            title += "（部分记录）"
        elif status == "legacy_review":
            title += "（旧记录待核对）"
        stamp = (datetime.fromisoformat(original["captured_at"]).astimezone(SG_TIME)
                 if original.get("captured_at") else record["at"])
        with st.expander(f"{stamp:%H:%M}　{title}　·　约 {record['totals']['kcal']:.0f} kcal"):
            weight = sum(item["confirmed_g"] for item in items)
            served = original.get("served_grams")
            if served:
                st.write(f"盘中 {sum(served.values())} g · 实际计入 {weight} g")
            else:
                st.write(f"实际计入 {weight} g")
            for item in items:
                st.markdown(f"{item['name']} · {item['confirmed_g']} g · "
                            f"约 {item['nutrients']['kcal']:.0f} kcal　[来源]({item['source_url']})")
            if status == "partial" and original.get("unmatched_foods"):
                st.caption("尚未计入：" + "、".join(original["unmatched_foods"]))
            elif status == "legacy_review":
                st.caption("当时未自动匹配：" + "、".join(original["unmatched_foods"]))
                st.caption("旧版未保存逐项核对结果，以上为当时记入的食物小计。")
            notes = original.get("uncertain_items", original.get("unmatched", []))
            if notes:
                st.caption("识别备注：" + "、".join(notes))
            if usage := original.get("token_usage"):
                with st.expander("本次识别用量"):
                    st.caption(f"{original.get('model', '照片识别')} · 输入 {usage['input_tokens']:,} · "
                               f"输出 {usage['output_tokens']:,} · 合计 {usage['total_tokens']:,} tokens")
