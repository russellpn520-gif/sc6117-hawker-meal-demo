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
    lang = st.session_state.ui_language_control
    st.session_state.ui_lang = lang
    st.query_params["lang"] = lang


def language_switch():
    requested = st.query_params.get("lang")
    explicit = requested if requested in LANGUAGES else None
    saved = _preference(key="language_cache", data={"selected": explicit}, default={"language": None},
                        on_language_change=lambda: None).language
    lang = explicit or (saved if saved in LANGUAGES else st.session_state.get("ui_lang", "zh"))
    st.session_state.ui_lang = lang
    if st.session_state.get("ui_language_control") != lang:
        st.session_state.ui_language_control = lang
    st.segmented_control("Language / 语言", list(LANGUAGES), format_func=LANGUAGES.get, required=True,
                         key="ui_language_control", on_change=_choose_language, label_visibility="collapsed")


def food_name(food):
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
