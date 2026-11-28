import re
from datetime import timedelta
from typing import NamedTuple

import streamlit as st

from device_diary import forget_diary, remember_diary
from i18n import tr
from meals import clear_diary, move_workout, planned_days, save_profile
from planning import ACTIVITIES, GOALS, SEXES, Profile, TrainingPreferences, calorie_balance, day_plan, span, valid_training_move
from training_coach import (DAYS, EXERCISES, read_logs, save_training_log, save_training_preferences,
                            session_lines, training_context)


class ActivityText(NamedTuple):
    label: str
    training: str
    rest: str


ACTIVITY_EN = {
    "inactive": ActivityText(
        "No regular exercise · usually 0 days a week",
        "Try a comfortable 10-minute walk after a meal. Add time as it starts to feel familiar.",
        "Go about your usual day and take a short walk when you have time.",
    ),
    "occasional": ActivityText(
        "Occasionally active · usually 1–2 days a week",
        "Try 20 minutes of brisk walking at a pace that lets you talk. Shorter walks count, too.",
        "Take an easy walk today and save your energy for your next session.",
    ),
    "regular": ActivityText(
        "Regularly active · usually 3 or more days a week",
        "Choose a familiar cardio or strength session. Alternate activities so the same muscles have time to recover.",
        "An easy walk can be enough today. Resume your usual intensity at your next session.",
    ),
    "athlete": ActivityText(
        "Competitive athlete · structured training, usually over 12 hours a week",
        "Follow your coach’s sport-specific plan and match the calendar to your training days. "
        "During high-volume training, review your intake with a sports dietitian.",
        "Follow your coach’s recovery session and adjust the schedule to your current training cycle.",
    ),
}
GOAL_EN = {"maintain": "Maintain weight", "lose": "Gradual weight loss", "gain": "Gradual weight gain"}
BALANCE_EN = {
    "已超出今日目标": "Above today’s target", "今日热量": "Today’s energy",
    "已达目标": "Target reached", "已在目标范围": "Within target range",
    "今天还差": "Remaining today", "距今日目标下限": "To the lower end of your range",
}


def plan_label(plan):
    return tr(plan.label, "Training day" if plan.training else "Rest day")


def activity_label(key):
    return tr(ACTIVITIES[key].label, ACTIVITY_EN[key].label)


def goal_label(key):
    return tr(GOALS[key], GOAL_EN[key])


def month_day(day):
    return tr(f"{day:%m 月 %d 日}", f"{day:%b} {day.day}")


