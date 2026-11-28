import streamlit as st

from i18n import tr
from nutrition_coach import ALLERGENS, DIETS, INGREDIENTS, Preferences, budget_cents, get_preferences, save_preferences


def nutrition_preferences(db_path, *, key="food_preferences"):
    prefs = get_preferences(db_path)
    lang_index = int(st.session_state.get("ui_lang") == "en")
    labels = {a: names[lang_index] for a, names in ALLERGENS.items()}
    labels["none"] = tr("没有已知过敏", "No known allergies")
    allergy_default = (list(prefs.allergies) or ["none"]) if prefs and prefs.allergies is not None else []
    diet_keys = list(DIETS)
    with st.form(key, border=False):
        budget = st.number_input(tr("一人单餐预算（S$，选填）", "Meal budget per person (S$, optional)"),
                                 min_value=0.01, step=0.5,
                                 value=prefs.budget_cents / 100 if prefs and prefs.budget_cents else None,
                                 placeholder=tr("未设预算", "No budget set"), key=f"{key}-budget")
        diet = st.selectbox(tr("饮食偏好", "Diet preference"), diet_keys, format_func=lambda v: DIETS[v][lang_index],
                            index=diet_keys.index(prefs.diet) if prefs else 0, key=f"{key}-diet")
        allergies = st.multiselect(tr("过敏情况（选填）", "Food allergies (optional)"), ["none", *ALLERGENS], default=allergy_default,
                                   format_func=labels.__getitem__, placeholder=tr("未填写", "Not provided"),
                                   key=f"{key}-allergies")
        avoid = st.multiselect(tr("不想吃哪些食材（可选）", "Ingredients you dislike (optional)"), list(INGREDIENTS),
                               format_func=lambda k: INGREDIENTS[k].names[lang_index], default=list(prefs.avoid) if prefs else [],
                               key=f"{key}-avoid", placeholder=tr("选择食材", "Choose ingredients"))
        other = st.text_input(tr("其他过敏或忌口（可选）", "Other allergies or dietary restrictions (optional)"),
                              value=prefs.other_restriction if prefs else "", max_chars=200, key=f"{key}-other")
        submitted = st.form_submit_button(tr("保存饮食偏好", "Save food preferences"))
    if submitted:
        if "none" in allergies and len(allergies) != 1:
            st.warning(tr("已选过敏原时，请移除「没有已知过敏」。", "Remove “No known allergies” when listing an allergen."))
            return False
        reported = tuple(k for k in allergies if k != "none") if allergies else None
        save_preferences(db_path, Preferences(budget_cents(budget), diet, reported,
                                              tuple(avoid), other.strip()))
        st.success(tr("已保存，将按这些条件筛选餐食。", "Saved. Meal suggestions will use these preferences."))
        return True
    return False
