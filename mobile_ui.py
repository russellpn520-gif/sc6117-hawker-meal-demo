"""Compact, mobile-first presentation for the meal diary."""

import streamlit as st

from meals import total_nutrients
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
      .stMain [data-testid="stBaseButton-segmented_controlActive"] {
        border-color: var(--meal-selected);
        background: var(--meal-selected);
        color: white;
      }
      .stMain button:focus-visible, .stMain summary:focus-visible {
        outline: 3px solid #64a48a;
        outline-offset: 2px;
      }
      .st-key-day_strip, .st-key-saved_receipt {
        border-inline-start: 3px solid #538971;
        border-radius: 0 .65rem .65rem 0;
        background: rgba(100, 151, 121, .11);
        padding: .7rem .95rem;
        gap: .28rem;
      }
      .st-key-day_strip p, .st-key-saved_receipt p {margin: 0;}
      @media (max-width: 640px) {
        .stMainBlockContainer {padding: 3.5rem 1rem max(6rem, calc(env(safe-area-inset-bottom) + 5rem));}
        .stMain :is(.stButton, .stFormSubmitButton, .stButtonGroup) button {min-height: 44px;}
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


def day_strip(today, plan, eaten):
    """Keep today's training and remaining energy visible in two lines."""
    low, high = plan.kcal
    kcal = eaten["kcal"]
    if kcal < low:
        remaining = span((low - kcal, high - kcal))
        summary = f"今日剩余参考量约 {remaining} kcal"
    elif kcal <= high:
        summary = "今日已在热量参考范围内"
    else:
        summary = f"今日已记 {kcal:.0f} kcal，参考范围 {span(plan.kcal)} kcal"
    with st.container(key="day_strip"):
        st.markdown(f"**{today.month} 月 {today.day} 日 · {plan.label}**")
        st.caption(f"{summary} · 蛋白质 {eaten['protein_g']:.0f} / {plan.protein_g} g")


def saved_receipt(record, plan=None, eaten=None):
    with st.container(key="saved_receipt"):
        st.markdown("**这餐已记入日记**")
        if record is None:
            return
        totals = record["totals"]
        st.write(f"约 {totals['kcal']:.0f} kcal · 蛋白质 {totals['protein_g']:.1f} g")
        if plan and eaten is not None:
            st.caption(f"{plan.label}已记蛋白质 {eaten['protein_g']:.0f} g，今日参考量 {plan.protein_g} g。")


def meal_history(records, day=None):
    st.subheader(f"{day:%m 月 %d 日}的记录" if day else "今日记录")
    if not records:
        st.caption("确认吃下的份量后，这餐就会出现在这里。")
        return
    total = total_nutrients([record["totals"] for record in records])
    st.markdown(f"**{len(records)} 餐 · 约 {total['kcal']:.0f} kcal**")
    st.caption(f"蛋白质 {total['protein_g']:.1f} g · 碳水 {total['carb_g']:.1f} g · 脂肪 {total['fat_g']:.1f} g")
    for record in records:
        items = record["items"]
        if not items:
            continue
        title = "、".join(item["name"] for item in items[:2])
        if len(items) > 2:
            title += f" 等 {len(items)} 项"
        with st.expander(f"{record['at']:%H:%M}　{title}　·　约 {record['totals']['kcal']:.0f} kcal"):
            original = record["input"]
            weight = sum(item["confirmed_g"] for item in items)
            served = original.get("served_grams")
            if served:
                st.write(f"盘中 {sum(served.values())} g · 实际计入 {weight} g")
            else:
                st.write(f"实际计入 {weight} g")
            for item in items:
                st.markdown(f"{item['name']} · {item['confirmed_g']} g · "
                            f"约 {item['nutrients']['kcal']:.0f} kcal　[来源]({item['source_url']})")
            if original.get("unmatched"):
                st.caption("记录时待核对：" + "、".join(original["unmatched"]))
            if usage := original.get("token_usage"):
                with st.expander("本次识别用量"):
                    st.caption(f"{original.get('model', '照片识别')} · 输入 {usage['input_tokens']:,} · "
                               f"输出 {usage['output_tokens']:,} · 合计 {usage['total_tokens']:,} tokens")