def profile_form(profile, today, db_path, public_demo):
    st.subheader(tr("调整个人计划", "Edit your plan") if profile else tr("先认识一下你", "Your personal plan"))
    st.caption(tr("填一次，就能在每餐后看到当天的热量余量。",
                  "Set up your plan to see how each meal fits into your day."))
    with st.form("personal_plan"):
        nickname = st.text_input(tr("怎么称呼你？（选填）", "What should we call you? (optional)"),
                                 key="plan_nickname", value=profile.nickname if profile else "",
                                 max_chars=24, placeholder=tr("昵称", "Nickname"))
        with st.container(key="body_measurements"):
            a, b, c = st.columns(3, gap="small")
            age = a.number_input(tr("年龄（岁）", "Age (years)"), min_value=1, max_value=115,
                                 value=profile.age if profile else None, step=1, key="plan_age",
                                 placeholder=tr("岁", "Years"))
            height = b.number_input(tr("身高（cm）", "Height (cm)"), min_value=80.0, max_value=250.0,
                                    value=profile.height_cm if profile else None, step=0.5, format="%.1f",
                                    key="plan_height", placeholder=tr("厘米", "cm"))
            weight = c.number_input(tr("体重（kg）", "Weight (kg)"), min_value=20.0, max_value=400.0,
                                    value=profile.weight_kg if profile else None, step=0.5, format="%.1f",
                                    key="plan_weight", placeholder=tr("公斤", "kg"))
        tiers = list(ACTIVITIES)
        tier_labels = {key: activity_label(key) for key in tiers}
        activity = st.selectbox(tr("近三个月，你通常多久运动一次？", "How often have you exercised in the last three months?"), tiers,
                                index=tiers.index(profile.activity) if profile else None,
                                placeholder=tr("选择最接近的一档", "Choose the closest match"),
                                format_func=tier_labels.__getitem__, key="plan_activity")
        sex_labels = {key: tr(label, key.capitalize()) for key, label in SEXES.items()}
        sex = st.segmented_control(tr("生理性别（选填）", "Sex for the estimate (optional)"), list(SEXES),
                                   format_func=sex_labels.__getitem__,
                                   key="plan_sex", default=profile.sex if profile else None,
                                   help=tr("选择后显示单一估值，留空会显示两种公式的估算范围。",
                                           "Choose one for a single estimate, or leave blank to see a range."))
        goal_labels = {key: goal_label(key) for key in GOALS}
        goal = st.selectbox(tr("体重目标", "Weight goal"), list(GOALS),
                            index=list(GOALS).index(profile.goal) if profile else 0,
                            format_func=goal_labels.__getitem__, key="plan_goal")
        remember = False
        if public_demo and st.session_state.get("diary_token"):
            st.caption(tr("保存后，下次用这台设备的同一浏览器可找回个人计划。",
                          "Return to this browser on this device to find your saved plan."))
        if public_demo and not st.session_state.get("diary_token") and not st.session_state.get("device_storage_blocked"):
            remember = st.checkbox(tr("在这台设备记住我的记录", "Remember my diary on this device"),
                                   help=tr("适合自己的手机。同一浏览器用随机标识找回云端临时记录；可在个人设置中清除。",
                                           "A random identifier lets this browser retrieve your temporary cloud diary. "
                                           "Use this on your own device. You can clear the diary in settings."))
        action = tr("保存调整", "Save changes") if profile else tr("生成我的计划", "Create my plan")
        submitted = st.form_submit_button(action, type="primary", width="stretch")
    if submitted:
        if age is None or height is None or weight is None or activity is None:
            st.warning(tr("请补全年龄、身高、体重和运动习惯。", "Enter your age, height, weight and activity level."))
        elif age < 18:
            st.info(tr("热量计划适用于成年人。你仍然可以直接记餐。",
                       "The energy plan is for adults. You can still log meals."))
        else:
            updated = Profile(nickname=nickname, age=age, height_cm=height, weight_kg=weight,
                              activity=activity, sex=sex, goal=goal, start=profile.start if profile else today,
                              training=profile.training if profile else None,
                              training_history=profile.training_history if profile else ())
            if min(updated.resting_kcal) <= 0:
                st.warning(tr("请核对身高、体重及单位，这组输入无法估算静息代谢。",
                              "Check your height and weight, including the units, so we can estimate your resting energy."))
                return
            if remember:
                db_path = remember_diary(db_path)
            save_profile(updated, db_path=db_path)
            st.session_state.edit_profile = False
            st.session_state.guest = False
            st.rerun()
    if profile:
        if st.button(tr("返回", "Back")):
            st.session_state.edit_profile = False
            st.rerun()
    elif st.button(tr("先试试记餐", "Try logging a meal first")):
        st.session_state.edit_profile = False
        st.session_state.guest = True
        st.rerun()


