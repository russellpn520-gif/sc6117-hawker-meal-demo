import streamlit as st

from i18n import tr
from nutrition_coach import ALLERGENS, DIETS, INGREDIENTS, Preferences, budget_cents, dinner_reply, get_preferences, save_preferences


def nutrition_preferences(db_path, *, key="food_preferences"):
    prefs = get_preferences(db_path)
    lang_index = int(st.session_state.get("ui_lang") == "en")
    labels = {a: names[lang_index] for a, names in ALLERGENS.items()}
    labels["none"] = tr("没有已知过敏", "No known allergies")
    allergy_default = (list(prefs.allergies) or ["none"]) if prefs else []
    diet_keys = list(DIETS)
    with st.form(key, border=False):
        budget = st.number_input(tr("一人份晚餐食材预算（S$）", "Ingredient budget for one dinner (S$)"),
                                 min_value=0.01, step=0.5, value=prefs.budget_cents / 100 if prefs else 5.0, key=f"{key}-budget")
        diet = st.selectbox(tr("饮食偏好", "Diet preference"), diet_keys, format_func=lambda v: DIETS[v][lang_index],
                            index=diet_keys.index(prefs.diet) if prefs else 0, key=f"{key}-diet")
        allergies = st.multiselect(tr("过敏情况", "Food allergies"), ["none", *ALLERGENS], default=allergy_default,
                                   format_func=labels.__getitem__, placeholder=tr("选择过敏原或没有已知过敏", "Select allergens or no known allergies"),
                                   key=f"{key}-allergies")
        avoid = st.multiselect(tr("不想吃哪些食材（可选）", "Ingredients you dislike (optional)"), list(INGREDIENTS),
                               format_func=lambda k: INGREDIENTS[k].names[lang_index], default=list(prefs.avoid) if prefs else [],
                               key=f"{key}-avoid", placeholder=tr("选择食材", "Choose ingredients"))
        other = st.text_input(tr("其他过敏或忌口（可选）", "Other allergies or dietary restrictions (optional)"),
                              value=prefs.other_restriction if prefs else "", max_chars=200, key=f"{key}-other")
        submitted = st.form_submit_button(tr("保存饮食偏好", "Save food preferences"))
    if submitted:
        if not allergies or ("none" in allergies and len(allergies) != 1):
            st.warning(tr("请选择过敏原，或单独选择「没有已知过敏」。", "Select your allergens or choose “No known allergies” on its own."))
            return False
        save_preferences(db_path, Preferences(budget_cents(budget), diet, tuple(k for k in allergies if k != "none"),
                                              tuple(avoid), other.strip()))
        st.success(tr("已保存，将按这些条件筛选晚餐。", "Saved. Dinner suggestions will use these preferences."))
        return True
    return False


def dinner_advice(db_path, remaining_kcal=None, remaining_protein=None, shopping=False, *, key="dinner_advice", budget_sgd=None):
    if get_preferences(db_path) is None:
        nutrition_preferences(db_path, key=key + "-prefs")
    st.markdown(dinner_reply(db_path, lang=st.session_state.get("ui_lang", "zh"), remaining_kcal=remaining_kcal,
                             remaining_protein=remaining_protein, shopping=shopping, budget_sgd=budget_sgd))
