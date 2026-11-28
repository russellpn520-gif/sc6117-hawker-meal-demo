"""Mobile entry point for the team’s nutrition and training coach."""

from pathlib import Path

import streamlit as st

from i18n import tr
from meals import get_profile


_STYLE = Path(__file__).with_name("coach.css")
_FACE = """<span class="mituan-face" aria-hidden="true"><i class="rice"><i class="band"></i>
<i class="eyes"></i><i class="smile"></i><i class="cheeks"></i><i class="seaweed"></i></i>
<i class="arm"></i><i class="feet"></i></span>"""
_ACTIONS = {
    "today": ("今日进度", "Today’s progress"),
    "week": ("最近七天的日记", "Last seven days"),
    "training": ("我的训练", "My workout"),
    "dinner": ("晚餐建议", "Dinner ideas"),
    "move": ("训练改期", "Move a workout"),
    "shopping": ("购物清单", "Shopping list"),
}


def _close():
    state = st.session_state.get("mituan_state")
    if state:
        state.update(open=False, pending=None, preferences=False)


def _history(turns):
    return [{"role": "user", "content": turn["question"]} for turn in turns[-3:]]


def _ask(state, question, today, db_path, *, quick=None, api_key=""):
    from coach import ask_coach

    # Consume the submitted question once, even if the dialog is rerendered.
    state["pending"] = None
    state["preferences"] = False
    lang = st.session_state.get("ui_lang", "zh")
    turns = state["turns"]
    previous_meal = turns[-1]["reply"].get("meal_context") if turns and quick in (None, "shopping") else None
    with st.spinner(tr("米团在查看你的安排…", "Mituan is checking your plan…")):
        reply = ask_coach(question, today=today, db_path=db_path, lang=lang, api_key=api_key,
                          quick=quick, history=_history(turns), meal_context=previous_meal)
    turns.append({"question": tr(*_ACTIONS[quick]) if quick else question, "reply": reply, "quick": quick})
    del turns[:-6]


def _show_reply(state, today, db_path):
    if not state["turns"]:
        return
    turn = state["turns"][-1]
    reply = turn["reply"]
    st.text(turn["question"])
    st.markdown(reply["text"])
    tools_used = reply.get("tool_names", [])
    followups = []
    if turn["quick"] == "today" or ("ReadDiary" in tools_used and turn["quick"] != "week"):
        followups.append("week")
    if turn["quick"] == "training" or "ReadWorkout" in tools_used:
        followups.append("move")
    if isinstance(reply.get("meal_context"), dict) and turn["quick"] != "shopping":
        followups.append("shopping")
    for action in followups:
        if st.button(tr(*_ACTIONS[action]), type="tertiary", key=f"mituan_follow_{action}"):
            _ask(state, "", today, db_path, quick=action)
            st.rerun()
    if move := reply.get("move"):
        origin, destination = move
        if st.button(tr(f"确认改到 {destination:%m/%d}", f"Confirm move to {destination:%d %b}"),
                     key="mituan_confirm_move", type="primary"):
            from coach import confirm_move
            saved, message = confirm_move(origin, destination, today=today, db_path=db_path, expected_targets=reply.get("move_targets"),
                                          lang=st.session_state.get("ui_lang", "zh"))
            if saved and reply.get("meal_context"):
                message += tr(" 热量目标已更新。再问一次晚餐，就能看到新建议和购物清单。",
                              " Your calorie targets changed. Ask for dinner again for an updated meal and shopping list.")
            turn["reply"] = {"text": message}
            st.rerun()
    if reply.get("show_training_setup"):
        profile = get_profile(db_path=db_path)
        label = (tr("调整训练资料", "Edit workout preferences") if profile else
                 tr("建立个人计划", "Create a personal plan"))
        if st.button(label, key="mituan_setup"):
            state["training_setup"] = True
            _close()
            st.rerun()
    if reply.get("show_nutrition"):
        state["preferences"] = True
    elif turn["quick"] in {"dinner", "shopping"} or "PlanDinner" in tools_used:
        if st.button(tr("饮食偏好与预算", "Food preferences and budget"), key="mituan_open_preferences"):
            state["preferences"] = True
    if state["preferences"]:
        from nutrition_coach_ui import nutrition_preferences
        if nutrition_preferences(db_path, key="coach_food_preferences"):
            _refresh_preferences(state, today, db_path)
            st.rerun()
    if reply.get("usage"):
        with st.expander(tr("本次 API 用量", "API usage for this question")):
            usage = reply["usage"]
            st.caption(tr(f"输入 {usage.get('input_tokens', 0)} · 输出 {usage.get('output_tokens', 0)} tokens",
                          f"Input {usage.get('input_tokens', 0)} · Output {usage.get('output_tokens', 0)} tokens"))