def day_summary(profile, today, plan, eaten, *, partial_count=0, legacy_count=0):
    nickname = re.sub(r"([\\`*_{}\[\]()<>#!|~$])", r"\\\1", profile.nickname)
    name = (nickname + "的") if nickname else ""
    st.subheader(tr(f"{name}今日计划", f"Today’s plan · {nickname}" if nickname else "Today’s plan"))
    tier = ACTIVITIES[profile.activity]
    goal = profile.goal if profile.goal_factor != 1 else "maintain"
    st.caption(f"{month_day(today)} · {plan_label(plan)} · {goal_label(goal)}")
    incomplete = partial_count or legacy_count
    if incomplete:
        label, value = tr("已记热量小计", "Energy logged"), f"{eaten['kcal']:.0f} kcal"
    else:
        label, value = calorie_balance(plan.kcal, eaten["kcal"])
        label = tr(label, BALANCE_EN[label])
        value = tr(value, BALANCE_EN.get(value, value))
    with st.container(key="daily_balance"):
        a, b = st.columns(2)
        a.metric(label, value)
        remaining = plan.protein_g - eaten["protein_g"]
        if incomplete:
            b.metric(tr("已记蛋白质小计", "Protein logged"), f"{eaten['protein_g']:.1f} g")
        else:
            b.metric(tr("蛋白质还差", "Protein remaining") if remaining > 0 else tr("蛋白质", "Protein"),
                     f"{remaining:.1f} g" if remaining > 0 else tr("已达目标", "Target reached"))
    if partial_count:
        st.caption(tr(f"今天有 {partial_count} 笔只计入了部分食物。",
                      f"Only some foods were included in {partial_count} of today’s entries."))
    if legacy_count:
        st.caption(tr(f"有 {legacy_count} 笔旧记录曾有食物未匹配，完整性待核对。",
                      f"Check the {legacy_count} older " + ("entry" if legacy_count == 1 else "entries") +
                      " with unmatched foods."))
    st.write(tr(f"已记 **{eaten['kcal']:.0f} kcal** / 今日目标 **{span(plan.kcal)} kcal**",
                f"Logged **{eaten['kcal']:.0f} kcal** · Daily target **{span(plan.kcal)} kcal**"))
    st.caption(tr(f"静息代谢约 {span(profile.resting_kcal)} kcal/天 · 每日蛋白质目标 {plan.protein_g} g",
                  f"Estimated resting energy {span(profile.resting_kcal)} kcal/day · Protein target {plan.protein_g} g/day"))
    copy = ACTIVITY_EN[profile.activity]
    st.write(tr(tier.advice, copy.training) if plan.training else tr(tier.recovery, copy.rest))


def _change_date(profile, origin, destination, db_path):
    if move_workout(profile, origin, destination, db_path=db_path):
        st.session_state.notice = tr(f"训练已从 {origin:%m/%d} 移到 {destination:%m/%d}，两天的目标已更新。",
                                     f"Workout moved from {month_day(origin)} to {month_day(destination)}. "
                                     "Both days’ targets have been updated.")
    else:
        st.session_state.notice = tr("这两个日期的安排刚刚变过，已刷新为当前日程。",
                                     "These dates have changed. The calendar now shows the latest schedule.")
    st.rerun()


def training_plan(profile, today, days, db_path):
    tomorrow = today + timedelta(days=1)
    st.subheader(tr("训练安排", "Training schedule"))
    for day, name in [(today, tr("今天", "Today")), (tomorrow, tr("明天", "Tomorrow"))]:
        plan = day_plan(profile, day, days)
        st.write(f"**{name} · {plan_label(plan)}**　{span(plan.kcal)} kcal · "
                 + tr(f"蛋白质 {plan.protein_g} g", f"{plan.protein_g} g protein"))
    if (today in days) != (tomorrow in days):
        origin, destination = (today, tomorrow) if today in days else (tomorrow, today)
        label = (tr("把今天的训练移到明天", "Move today’s workout to tomorrow") if origin == today
                 else tr("把明天的训练移到今天", "Move tomorrow’s workout to today"))
        if valid_training_move(profile, origin, destination, set(days) - {origin}) and st.button(label, type="primary"):
            _change_date(profile, origin, destination, db_path)
    upcoming = [today + timedelta(days=i) for i in range(14)]
    active = [d for d in upcoming if d in days]
    rest = [d for d in upcoming if d not in days]
    with st.expander(tr("查看两周安排或改到其他日期", "See the next two weeks or change a date")):
        st.caption(tr("按运动习惯生成的建议训练日，可根据自己的日程改期。",
                      "These dates follow your usual activity level. Move a workout to fit your schedule."))
        st.write(tr("、", ", ").join(month_day(d) for d in active)
                 or tr("接下来两周没有训练。", "No workouts scheduled for the next two weeks."))
        if active and rest:
            date_labels = {d: month_day(d) for d in upcoming}
            origin = st.selectbox(tr("把哪天的训练移走？", "Which workout do you want to move?"),
                                  active, format_func=date_labels.__getitem__, key="reschedule_origin")
            options = [d for d in rest if valid_training_move(profile, origin, d, set(days) - {origin})]
            if not options:
                st.caption(tr("这两周暂无符合可用日期和恢复间隔的空档。",
                              "There is no other date in this period that fits your availability and recovery days."))
            else:
                with st.form("reschedule"):
                    destination = st.selectbox(tr("改到哪个休息日？", "Choose a rest day to train instead"),
                                               options, format_func=date_labels.__getitem__, key="reschedule_destination")
                    submit = st.form_submit_button(tr("确认改期", "Confirm new date"))
                if submit:
                    _change_date(profile, origin, destination, db_path)
    _strength_panel(profile, today, db_path)


