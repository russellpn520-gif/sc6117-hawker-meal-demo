import re
from datetime import timedelta
from html import escape
from typing import NamedTuple

import streamlit as st

from device_diary import forget_diary, remember_diary
from i18n import tr
from meals import clear_diary, diary_day_plan, diary_move_targets, move_workout, planned_days, save_profile
from planning import (ACTIVITIES, CARDIO, GOALS, SEXES, THEMES, Profile, TrainingPreferences,
                      span, training_theme, valid_training_move)
from training_coach import (DAYS, EXERCISES, WEIGHTED, read_logs, save_training_log, save_training_preferences,
                            session_lines, session_for_day)


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
GOAL_EN = {"lose": "Fat loss", "gain": "Muscle gain", "recomp": "Fat loss + muscle gain"}
def plan_label(plan):
    return tr(*THEMES[plan.theme if plan.training else "rest"])


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
        goal = st.selectbox(tr("体态目标", "Body goal"), list(GOALS),
                            index=list(GOALS).index(profile.goal if profile else "recomp"),
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


def _preview_date(profile, origin, destination, days, diary, db_path):
    targets = diary_move_targets(profile, origin, destination, days, db_path)
    st.session_state.training_move_preview = (diary, origin, destination, targets)
    st.rerun()


def _review_date(profile, origin, destination, targets, db_path):
    lines = []
    for day, (before, after) in zip((origin, destination), targets):
        change = span(sorted(abs(a - b) for a, b in zip(after.kcal, before.kcal)))
        delta = (tr(f"增加 {change}", f"up {change}") if after.training
                 else tr(f"减少 {change}", f"down {change}"))
        if after.kcal == before.kcal:
            delta = tr("变化 0", "change 0")
        lines.append(f"**{month_day(day)} · {plan_label(after)}**  \n"
                     f"{span(before.kcal)} → **{span(after.kcal)} kcal** ({delta} kcal)　" +
                     tr(f"蛋白 {before.protein_g} → {after.protein_g} · 碳水 {before.carb_g} → {after.carb_g} · 脂肪 {before.fat_g} → {after.fat_g}\u00a0g",
                        f"Protein {before.protein_g} → {after.protein_g} · Carbs {before.carb_g} → {after.carb_g} · Fat {before.fat_g} → {after.fat_g}\u00a0g"))
    comparison = "\n\n".join(lines)
    st.markdown("**" + tr("改期后的每日热量目标", "Daily targets after this move") + "**")
    st.markdown(comparison)
    if profile.week_start(origin) != profile.week_start(destination):
        st.caption(tr("这次改期跨周，两个日期的目标将按新的训练安排计算。",
                      "This move crosses two weeks. Both dates will use their new training schedules."))
    elif origin.isocalendar()[:2] != destination.isocalendar()[:2]:
        st.caption(tr("这次训练将移到另一个日历周。", "This workout moves to a different calendar week."))
    if st.button(tr("确认改期", "Confirm new date"), key="confirm_training_move", type="primary", width="stretch"):
        st.session_state.pop("training_move_preview", None)
        if move_workout(profile, origin, destination, db_path=db_path, require_current_profile=True, expected_targets=targets):
            st.session_state.selected_day = destination
            st.session_state.pop("training_action", None)
            st.session_state.notice = tr(f"训练已从 {month_day(origin)} 移到 {month_day(destination)}。",
                                         f"Workout moved from {month_day(origin)} to {month_day(destination)}.")
        else:
            st.session_state.notice = tr("训练安排或目标已有变化，这次改期未保存。请重新选择日期。",
                                         "Your schedule or targets have changed. The move was not saved. Choose new dates.")
        st.rerun()
    if st.button(tr("取消", "Cancel"), key="cancel_training_move", width="stretch"):
        st.session_state.pop("training_move_preview", None)
        st.rerun()


def _setup_form(profile, today, db_path):
    prefs = profile.training
    with st.form("training_availability"):
        labels = {i: tr("周" + name[0], name[1]) for i, name in enumerate(DAYS)}
        weekdays = st.multiselect(tr("一周哪几天有空？", "Which weekdays are available?"), list(labels),
                                  default=list(prefs.weekdays) if prefs else [], format_func=labels.__getitem__)
        def choose(label, choices, default):
            names = {key: tr(*pair) for key, pair in choices.items()}
            return st.selectbox(tr(*label), list(names), index=list(names).index(default),
                                format_func=names.__getitem__)

        equipment = choose(("可用器械", "Available equipment"), {
            "bodyweight": ("居家徒手", "Bodyweight"), "dumbbells": ("居家哑铃", "Dumbbells"),
            "gym": ("健身房器械", "Gym equipment")}, prefs.equipment if prefs else "bodyweight")
        mode = choose(("训练模式", "Training style"), {
            "strength": ("力量为主", "Strength"), "mixed": ("力量 + 有氧", "Strength + cardio"),
            "cardio": ("有氧为主", "Cardio")}, (prefs.mode if prefs else None) or "strength")
        cardio = choose(("有氧日做什么？", "Cardio activity"), {k: THEMES[k] for k in ("run", "swim", "cycle", "walk")},
                        prefs.cardio if prefs else "run")
        minutes = st.select_slider(tr("每次可用时间（分钟）", "Minutes available per workout"), [10, 20, 30, 45, 60],
                                   value=prefs.minutes if prefs else 20)
        slot = choose(("通常什么时候练？", "Usual workout time"), {
            None: ("随时", "Flexible"), "morning": ("早上", "Morning"), "afternoon": ("下午", "Afternoon"),
            "evening": ("傍晚", "Evening")}, prefs.time_slot if prefs else None)
        st.caption(tr("每个选中的日子安排一节课，之后可以单独改期。", "Each selected day gets a session. You can move individual workouts later."))
        if st.form_submit_button(tr("应用训练安排", "Apply training schedule"), type="primary"):
            if not weekdays:
                st.warning(tr("请选择至少一个可训练日。", "Choose at least one available day."))
            else:
                new = TrainingPreferences(equipment=equipment, weekdays=weekdays, minutes=minutes, since=today,
                                          mode=mode, cardio=cardio, time_slot=slot)
                save_training_preferences(profile, new, db_path=db_path)
                _dismiss_training_dialog()
                st.session_state.pop("training_move_preview", None)
                st.session_state.pop("training_action", None)
                st.rerun()


def _training_log_ui(profile, day, today, session, existing, db_path):
    statuses = {"comfortable": tr("顺利完成", "Comfortable"), "challenging": tr("吃力或未完成目标", "Challenging or incomplete"),
                "missed": tr("这次漏练", "Missed")}
    status = st.radio(tr("这次训练怎么样？", "How did it go?"), list(statuses), horizontal=True,
                      index=list(statuses).index(existing.get("status", "comfortable")), format_func=statuses.__getitem__,
                      key=f"training-result-{day}")
    with st.form(f"workout-entry-{day}-{status}"):
        entries = {}
        cardio_log = session["mode"] == "cardio" and status != "missed"
        if cardio_log:
            saved = existing.get("actuals", {})
            duration = st.number_input(tr("实际分钟", "Actual minutes"), 1, 600, saved.get("minutes", session["planned_minutes"]))
            effort = st.slider(tr("体感强度 · 1 很轻松，10 很吃力", "Effort · 1 very easy, 10 very hard"), 1, 10, saved.get("rpe", 4))
        elif status != "missed":
            st.caption(tr("每组实做次数用逗号隔开；没做的动作留空。",
                          "Enter the reps you actually did in each set, separated by commas. Leave skipped exercises blank."))
            for ex in session["exercises"]:
                key = ex["id"]
                saved = existing.get("actuals", {}).get(key, [])
                reps = st.text_input(ex["name"] + tr(" · 每组次数", " · reps per set"),
                                     value=", ".join(str(s["reps"]) for s in saved), placeholder="8, 7",
                                     max_chars=100)
                loads = ""
                if key in WEIGHTED:
                    load_label = tr("每只哑铃重量（kg，每组一个数或共用一个数）",
                                             "Weight per dumbbell (kg, one value or one per set)") if key == "curl" else tr("每组使用重量（kg）", "Load per set (kg)")
                    loads = st.text_input(ex["name"] + " · " + load_label,
                                          value=", ".join(f"{s['kg']:g}" for s in saved), placeholder=tr("例如 20", "e.g. 20"), max_chars=100,
                                          key=f"log-kg-{day}-{key}")
                entries[key] = (reps, loads)
        if st.form_submit_button(tr("保存训练记录", "Save workout log"), type="primary"):
            try:
                actuals = {"minutes": duration, "rpe": effort} if cardio_log else {}
                for key, (reps, loads) in entries.items():
                    if not reps.strip():
                        continue
                    rep_list = [int(v) for v in re.split("[,，]", reps)]
                    kg_list = [float(v) for v in re.split("[,，]", loads)] if key in WEIGHTED else [0]
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
                st.session_state.pop("training_action", None)
                st.rerun()


def _actual_summary(record, lang):
    lines = []
    actuals = record["actuals"]
    if "minutes" in actuals:
        minutes, effort = actuals["minutes"], actuals["rpe"]
        lines.append(tr(f"{minutes} 分钟 · 用力程度 {effort}/10", f"{minutes} min · RPE {effort}/10"))
    for key, sets in actuals.items():
        if key not in EXERCISES:
            continue
        name = EXERCISES[key][lang == "en"]
        numbers = ", ".join(f"{s['reps']} × {s['kg']:g} kg" if key in WEIGHTED else str(s["reps"]) for s in sets)
        lines.append(f"{name} ({numbers})")
    st.write(" · ".join(lines) if lines else tr("已标记漏练", "Marked as missed"))


DAY_TAG = {
    "push": ("推", "Push"), "pull": ("拉", "Pull"), "legs": ("腿", "Legs"),
    "chest": ("胸", "Chest"), "back": ("背", "Back"), "full": ("全", "Full"),
    "upper": ("上", "Upper"), "lower": ("下", "Lower"), "core": ("核", "Core"),
    "general": ("全", "Full"), "run": ("跑", "Run"), "swim": ("游", "Swim"),
    "cycle": ("骑", "Ride"), "walk": ("走", "Walk"), "rest": ("休", "Rest"),
}


def _select_day(day):
    st.session_state.selected_day = day
    st.session_state.pop("training_action", None)
    st.session_state.pop("training_move_preview", None)


def _theme_name(theme):
    if theme == "general":
        return tr("全身基础", "Full-body basics")
    if theme == "rest":
        return tr("恢复休息日", "Recovery day")
    return tr(*THEMES[theme])


def _calendar_grid(profile, today, selected, dates, days, logs):
    with st.container(key="training_calendar", gap="small"):
        st.caption(f"{month_day(dates[0])} – {month_day(dates[-1])}")
        labels = "".join(f"<span>{tr(*names)}</span>" for names in DAYS)
        st.html(f'<div class="cal-weekdays">{labels}</div>')
        for week in (0, 1):
            with st.container(horizontal=True, key=f"cal_week_{week}"):
                for day in dates[week * 7 : week * 7 + 7]:
                    theme = training_theme(profile, day, days)
                    tag = tr(*DAY_TAG[theme])
                    tone = "rest" if theme == "rest" else "cardio" if theme in CARDIO else "strength"
                    name = _theme_name(theme)
                    if row := logs.get(day.isoformat()):
                        missed = row["status"] == "missed"
                        tag = tr("漏", "Miss") if missed else "✓"
                        tone = "rest" if missed else "done"
                        name += " · " + (tr("漏练", "Missed") if missed else tr("已打卡", "Logged"))
                    marker = "_today" if day == today else ""
                    marker += "_selected" if day == selected else ""
                    description = f"{month_day(day)} · {name}"
                    if day == today:
                        description += tr(" · 今天", " · Today")
                    if day == selected:
                        description += tr(" · 已选", " · Selected")
                    st.button(f"**{day.day}**  \n{tag} *{description}*", key=f"cal_day_{day}_{tone}{marker}",
                              width="stretch", on_click=_select_day, args=(day,))



def _move_options(profile, day, today, days, logs):
    moving_out = day in days
    if day < today or day.isoformat() in logs:
        return []
    choices = []
    for i in range(14 - today.weekday()):
        candidate = today + timedelta(days=i)
        if candidate.isoformat() in logs or (candidate in days) == moving_out:
            continue
        origin, destination = (day, candidate) if moving_out else (candidate, day)
        if valid_training_move(profile, origin, destination, days - {origin}):
            choices.append((origin, destination))
    return choices


def _nutrition_rules():
    st.markdown(tr("全天静息代谢按成人 Mifflin–St Jeor 公式估算。平时乘活动系数；同步后改用全天静息代谢加已同步活动能量。性别留空时保留两种估算。",
                   "We estimate full-day resting energy with Mifflin–St Jeor. The plan uses an activity factor until you sync. After sync it uses resting energy plus recorded activity. Leaving sex blank keeps both estimates.") +
                " [Mifflin–St Jeor](https://pubmed.ncbi.nlm.nih.gov/2305711/)")
    st.caption(tr("本演示的目标系数（力量／有氧／休息）为减脂 0.90／0.90／0.80，增肌 1.14／1.14／1.05，重塑 1.03／0.95／0.88。运动员以及选择减脂或重塑的偏瘦用户按维持估算。非偏瘦减脂和重塑目标至少取全天静息代谢，女性至少 1200、男性至少 1500 kcal。",
                  "Demo factors for strength / cardio / rest are 0.90 / 0.90 / 0.80 for fat loss, 1.14 / 1.14 / 1.05 for muscle gain and 1.03 / 0.95 / 0.88 for recomposition. Athletes and underweight users choosing fat loss or recomposition use maintenance. For those goals with BMI ≥18.5, targets are at least resting energy and 1200 kcal (female) or 1500 kcal (male)."))
    st.caption(tr("减脂、增肌、重塑的蛋白参考量分别为 2.0、1.7、2.1 g/kg；久坐且未排力量训练的重塑目标取 1.6。BMI 超过 25 时，用 BMI 25 对应体重加超出部分的 40% 计算。脂肪占 25%，重塑训练日 24%、休息日 30%，下限为每公斤参考体重 0.7 g。其余热量按每克碳水 4 kcal 分配。",
                  "Protein per reference kg is 2.0 g for fat loss, 1.7 g for muscle gain and 2.1 g for recomposition (1.6 g if inactive without strength sessions). Above BMI 25, reference weight includes 40% of the weight above the BMI-25 threshold. Fat gets 25% of energy, or 24% on recomposition training days and 30% at rest, with a floor of 0.7 g/kg. Remaining energy goes to carbs at 4 kcal/g."))


def _training_sources():
    _nutrition_rules()
    st.write(tr("同一重量下连续两次轻松完成目标，可增加一次重复。漏练后先减轻训练量；连续两次吃力或每第四周安排减量。重量参考你自己的记录。",
                "After two comfortable completions at the same load, the plan can add one rep. A missed session eases you back in. Two difficult sessions or every fourth week reduce volume. Loads come from your log."))
    st.markdown(tr("力量训练与有氧强度", "Strength and aerobic intensity") +
                " · [ACSM](https://acsm.org/resistance-training-guidelines-update-2026/) · [CDC](https://www.cdc.gov/physical-activity-basics/measuring/) · [NHS](https://www.nhs.uk/live-well/exercise/strength-exercises/)")
    st.markdown(tr("静息代谢、活动消耗与运动营养", "Resting energy, activity and nutrition") +
                " · [Cronometer](https://support.cronometer.com/hc/en-us/articles/31974307318420-Energy-Expenditure) · [NIH ODS](https://ods.od.nih.gov/factsheets/ExerciseandAthleticPerformance-HealthProfessional/)")


def _focus_card(profile, today, day, days, logs, diary, db_path, eaten, incomplete):
    plan = diary_day_plan(profile, day, days, db_path)
    theme = plan.theme if plan.training else "rest"
    tone = "recovery" if theme == "rest" else "cardio" if theme in CARDIO else "strength"
    existing = logs.get(day.isoformat(), {})
    lang = tr("zh", "en")
    session = session_for_day(profile, day, db_path=db_path, lang=lang)
    with st.container(key="training_focus", gap="small"):
        title = month_day(day) + (tr(" · 今天", " · Today") if day == today else "")
        badge = escape(_theme_name(theme))
        st.html(f'<div class="focus-heading"><h3>{escape(title)}</h3><span class="focus-badge {tone}">{badge}</span></div>')
        st.caption(tr(f"参考 {span(plan.kcal)} kcal · 蛋白 {plan.protein_g}\u00a0g · 碳水 {plan.carb_g}\u00a0g · 脂肪 {plan.fat_g}\u00a0g",
                      f"{span(plan.kcal)} kcal · Protein {plan.protein_g}\u00a0g · Carbs {plan.carb_g}\u00a0g · Fat {plan.fat_g}\u00a0g"))
        if day == today and eaten is not None:
            prefix = tr("已记小计", "Logged subtotal") if incomplete else tr("已记", "Logged")
            st.caption(prefix + tr(f" {eaten['kcal']:.0f} kcal · 蛋白 {eaten['protein_g']:.0f}\u00a0g · 碳水 {eaten['carb_g']:.0f}\u00a0g · 脂肪 {eaten['fat_g']:.0f}\u00a0g",
                                   f" {eaten['kcal']:.0f} kcal · Protein {eaten['protein_g']:.0f}\u00a0g · Carbs {eaten['carb_g']:.0f}\u00a0g · Fat {eaten['fat_g']:.0f}\u00a0g"))
        if existing:
            status = {"missed": ("漏练", "Missed"), "comfortable": ("✓ 顺利完成", "✓ Completed comfortably"),
                      "challenging": ("✓ 已打卡 · 体感吃力", "✓ Logged · Challenging")}
            st.markdown("**" + tr(*status[existing["status"]]) + "**")
            if existing["actuals"]:
                _actual_summary(existing, lang)
        if theme == "rest":
            st.write(tr(ACTIVITIES[profile.activity].recovery, ACTIVITY_EN[profile.activity].rest))
        else:
            lines = session_lines(session, lang)
            st.caption(tr(f"本节约 {session['planned_minutes']} 分钟", f"About {session['planned_minutes']} min"))
            if session["mode"] == "cardio":
                parts = lines[1].split(" · ")
            else:
                parts = lines[1:]
                if theme == "general":
                    parts.insert(0, tr("热身 · 徒手浅蹲和轻松绕肩", "Warm-up · Mini squats and arm circles"))
            rows = "".join(f"<li>{escape(line)}</li>" for line in parts)
            st.html(f'<ul class="focus-exercises">{rows}</ul>')

        preview = st.session_state.get("training_move_preview")
        if preview and preview[0] == diary:
            _review_date(profile, *preview[1:], db_path)
            return
        options = _move_options(profile, day, today, days, logs)
        action = st.session_state.get("training_action")
        with st.container(horizontal=True, gap="small"):
            if day <= today and day in days:
                label = tr("修改打卡", "Edit workout log") if existing else tr("✓ 完成打卡 / 记一组", "✓ Log workout / a set")
                st.button(label, key="open_workout_log", type="primary", on_click=st.session_state.update,
                          args=({"training_action": None if action == "log" else "log"},))
            if options:
                if day not in days:
                    move = tr("把训练挪到这天", "Move a workout here")
                elif day == today:
                    move = tr("换一天练", "Change day")
                else:
                    move = tr("换到其他休息日", "Move to a rest day")
                st.button(move, key="open_move_days", on_click=st.session_state.update,
                          args=({"training_action": None if action == "move" else "move"},))
        if action == "log" and day <= today and day in days:
            _training_log_ui(profile, day, today, session, existing, db_path)
        elif action == "move" and options:
            st.caption(tr("选休息日", "Choose a rest day") if day in days else tr("选要移过来的训练", "Choose a workout"))
            with st.container(horizontal=True, gap="xsmall", key="move_choices"):
                for origin, destination in options:
                    candidate = destination if day in days else origin
                    label = month_day(candidate)
                    if day not in days:
                        label += " · " + _theme_name(training_theme(profile, origin, days))
                    if st.button(label, key=f"move_option_{candidate}"):
                        _preview_date(profile, origin, destination, days, diary, db_path)
        elif day in days and day >= today and not existing and not options:
            st.caption(tr("近期暂无符合安排的休息日。", "No available rest day fits this schedule."))


def _dismiss_training_dialog():
    st.session_state.pop("training_dialog", None)


def training_plan(profile, today, days, db_path, *, eaten=None, incomplete=False):
    diary = (str(db_path), st.session_state.get("diary_token"), today)
    monday = today - timedelta(days=today.weekday())
    dates = [monday + timedelta(days=i) for i in range(14)]
    if st.session_state.get("calendar_diary") != diary:
        st.session_state.calendar_diary = diary
        _dismiss_training_dialog()
        st.session_state.pop("offered_training_setup", None)
        _select_day(today)
    day = st.session_state.selected_day
    logs = {r["date"]: r for r in read_logs(monday, today + timedelta(days=13), db_path=db_path)}
    with st.container(horizontal=True, vertical_alignment="center", key="training_header"):
        st.subheader(tr("训练安排", "Training schedule"))
        settings_clicked = st.button(tr("⚙ 课表设置", "⚙ Schedule settings"), key="calendar_settings")
    setup = st.session_state.pop("edit_training_setup", False) or settings_clicked
    if not profile.training and not st.session_state.get("offered_training_setup"):
        st.session_state.offered_training_setup = True
        setup = True
    _calendar_grid(profile, today, day, dates, days, logs)
    _focus_card(profile, today, day, days, logs, diary, db_path, eaten, incomplete)
    sources = tr("进度规则与文献依据", "Progression rules and sources")
    if setup:
        st.session_state.training_dialog = "setup"
    if st.button(sources, type="tertiary", key="training_sources"):
        st.session_state.training_dialog = "sources"
    opened = st.session_state.get("training_dialog")
    if opened == "sources":
        st.dialog(sources, on_dismiss=_dismiss_training_dialog)(_training_sources)()
    elif opened == "setup":
        st.dialog(tr("课表设置", "Schedule settings"), on_dismiss=_dismiss_training_dialog)(_setup_form)(profile, today, db_path)


def calendar_for_view(profile, today, db_path):
    last = today + timedelta(days=13)
    monday = today - timedelta(days=today.weekday())
    return planned_days(profile, profile.week_start(monday) - timedelta(days=1),
                        profile.week_start(last) + timedelta(days=7), db_path=db_path)


def settings(profile, db_path, public_demo):
    with st.expander(tr("个人设置与估算依据", "Settings and estimates")):
        if profile:
            st.write(f"{activity_label(profile.activity)} · {goal_label(profile.goal)}")
            if profile.maintenance_guard:
                st.caption(tr("按这份身体或训练资料，体验版继续以维持体重估算。",
                              "With your current profile, this demo uses a weight-maintenance estimate."))
            if st.button(tr("修改我的资料和目标", "Edit profile and goals")):
                st.session_state.edit_profile = True
                st.rerun()
            if profile.goal == "recomp":
                st.caption(tr("可以从每周安排 2–3 次适合自己的力量练习开始。", "Try scheduling two or three strength sessions a week at a comfortable level."))
            _nutrition_rules()
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
                for key in ("guest", "saved", "draft", "edit_profile", "mituan_state", "edit_training_setup",
                            "training_move_preview"):
                    st.session_state.pop(key, None)
                for key in ("receipt", "capture_ack", "active_draft", "section"):
                    st.session_state.pop(key, None)
                st.session_state.notice = tr("这份档案、训练安排和餐食记录已清除。",
                                             "Your profile, training schedule and meal records have been cleared.")
                st.rerun()
