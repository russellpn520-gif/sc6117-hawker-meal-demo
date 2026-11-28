"""Mobile entry point for the team’s nutrition and training coach."""

from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st

from i18n import tr
from meals import SG_TIME, get_profile, has_pending


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
        state.update(open=False, pending=None, preferences=False, dinner_only=False)
        state.pop("radar", None)


def open_dinner():
    state = st.session_state.get("mituan_state")
    if state:
        state.update(open=True, pending=None, dinner_requested=True, dinner_only=True)


def _history(turns):
    return [{"role": "user", "content": turn["question"]} for turn in turns[-3:]]


def _ask(state, question, today, db_path, *, quick=None, api_key="", replace=False, dinner_budget_sgd=None):
    from coach import ask_coach

    # Consume the submitted question once, even if the dialog is rerendered.
    state["pending"] = None
    state["preferences"] = False
    lang = st.session_state.get("ui_lang", "zh")
    turns = state["turns"]
    previous_meal = turns[-1]["reply"].get("meal_context") if turns and quick in (None, "shopping") else None
    with st.spinner(tr("米团在查看你的安排…", "Mituan is checking your plan…")):
        reply = ask_coach(question, today=today, db_path=db_path, lang=lang, api_key=api_key,
                          quick=quick, history=_history(turns), meal_context=previous_meal, dinner_budget_sgd=dinner_budget_sgd)
    if replace and turns:
        turns.pop()
    turns.append({"question": tr(*_ACTIONS[quick]) if quick else question, "reply": reply, "quick": quick, "lang": lang})
    del turns[:-6]


def _show_reply(state, today, db_path):
    if not state["turns"]:
        return
    turn = state["turns"][-1]
    if turn.get("added_to_diary_draft"):
        return
    reply = turn["reply"]
    if "dinner_mode" in reply:
        from nutrition_coach import save_dinner_mode

        modes = {"out": tr("在外吃", "Eat out"), "home": tr("自己做", "Cook at home")}
        lang = st.session_state.get("ui_lang", "zh")
        selected = reply["dinner_mode"]
        if selected is None:
            st.markdown("**" + tr("今晚准备在哪儿吃？", "Where are you having dinner?") + "**")
        choice = st.segmented_control(tr("用餐方式", "Dinner setting"), list(modes),
                                      format_func=modes.__getitem__, default=selected, required=bool(selected),
                                      label_visibility="collapsed", key=f"mituan_dinner_mode_{lang}_{selected}")
        if choice in modes and choice != selected:
            save_dinner_mode(db_path, choice)
            _ask(state, "", today, db_path, quick="dinner", replace=True, dinner_budget_sgd=reply.get("dinner_budget_sgd"))
            st.rerun()
        if selected is None and turn["quick"] == "dinner":
            return
    else:
        st.text(turn["question"])
    nearby = reply.get("dinner_mode") == "out"
    if not nearby or any(t != "PlanDinner" for t in reply.get("tool_names", [])):
        st.markdown(reply["text"])
    if nearby:
        from nearby_ui import nearby_dinner

        draft_id = nearby_dinner(state, today, db_path, reply.get("dinner_budget_sgd"))
        if draft_id:
            turn["added_to_diary_draft"] = True
            st.session_state.active_draft = draft_id
            st.session_state.section = "记餐"
            st.session_state.edit_profile = False
            st.session_state.pop("receipt", None)
            _close()
            st.rerun()
    elif sources := reply.get("dinner_references"):
        with st.expander(tr("查看参考份量与来源", "Reference portions and sources")):
            for source in sources:
                st.markdown(f"[{source['name']} · {source['grams']} g]({source['source_url']})")
    tools_used = reply.get("tool_names", [])
    followups = []
    if turn["quick"] == "today" or ("ReadDiary" in tools_used and turn["quick"] != "week"):
        followups.append("week")
    if (turn["quick"] == "training" or "ReadWorkout" in tools_used) and not st.session_state.get("practice_mode"):
        followups.append("move")
    if isinstance(reply.get("meal_context"), dict) and turn["quick"] != "shopping":
        followups.append("shopping")
    for action in followups:
        if st.button(tr(*_ACTIONS[action]), key=f"mituan_follow_{action}"):
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
            if profile:
                st.session_state.section = "训练安排"
                st.session_state.edit_training_setup = True
                st.session_state.edit_profile = False
            else:
                st.session_state.edit_profile = True
            _close()
            st.rerun()
    if reply.get("show_nutrition"):
        state["preferences"] = True
    elif not nearby and (turn["quick"] in {"dinner", "shopping"} or "PlanDinner" in tools_used):
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
    if previous and previous[-1] not in state["turns"] and not previous[-1].get("added_to_diary_draft"):
        if previous[-1]["quick"] in {"dinner", "shopping"}:
            _ask(state, "", today, db_path, quick=previous[-1]["quick"])
        else:
            state["food_notice"] = True