def _strength_panel(profile, today, db_path):
    prefs = profile.training
    with st.expander(tr("设置力量训练", "Strength training setup"),
                     expanded=bool(st.session_state.pop("edit_training_setup", False))):
        with st.form("training_availability"):
            labels = {i: tr("周" + name[0], name[1]) for i, name in enumerate(DAYS)}
            weekdays = st.multiselect(tr("一周哪几天有空？", "Which weekdays are available?"), list(labels),
                                      default=list(prefs.weekdays) if prefs else [], format_func=labels.__getitem__)
            gear = {"bodyweight": tr("徒手", "Bodyweight"), "dumbbells": tr("徒手和哑铃", "Bodyweight and dumbbells")}
            equipment = st.selectbox(tr("可用器械", "Available equipment"), list(gear), format_func=gear.__getitem__,
                                     index=int(bool(prefs and prefs.equipment == "dumbbells")))
            minutes = st.select_slider(tr("每次可用时间（分钟）", "Minutes available per workout"), [10, 20, 30],
                                       value=prefs.minutes if prefs else 20)
            st.caption(tr("从今天起安排力量训练，已记过今天的训练则从明天开始。训练间隔恢复日，与新时间冲突的改期会更新。",
                          "The schedule starts today, or tomorrow if today’s workout is logged. It leaves days for recovery. "
                          "Earlier reschedules that conflict with the new availability will be updated."))
            if st.form_submit_button(tr("应用训练安排", "Apply training schedule")):
                if not weekdays:
                    st.warning(tr("请选择至少一个可训练日。", "Choose at least one available day."))
                else:
                    new = TrainingPreferences(equipment=equipment, weekdays=weekdays, minutes=minutes, since=today)
                    save_training_preferences(profile, new, db_path=db_path)
                    st.rerun()
    if not prefs:
        return
    lang = tr("zh", "en")
    context = training_context(profile, today, db_path=db_path, lang=lang)
    session = next((s for s in context["sessions"] if s["exercises"]), None)
    if session:
        st.markdown("**" + tr("本次力量训练", "Your strength session") + " · " + session["date"] + "**")
        for line in session_lines(session, lang):
            st.write(line)
        st.caption(tr("先轻松热身，组间充分休息，按可用时间结束。有疼痛、孕期或健康状况时请先咨询专业人员。",
                      "Warm up gently, rest between sets and finish within the time available. "
                      "For pain, pregnancy or health conditions, consult a qualified professional."))
        with st.expander(tr("进度与训练依据", "Progression and sources")):
            st.caption(tr("连续两次轻松完成目标后可增加一次重复。漏练后从较轻的训练恢复；连续两次吃力或第四周减量。重量沿用实际记录。",
                          "Two comfortable completions can earn one extra rep. A missed session eases you back in; "
                          "two difficult sessions or week four trigger a lighter session. Weights come from your own log."))
            st.markdown("[NHS · Strength exercises](https://www.nhs.uk/live-well/exercise/strength-exercises/)")
    _training_log_ui(profile, today, db_path, lang)


