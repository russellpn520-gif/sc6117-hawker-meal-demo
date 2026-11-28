"""Shared next-meal controls for the coach sheet and hawker cards."""
from uuid import uuid4

import streamlit as st

from coach import _today_values
from i18n import food_name, tr
from meal_targets import fit_reason, fit_score, meal_target, vegetable_grams
from meals import get_profile, load_foods, total_nutrients
from nutrition_coach import (Preferences, add_home_draft, budget_cents, choose_booster,
                             get_preferences, plan_dinner, side_options)


def target_control(state, today, db_path):
    rows, eaten, partial, plan = _today_values(get_profile(db_path=db_path), today, db_path)
    default = meal_target(plan, eaten, rows, partial)
    stamp = (today, tuple(r["id"] for r in rows), plan)
    if stamp != state.get("meal_stamp"):
        state.update(meal_stamp=stamp, meal_choice=default.mode)
    labels = {"two": tr("还吃 2 顿", "Two meals"), "one": tr("就剩 1 顿", "One meal"),
              "snack": tr("补个加餐", "A snack")}
    choice = st.pills(tr("今天大概还吃几顿？", "How many meals are left today?"), list(labels),
                      default=state["meal_choice"], format_func=labels.__getitem__, required=True,
                      key=f"meal_count_{today}_{len(rows)}_{default.mode}_{tr('zh', 'en')}")
    state["meal_choice"] = choice
    target = meal_target(plan, eaten, rows, partial, choice)
    if target.amounts:
        n = target.amounts
        st.caption(tr(f"本顿参考约 {n['kcal']:.0f} kcal · 蛋白 {n['protein_g']:.0f} g · 碳水 {n['carb_g']:.0f} g · 脂肪 {n['fat_g']:.0f} g",
                      f"Meal guide · {n['kcal']:.0f} kcal · protein {n['protein_g']:.0f} g · carbs {n['carb_g']:.0f} g · fat {n['fat_g']:.0f} g"))
    elif partial:
        st.caption(tr("今天有部分记录，先按饮食偏好选餐。", "Some entries are partial. Picks use your food preferences."))
    return target


def show_booster(side, main, key):
    if not side:
        return None
    name = tr(*side["names"])
    n = side["totals"]
    picked = st.checkbox(tr(f"顺手加一份 · {name}", f"Add a side · {name}"), value=True, key="side_" + key)
    item = side["items"][0]
    combined = total_nutrients([main, n]) if picked else main
    st.caption(tr(f"主餐 {main['kcal']:.0f} kcal / {main['protein_g']:.1f} g 蛋白 · 加配 +{n['kcal']:.0f} kcal / +{n['protein_g']:.1f} g",
                  f"Main {main['kcal']:.0f} kcal / {main['protein_g']:.1f} g protein · side +{n['kcal']:.0f} kcal / +{n['protein_g']:.1f} g"))
    st.markdown(tr(f"**所选合计 {combined['kcal']:.0f} kcal · 蛋白质 {combined['protein_g']:.1f} g**",
                   f"**Selected total {combined['kcal']:.0f} kcal · {combined['protein_g']:.1f} g protein**"))
    st.caption(f"[{name} · {item['confirmed_g']} g]({item['source_url']})")
    return side["key"] if picked else None


def local_card(state, target, db_path, budget_sgd):
    prefs = get_preferences(db_path) or Preferences(None, "any", None)
    cap = min((c for c in (prefs.budget_cents, budget_cents(budget_sgd)) if c is not None), default=None)
    snack = target.mode == "snack"
    side_key, recipe_name, context = None, None, None
    pick = None
    if snack:
        options = side_options(prefs, cap)
        if options:
            pick = min(options, key=lambda s: fit_score(target, s["totals"], 0))
            name, items, totals = tr(*pick["names"]), pick["items"], pick["totals"]
            side_key = pick["key"]
    else:
        pick = plan_dinner(prefs, target=target, budget_sgd=budget_sgd)
        if pick:
            recipe = pick["recipe"]
            name, items, totals = tr(*recipe.names), pick["items"], pick["nutrients"]
            recipe_name = recipe.names[1]
            context = {"recipe_name": recipe_name, "budget_sgd": budget_sgd}
    if not pick:
        st.info(tr("目前收录的搭配没有符合你偏好和预算的选项。", "No listed option fits your preferences and budget."))
        return None, None
    key = recipe_name or side_key
    with st.container(border=True):
        st.markdown("**" + name + "**")
        st.caption(tr(*fit_reason(target, totals, vegetable_grams(items))))
        st.write(tr(f"约 {totals['kcal']:.0f} kcal · 蛋白 {totals['protein_g']:.1f} g · 碳水 {totals['carb_g']:.0f} g · 脂肪 {totals['fat_g']:.0f} g",
                    f"About {totals['kcal']:.0f} kcal · protein {totals['protein_g']:.1f} g · carbs {totals['carb_g']:.0f} g · fat {totals['fat_g']:.0f} g"))
        if not snack:
            st.write(tr(*recipe.prepare))
            room = cap - pick["cost_cents"] if cap is not None else None
            side = choose_booster(target, totals, prefs, room)
            side_key = show_booster(side, totals, key)
            context["side_key"] = side_key
            side_cost = side["cost_cents"] if side_key else 0
            if side_cost is None:
                st.caption(tr("加配价格以商品标签为准。", "Check the label for the price of the side."))
            cost = (pick["cost_cents"] + (side_cost or 0))/100
            st.caption(tr(f"有参考单价的食材用量估算 S${cost:.2f}。", f"Estimated cost of priced ingredients S${cost:.2f}."))
        with st.expander(tr("参考份量与来源", "Portions and sources")):
            for part in items:
                st.markdown(f"[{food_name(load_foods()[part['food_id']])} · {part['confirmed_g']} g]({part['source_url']})")
        if st.button(tr("这顿就吃这个（加入草稿）", "Add to meal draft"), type="primary", key="local_meal_add"):
            request_id = state.setdefault("local_draft_ids", {}).setdefault(key, str(uuid4()))
            try:
                return add_home_draft(db_path, recipe_name, side_key, request_id, budget_sgd), context
            except ValueError:
                st.info(tr("饮食偏好已更新，请重新选择。", "Your preferences have changed. Choose again."))
    return None, context