def _greeting(today, db_path):
    from coach import _today_values

    if has_pending(db_path=db_path):
        return tr("这餐在待确认里。慢慢吃，吃完再调份量。", "Your meal is waiting in drafts. Enjoy it and confirm your portions afterwards.")
    rows, _, _, plan = _today_values(get_profile(db_path=db_path), today, db_path)
    if rows and timedelta() <= datetime.now(SG_TIME) - rows[0]["at"] < timedelta(minutes=30):
        return tr("这餐记好啦。晚餐想在附近吃点什么？", "Meal’s in the diary. Shall we find something nearby for dinner?")
    if plan and plan.training:
        return tr("今天有训练。要看看动作，还是把训练挪一天？", "There’s a workout today. Want to see it or move it to another day?")
    if plan:
        return tr("今天歇一歇。晚餐想出去吃，还是自己做？", "A rest day today. Heading out for dinner or cooking at home?")
    return tr("晚餐有想法了吗？一起看看附近有什么。", "Any dinner plans? Let’s see what’s nearby.")


def _panel(today, db_path, public_demo):
    from nutrition_coach import get_preferences
    from photo_access import coach_api_key

    state = st.session_state.mituan_state
    preferences = get_preferences(db_path)
    if "food_profile" in state and state["food_profile"] != preferences:
        _refresh_preferences(state, today, db_path)
    state["food_profile"] = preferences
    if state.pop("dinner_requested", False):
        _ask(state, "", today, db_path, quick="dinner")
    elif state["turns"]:
        last = state["turns"][-1]
        if (not last.get("added_to_diary_draft") and last.get("quick") in ("dinner", "shopping")
                and last.get("lang") != st.session_state.get("ui_lang", "zh")):
            _ask(state, "", today, db_path, quick=last["quick"], replace=True,
                 dinner_budget_sgd=last["reply"].get("dinner_budget_sgd"))
    with st.container(key="mituan_panel"):
        if state.get("dinner_only"):
            _show_reply(state, today, db_path)
            return
        greeting = _greeting(today, db_path)
        st.html(f'<div class="mituan-intro">{_FACE}<p>{greeting}</p></div>')
        if state.pop("food_notice", False):
            st.info(tr("饮食偏好已更新。请再问一次，以便按新偏好和这次的预算规划。",
                       "Your food preferences changed. Ask again to plan with your new preferences and budget."))
        answer = st.container()
        practice = st.session_state.get("practice_mode", False)
        with st.container(key="mituan_actions", horizontal=True, gap="xsmall"):
            actions = ("today", "training", "dinner", "move") if practice else ("today", "training", "dinner")
            for action in actions:
                if st.button(tr(*_ACTIONS[action]), key=f"mituan_quick_{action}"):
                    _ask(state, "", today, db_path, quick=action)
        if not practice:
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
    st.html(_STYLE)
    with st.container(key="mituan_dock"):
        cloud_mark = ' class="mituan-cloud"' if public_demo else ""
        st.html(f"<span{cloud_mark}>{_FACE}</span>")
        if st.button(tr("问米团", "Ask Mituan"), key="mituan_launcher"):
            state["open"] = True
            state["dinner_only"] = False
    if state["open"]:
        title = tr("今晚的晚餐", "Dinner tonight") if state.get("dinner_only") else tr("米团顾问", "Mituan, your coach")
        st.dialog(title, on_dismiss=_close)(_panel)(today, db_path, public_demo)
