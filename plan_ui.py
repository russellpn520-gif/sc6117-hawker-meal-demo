import re
from datetime import timedelta

import streamlit as st

from device_diary import forget_diary, remember_diary
from meals import clear_diary, move_workout, planned_days, save_profile
from planning import ACTIVITIES, GOALS, SEXES, Profile, calorie_balance, day_plan, span


def profile_form(profile, today, db_path, public_demo):
    st.subheader("调整个人计划" if profile else "先认识一下你")
    st.caption("填一次，就能在每餐后看到当天的热量余量。")
    with st.form("personal_plan"):
        nickname = st.text_input("怎么称呼你？（选填）", value=profile.nickname if profile else "",
                                 max_chars=24, placeholder="昵称")
        with st.container(key="body_measurements"):
            a, b, c = st.columns(3, gap="small")
            age = a.number_input("年龄（岁）", min_value=1, max_value=115, value=profile.age if profile else None,
                                 step=1, placeholder="岁")
            height = b.number_input("身高（cm）", min_value=80.0, max_value=250.0,
                                    value=profile.height_cm if profile else None, step=0.5, format="%.1f", placeholder="厘米")
            weight = c.number_input("体重（kg）", min_value=20.0, max_value=400.0,
                                    value=profile.weight_kg if profile else None, step=0.5, format="%.1f", placeholder="公斤")
        tiers = list(ACTIVITIES)
        activity = st.selectbox("近三个月，你通常多久运动一次？", tiers,
                                index=tiers.index(profile.activity) if profile else None,
                                placeholder="选择最接近的一档", format_func=lambda k: ACTIVITIES[k].label)
        sex = st.segmented_control("生理性别（选填）", list(SEXES), format_func=SEXES.get,
                                   default=profile.sex if profile else None,
                                   help="选择后显示单一估值，留空会显示两种公式的估算范围。")
        goal = "maintain"
        if profile:
            goal = st.selectbox("体重目标", list(GOALS), index=list(GOALS).index(profile.goal),
                                format_func=GOALS.get)
        remember = False
        if public_demo and st.session_state.get("diary_token"):
            st.caption("保存后，下次用这台设备的同一浏览器可找回个人计划。")
        if public_demo and not st.session_state.get("diary_token") and not st.session_state.get("device_storage_blocked"):
            remember = st.checkbox("在这台设备记住我的记录",
                                   help="适合自己的手机。同一浏览器用随机标识找回云端临时记录；可在个人设置中清除。")
        submitted = st.form_submit_button("保存调整" if profile else "生成我的计划", type="primary", width="stretch")
    if submitted:
        if age is None or height is None or weight is None or activity is None:
            st.warning("请补全年龄、身高、体重和运动习惯。")
        elif age < 18:
            st.info("热量计划适用于成年人。你仍然可以直接记餐。")
        else:
            updated = Profile(nickname=nickname, age=age, height_cm=height, weight_kg=weight,
                              activity=activity, sex=sex, goal=goal, start=profile.start if profile else today)
            if min(updated.resting_kcal) <= 0:
                st.warning("请核对身高、体重及单位，这组输入无法估算静息代谢。")
                return
            if remember:
                db_path = remember_diary(db_path)
            save_profile(updated, db_path=db_path)
            st.session_state.edit_profile = False
            st.session_state.guest = False
            st.rerun()
    if profile:
        if st.button("返回"):
            st.session_state.edit_profile = False
            st.rerun()
    elif st.button("先试试记餐"):
        st.session_state.edit_profile = False
        st.session_state.guest = True
        st.rerun()


def day_summary(profile, today, plan, eaten, *, partial_count=0, legacy_count=0):
    nickname = re.sub(r"([\\`*_{}\[\]()<>#!|~$])", r"\\\1", profile.nickname)
    name = (nickname + "的") if nickname else ""
    st.subheader(f"{name}今日计划")
    tier = ACTIVITIES[profile.activity]
    st.caption(f"{today:%m 月 %d 日} · {plan.label} · {GOALS[profile.goal] if profile.goal_factor != 1 else GOALS['maintain']}")
    incomplete = partial_count or legacy_count
    label, value = (("已记热量小计", f"{eaten['kcal']:.0f} kcal") if incomplete
                    else calorie_balance(plan.kcal, eaten["kcal"]))
    with st.container(key="daily_balance"):
        a, b = st.columns(2)
        a.metric(label, value)
        remaining = plan.protein_g - eaten["protein_g"]
        if incomplete:
            b.metric("已记蛋白质小计", f"{eaten['protein_g']:.1f} g")
        else:
            b.metric("蛋白质还差" if remaining > 0 else "蛋白质", f"{remaining:.1f} g" if remaining > 0 else "已达目标")
    if partial_count:
        st.caption(f"今天有 {partial_count} 笔只计入了部分食物。")
    if legacy_count:
        st.caption(f"有 {legacy_count} 笔旧记录曾有食物未匹配，完整性待核对。")
    st.write(f"已记 **{eaten['kcal']:.0f} kcal** / 今日目标 **{span(plan.kcal)} kcal**")
    st.caption(f"静息代谢约 {span(profile.resting_kcal)} kcal/天 · 每日蛋白质目标 {plan.protein_g} g")
    st.write(tier.advice if plan.training else tier.recovery)