def _training_log_ui(profile, today, db_path, lang):
    start = max(profile.start, today - timedelta(days=13))
    eligible = sorted((d for d in planned_days(profile, start, today, db_path=db_path) if profile.training_for(d)), reverse=True)
    recent = read_logs(start, today, db_path=db_path)
    records = {r["date"]: r for r in recent}
    with st.expander(tr("记录训练或漏练", "Log a workout or missed session")):
        if not eligible:
            st.caption(tr("第一个训练日到来后就可以在这里记录。", "You can log your first workout on its scheduled date."))
        else:
            day = st.selectbox(tr("训练日期", "Workout date"), eligible, format_func=str, key="workout_log_day")
            session = training_context(profile, day, db_path=db_path, lang=lang)["sessions"][0]
            existing = records.get(day.isoformat(), {})
            statuses = {"comfortable": tr("顺利完成", "Comfortable"), "challenging": tr("吃力或未完成目标", "Challenging or incomplete"),
                        "missed": tr("这次漏练", "Missed")}
            status = st.radio(tr("这次训练怎么样？", "How did it go?"), list(statuses), horizontal=True,
                              index=list(statuses).index(existing.get("status", "comfortable")), format_func=statuses.__getitem__,
                              key=f"training-result-{day}")
            with st.form(f"workout-entry-{day}-{status}"):
                entries = {}
                if status != "missed":
                    st.caption(tr("每组实做次数用逗号隔开；没做的动作留空。",
                                  "Enter the reps you actually did in each set, separated by commas. Leave skipped exercises blank."))
                    for ex in session["exercises"]:
                        key = ex["id"]
                        saved = existing.get("actuals", {}).get(key, [])
                        reps = st.text_input(ex["name"] + tr(" · 每组次数", " · reps per set"),
                                             value=", ".join(str(s["reps"]) for s in saved), placeholder="8, 7",
                                             max_chars=100)
                        loads = ""
                        if key == "curl":
                            loads = st.text_input(tr("每只哑铃重量（kg，每组一个数或共用一个数）",
                                                     "Weight per dumbbell (kg, one value or one per set)"),
                                                  value=", ".join(f"{s['kg']:g}" for s in saved), placeholder="2", max_chars=100)
                        entries[key] = (reps, loads)
                if st.form_submit_button(tr("保存训练记录", "Save workout log")):
                    try:
                        actuals = {}
                        for key, (reps, loads) in entries.items():
                            if not reps.strip():
                                continue
                            rep_list = [int(v) for v in re.split("[,，]", reps)]
                            kg_list = [float(v) for v in re.split("[,，]", loads)] if key == "curl" else [0]
                            if len(kg_list) == 1:
                                kg_list *= len(rep_list)
                            if len(kg_list) != len(rep_list):
                                raise ValueError("sets")
                            actuals[key] = [{"reps": r, "kg": kg} for r, kg in zip(rep_list, kg_list)]
                        save_training_log(profile, day, today, status, actuals, db_path=db_path)
                    except (TypeError, ValueError):
                        st.warning(tr("请核对每组实做次数和哑铃重量，或选择「这次漏练」。",
                                      "Check actual reps and dumbbell weights, or select Missed."))
                    else:
                        st.session_state.notice = tr("训练记录已保存。", "Workout logged.")
                        st.rerun()
        if recent:
            for record in reversed(recent[-4:]):
                lines = []
                for key, sets in record["actuals"].items():
                    name = EXERCISES[key][lang == "en"]
                    numbers = ", ".join(f"{s['reps']} × {s['kg']:g} kg" if key == "curl" else str(s["reps"]) for s in sets)
                    lines.append(f"{name} ({numbers})")
                st.caption(record["date"] + " · " + (" / ".join(lines) if lines else tr("漏练", "Missed")))


def calendar_for_view(profile, today, db_path):
    last = today + timedelta(days=13)
    return planned_days(profile, profile.week_start(today), profile.week_start(last) + timedelta(days=6), db_path=db_path)


