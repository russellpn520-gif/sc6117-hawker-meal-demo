"""UI language is a browser preference; stored meal and plan keys stay unchanged."""

import re

import streamlit as st


LANGUAGES = {"zh": "中文", "en": "English"}
_preference = st.components.v2.component(
    "meal_language", html="<span hidden></span>", js="""
    export default function ({parentElement, data, setStateValue}) {
      const marker = parentElement.querySelector("span");
      let value = "";
      try {
        if (data.selected) localStorage.setItem("sc6117.ui.lang", data.selected);
        value = localStorage.getItem("sc6117.ui.lang") || "";
      } catch { /* Link and session preference still work. */ }
      if (marker.dataset.sent !== value) {
        marker.dataset.sent = value;
        setStateValue("language", value);
      }
    }
    """)


def tr(zh, en):
    return en if st.session_state.get("ui_lang") == "en" else zh


def _choose_language():
    lang = st.session_state.get("ui_language_control")
    if lang not in LANGUAGES:
        return
    st.session_state.ui_lang = lang
    st.query_params["lang"] = lang


def language_switch():
    requested = st.query_params.get("lang")
    explicit = requested if requested in LANGUAGES else None
    saved = _preference(key="language_cache", data={"selected": explicit}, default={"language": None},
                        on_language_change=lambda: None).language
    lang = explicit or (saved if saved in LANGUAGES else st.session_state.get("ui_lang", "zh"))
    st.session_state.ui_lang = lang
    default = lang
    if "ui_language_control" in st.session_state and st.session_state.ui_language_control != lang:
        st.session_state.ui_language_control = lang
        default = None
    st.segmented_control("Language / 语言", list(LANGUAGES), format_func=LANGUAGES.get, required=True,
                         default=default, key="ui_language_control", on_change=_choose_language, label_visibility="collapsed")


SHORT_NAMES = {
    "fdc-170894": ("原味无脂希腊酸奶", "Plain nonfat Greek yogurt"),
    "fdc-171478": ("熟鸡胸肉", "Stewed chicken breast"),
    "fdc-173424": ("水煮蛋", "Hard-boiled egg"),
    "fdc-2707416": ("熟鹰嘴豆", "Cooked chickpeas"),
    "fdc-2709699": ("烤红薯", "Baked sweet potato"),
    "fdc-168878": ("熟白米饭", "Cooked white rice"),
    "fdc-175177": ("熟罗非鱼", "Cooked tilapia"),
    "fdc-169231": ("鲜姜", "Fresh ginger"),
    "fdc-169967": ("熟西兰花", "Cooked broccoli"),
    "fdc-2707361": ("熟黑豆", "Cooked black beans"),
    "fdc-170457": ("番茄", "Tomato"),
    "fdc-2710186": ("橄榄油", "Olive oil"),
    "fdc-168917": ("熟藜麦", "Cooked quinoa"),
    "fdc-2709784": ("黄瓜", "Cucumber"),
    "fdc-172421": ("熟扁豆", "Cooked lentils"),
    "fdc-168928": ("熟小麦意面", "Cooked wheat pasta"),
    "fdc-2709593": ("熟青菜", "Cooked greens"),
    "cofid-18-374": ("烧鸭（带皮）", "Roast duck with skin"),
    "fdc-167863": ("焖猪肝", "Braised pork liver"),
    "fdc-168233": ("烤猪里脊（瘦肉）", "Lean roast pork loin"),
    "fdc-168463": ("水煮菠菜（未加盐）", "Boiled spinach, unsalted"),
    "fdc-171228": ("烤牛肩肉", "Grilled beef chuck"),
    "fdc-172389": ("炖鸡腿肉（去皮）", "Stewed skinless chicken thigh"),
    "fdc-172475": ("硬豆腐（石膏点制）", "Calcium-set firm tofu"),
    "fdc-175180": ("熟虾仁", "Cooked shrimp"),
    "fdc-2708407": ("加油白饭", "Seasoned white rice"),
    "fdc-2705933": ("烧鸡（带皮）", "Roast chicken with skin"),
    "fdc-2707132": ("清汤", "Clear broth"),
    "fdc-2710375": ("黑咖啡", "Black coffee"),
    "fdc-2705399": ("淡奶", "Evaporated milk"),
    "fdc-169655": ("白砂糖", "Sugar"),
    "fdc-173227": ("无糖红茶", "Unsweetened black tea"),
    "fdc-2705405": ("无糖豆浆", "Unsweetened soy milk"),
}


def food_name(food):
    if food.food_id in SHORT_NAMES:
        return tr(*SHORT_NAMES[food.food_id])
    if st.session_state.get("ui_lang") != "en":
        return food.name
    for name in (food.source_name, *food.aliases):
        if re.search("[A-Za-z]", name) and not re.search(r"[\u3400-\u9fff]", name):
            return name
    return food.name


def source_name(label):
    english = {"HPB · 新加坡": "Singapore HPB", "USDA · 膳食调查": "USDA · FNDDS",
               "英国 CoFID": "UK CoFID", "台湾食药署": "Taiwan FDA",
               "FAO/INFOODS · 西非": "FAO/INFOODS · West Africa",
               "新加坡餐食实测": "Singapore meal study", "GYG · 澳大利亚菜单": "GYG · Australia"}
    return tr(label, english.get(label, label))