def _change_date(profile, origin, destination, db_path):
    if move_workout(profile, origin, destination, db_path=db_path):
        st.session_state.notice = f"训练已从 {origin:%m/%d} 移到 {destination:%m/%d}，两天的目标已更新。"
    else:
        st.session_state.notice = "这两个日期的安排刚刚变过，已刷新为当前日程。"
    st.rerun()


def training_plan(profile, today, days, db_path):
    tomorrow = today + timedelta(days=1)
    st.subheader("训练安排")
    for day, name in [(today, "今天"), (tomorrow, "明天")]:
        plan = day_plan(profile, day, days)
        st.write(f"**{name} · {plan.label}**　{span(plan.kcal)} kcal · 蛋白质 {plan.protein_g} g")
    if (today in days) != (tomorrow in days):
        origin, destination = (today, tomorrow) if today in days else (tomorrow, today)
        label = "把今天的训练移到明天" if origin == today else "把明天的训练移到今天"
        if st.button(label, type="primary"):
            _change_date(profile, origin, destination, db_path)
    upcoming = [today + timedelta(days=i) for i in range(14)]
    active = [d for d in upcoming if d in days]
    rest = [d for d in upcoming if d not in days]
    with st.expander("查看两周安排或改到其他日期"):
        st.caption("按运动习惯生成的建议训练日，可根据自己的日程改期。")
        st.write("、".join(f"{d:%m/%d}" for d in active) or "接下来两周没有训练。")
        if active and rest:
            with st.form("reschedule"):
                origin = st.selectbox("把哪天的训练移走？", active, format_func=lambda d: f"{d:%m 月 %d 日}")
                destination = st.selectbox("改到哪个休息日？", rest, format_func=lambda d: f"{d:%m 月 %d 日}")
                submit = st.form_submit_button("确认改期")
            if submit:
                _change_date(profile, origin, destination, db_path)


def calendar_for_view(profile, today, db_path):
    last = today + timedelta(days=13)
    return planned_days(profile, profile.week_start(today), profile.week_start(last) + timedelta(days=6), db_path=db_path)


def settings(profile, db_path, public_demo):
    with st.expander("个人设置与估算依据"):
        if profile:
            st.write(f"{ACTIVITIES[profile.activity].label} · {GOALS[profile.goal]}")
            if profile.goal != "maintain" and profile.goal_factor == 1:
                st.caption("按这份身体或训练资料，体验版继续以维持体重估算。")
            if st.button("修改我的资料和目标"):
                st.session_state.edit_profile = True
                st.rerun()
            st.markdown("使用成人 Mifflin–St Jeor 公式估算静息代谢，再乘活动系数得到平均每日消耗。"
                        "默认维持体重；可选目标按均值上调或下调约 5%。选择范围时，两端对应两种公式系数。"
                        " [公式原文](https://pubmed.ncbi.nlm.nih.gov/2305711/)")
            st.markdown("四档综合参考运动频率、训练量与备赛情况，活动系数依次为 1.20、1.375、1.50、1.90。"
                        "以建档日为起点，每七天保持同一热量预算，训练日与休息日相差约日均预算的 8%。"
                        "这是演示用的目标分配，专业运动员应按实际训练量校准。"
                        " [Cronometer](https://support.cronometer.com/hc/en-us/articles/31974307318420-Energy-Expenditure)"
                        " · [Polar](https://support.polar.com/uk-en/support/what_is_my_training_background)")
            st.markdown("蛋白质按体重和运动习惯估算，训练日每公斤上调 0.1 g。训练建议从熟悉的活动开始。"
                        " 孕哺期、康复期或有特殊营养需求时，可使用记餐功能，并向专业人员确认个人目标。"
                        " [新加坡 HealthHub](https://www.healthhub.sg/well-being-and-lifestyle/food-diet-and-nutrition/why_protein_is_important)")
        if public_demo:
            if st.session_state.get("device_storage_blocked"):
                st.caption("浏览器限制了设备存储，本次仅使用当前会话。")
            elif st.session_state.get("diary_token"):
                st.caption("已在这台设备记住记录。使用同一浏览器可找回，云端临时存储重置时记录可能清空。")
            else:
                st.caption("当前仅保留本次会话。可在修改资料时选择让这台设备记住记录。")
        if st.checkbox("我要清除这份档案、训练安排和餐食记录", key="request_clear"):
            if st.button("确认清除我的全部记录"):
                clear_diary(db_path=db_path)
                if public_demo:
                    forget_diary()
                for key in ("guest", "saved", "draft", "edit_profile"):
                    st.session_state.pop(key, None)
                for key in ("receipt", "capture_ack", "active_draft"):
                    st.session_state.pop(key, None)
                st.session_state.notice = "这份档案、训练安排和餐食记录已清除。"
                st.rerun()