def settings(profile, db_path, public_demo):
    with st.expander(tr("个人设置与估算依据", "Settings and estimates")):
        if profile:
            st.write(f"{activity_label(profile.activity)} · {goal_label(profile.goal)}")
            if profile.goal != "maintain" and profile.goal_factor == 1:
                st.caption(tr("按这份身体或训练资料，体验版继续以维持体重估算。",
                              "With your current profile, this demo uses a weight-maintenance estimate."))
            if st.button(tr("修改我的资料和目标", "Edit profile and goals")):
                st.session_state.edit_profile = True
                st.rerun()
            st.markdown(tr("使用成人 Mifflin–St Jeor 公式估算静息代谢，再乘活动系数得到平均每日消耗。"
                           "默认维持体重，可选目标按均值上调或下调约 5%。选择范围时，两端对应两种公式系数。"
                           " [公式原文](https://pubmed.ncbi.nlm.nih.gov/2305711/)",
                           "The Mifflin–St Jeor equation estimates resting energy in adults. An activity factor "
                           "scales this to average daily needs. The default goal is weight maintenance. "
                           "Optional weight goals adjust the average by about 5%. A range uses both sex coefficients. "
                           "[Original study](https://pubmed.ncbi.nlm.nih.gov/2305711/)"))
            st.markdown(tr("四档综合参考运动频率、训练量与备赛情况，活动系数依次为 1.20、1.375、1.50、1.90。"
                           "以建档日为起点，每七天保持同一热量预算，训练日与休息日相差约日均预算的 8%。"
                           "这是演示用的目标分配，专业运动员应按实际训练量校准。",
                           "The four activity levels use factors of 1.20, 1.375, 1.50 and 1.90. The total energy "
                           "budget stays the same across each seven-day period starting when you set up your plan. "
                           "Training and rest days differ by about 8% of the daily average. Competitive athletes "
                           "should tailor these demo targets to their training load.") +
                        " [Cronometer](https://support.cronometer.com/hc/en-us/articles/31974307318420-Energy-Expenditure)"
                        " · [Polar](https://support.polar.com/uk-en/support/what_is_my_training_background)")
            st.markdown(tr("蛋白质按体重和运动习惯估算，训练日每公斤上调 0.1 g。经常运动且制定力量计划的成年人选择温和增减重时，演示基准为每日每公斤至少 1.3 g。训练建议从熟悉的活动开始。"
                           " 孕哺期、康复期或有特殊营养需求时，可使用记餐功能，并向专业人员确认个人目标。",
                           "Protein targets depend on body weight and activity level, with an extra 0.1 g per kg "
                           "on training days. For regularly active adults using the strength plan with a gradual weight-change goal, "
                           "the demo uses a starting estimate of at least 1.3 g/kg daily. Start with familiar activities. If you are pregnant, breastfeeding, "
                           "recovering, or have specific dietary needs, ask a health professional about your goals.") +
                        " [HealthHub](https://www.healthhub.sg/well-being-and-lifestyle/food-diet-and-nutrition/why_protein_is_important)"
                        " · [NIH ODS](https://ods.od.nih.gov/factsheets/ExerciseAndAthleticPerformance-HealthProfessional/)")
        if public_demo:
            if st.session_state.get("device_storage_blocked"):
                st.caption(tr("浏览器限制了设备存储，本次仅使用当前会话。",
                              "This browser limits device storage. Your diary is available in this session."))
            elif st.session_state.get("diary_token"):
                st.caption(tr("已在这台设备记住记录。使用同一浏览器可找回，云端临时存储重置时记录可能清空。",
                              "Open this browser on this device to return to your diary. A cloud storage reset "
                              "can clear your confirmed entries."))
            else:
                st.caption(tr("当前仅保留本次会话。可在修改资料时选择让这台设备记住记录。",
                              "This diary lasts for the current session. You can choose to remember this device "
                              "when editing your profile."))
        if st.checkbox(tr("我要清除这份档案、训练安排和餐食记录", "Clear my profile, training schedule and meals"),
                       key="request_clear"):
            if st.button(tr("确认清除我的全部记录", "Confirm deletion of all my records")):
                clear_diary(db_path=db_path)
                if public_demo:
                    forget_diary()
                for key in ("guest", "saved", "draft", "edit_profile", "mituan_state", "edit_training_setup"):
                    st.session_state.pop(key, None)
                for key in ("receipt", "capture_ack", "active_draft"):
                    st.session_state.pop(key, None)
                st.session_state.notice = tr("这份档案、训练安排和餐食记录已清除。",
                                             "Your profile, training schedule and meal records have been cleared.")
                st.rerun()