def _refresh_preferences(state, today, db_path):
    from nutrition_coach import get_preferences

    previous = state["turns"]
    state["turns"] = [turn for turn in previous
                      if not turn["reply"].get("show_nutrition") and "PlanDinner" not in turn["reply"].get("tool_names", [])]
    state["preferences"] = False
    state["food_profile"] = get_preferences(db_path)
    if previous and previous[-1] not in state["turns"]:
        if previous[-1]["quick"] in {"dinner", "shopping"}:
            _ask(state, "", today, db_path, quick=previous[-1]["quick"])
        else:
            state["food_notice"] = True


def _panel(today, db_path, public_demo):
    from nutrition_coach import get_preferences
    from photo_access import coach_api_key

    state = st.session_state.mituan_state
    preferences = get_preferences(db_path)
    if "food_profile" in state and state["food_profile"] != preferences:
        _refresh_preferences(state, today, db_path)
    state["food_profile"] = preferences
    with st.container(key="mituan_panel"):
        greeting = tr("想看看今天的训练，还是决定晚餐吃什么？",
                      "Check your workout or pick something for dinner.")
        st.html(f'<div class="mituan-intro">{_FACE}<p>{greeting}</p></div>')
        if state.pop("food_notice", False):
            st.info(tr("饮食偏好已更新。请再问一次，以便按新偏好和这次的预算规划。",
                       "Your food preferences changed. Ask again to plan with your new preferences and budget."))
        answer = st.container()
        with st.container(key="mituan_actions", horizontal=True, gap="xsmall"):
            for action in ("today", "training", "dinner"):
                if st.button(tr(*_ACTIONS[action]), key=f"mituan_quick_{action}"):
                    _ask(state, "", today, db_path, quick=action)
        with st.form("mituan_ask", clear_on_submit=True, border=False):
            question = st.text_input(tr("问米团", "Ask Mituan"), key="mituan_question", max_chars=600,
                                     help=tr("输入的问题及近期提问会发送给 OpenAI。快捷问题不消耗 API 额度。",
                                             "Typed questions and recent questions go to OpenAI. Quick actions use no API credits."),
                                     placeholder=tr("例如：明天没空，训练怎么改？",
                                                    "e.g. Can I move my next workout?"))
            submitted = st.form_submit_button(tr("发送问题", "Send question"))
        if submitted and question.strip():
            state["pending"] = question.strip()
        if state["pending"]:
            api_key = coach_api_key(public_demo=public_demo)
            if api_key:
                _ask(state, state["pending"], today, db_path, api_key=api_key)
        with answer:
            _show_reply(state, today, db_path)
            if len(state["turns"]) > 1:
                with st.expander(tr("之前的对话", "Earlier conversation")):
                    for previous in state["turns"][:-1]:
                        st.text(previous["question"])
                        st.markdown(previous["reply"]["text"])


def coach_entry(today, db_path, public_demo):
    diary = (str(db_path), st.session_state.get("diary_token"))
    state = st.session_state.get("mituan_state")
    if not state or state["diary"] != diary:
        state = dict(diary=diary, open=False, pending=None, preferences=False, turns=[])
        st.session_state.mituan_state = state
    if state.pop("training_setup", False):
        if get_profile(db_path=db_path):
            st.session_state.section = "训练安排"
            st.session_state.edit_training_setup = True
            st.session_state.edit_profile = False
        else:
            st.session_state.edit_profile = True
    st.html(_STYLE)
    with st.container(key="mituan_dock"):
        cloud_mark = ' class="mituan-cloud"' if public_demo else ""
        st.html(f"<span{cloud_mark}>{_FACE}</span>")
        if st.button(tr("问米团", "Ask Mituan"), key="mituan_launcher"):
            state["open"] = True
    if state["open"]:
        st.dialog(tr("米团顾问", "Mituan, your coach"), on_dismiss=_close)(_panel)(today, db_path, public_demo)
