"""One daily activity total from an iPhone shortcut or an explicitly selected example."""
import re

import streamlit as st

from i18n import tr
from meals import clear_health, sync_health
from planning import CARDIO, span


SYNC_KEYS = ("health_active", "health_steps")
APP_URL = "https://sc6117-hawker-meal.streamlit.app/"


def import_health_link(day, db_path):
    params = st.query_params
    if not any(key in params for key in SYNC_KEYS):
        return
    raw, counts = (params.get_all(key) for key in SYNC_KEYS)
    try:
        if len(raw) != 1 or not re.fullmatch(r"[0-9]{1,6}(?:[.][0-9]+)?", raw[0]):
            raise ValueError("activity")
        if counts and (len(counts) != 1 or not re.fullmatch(r"[0-9]{1,6}", counts[0])):
            raise ValueError("steps")
        active = float(raw[0])
        steps = int(counts[0]) if counts else None
        sync_health(day, active, steps, "apple_shortcut", db_path=db_path)
    except ValueError:
        message = tr("同步链接里的数值无效。请使用今天的活动千卡和整数步数，再运行快捷指令。",
                     "The sync link contains invalid values. Run the shortcut with today’s active kcal and whole steps.")
    else:
        message = tr(f"已同步今日健康数据 · 活动消耗 {active:g} kcal", f"Health synced today · {active:g} active kcal")
        if steps is not None:
            message += tr(f" · {steps:,} 步", f" · {steps:,} steps")
    for key in SYNC_KEYS:
        if key in params:
            del params[key]
    st.session_state.notice = message


def _sync_panel(day, db_path, health):
    st.markdown("**" + tr("从 iPhone 同步", "Sync from iPhone") + "**")
    suffix = "&practice=1" if st.session_state.get("practice_mode") else ""
    template = APP_URL + "?health_active=" + tr("[活动能量]", "[ActiveEnergy]") + "&health_steps=" + tr("[步数]", "[Steps]") + suffix
    st.code(template, language=None, wrap_lines=True)
    st.markdown(tr(
        "1. 打开 iPhone「快捷指令」，新建指令，添加「查找健康样本」。\n"
        "2. 选择「活动能量」，筛选今天、单一设备来源，用「计算统计数据」求和（kcal）。\n"
        "3. 步数可选。按相同方法取今天一个来源的步数总和，或删除链接中的 &health_steps=[步数]。\n"
        "4. 添加「URL」，把方括号替换为无单位、无千位分隔的数字变量，再用「打开 URL」在平时记餐的 Safari 中打开。首次运行时允许读取。",
        "1. In iPhone Shortcuts, create a shortcut and add Find Health Samples.\n"
        "2. Choose Active Energy, filter to today and one device source, then use Calculate Statistics → Sum in kcal.\n"
        "3. Optionally repeat for today’s steps from one source, or remove &health_steps=[Steps] from the link.\n"
        "4. Add URL, replace the brackets with number variables without units or grouping separators, and Open URLs in the Safari browser you use for this diary. Allow access on first run."))
    st.caption(tr("链接含当天汇总，仅在自己的浏览器打开。再次同步会替换今天的数值。", "The link contains your daily totals. Open it in your own browser. A new sync replaces today’s reading."))
    if st.button(tr("用示例 Apple Watch 数据试看（活动 460 kcal · 8,600 步）",
                    "Try sample Apple Watch data (460 active kcal · 8,600 steps)"), key="sample_watch", width="stretch"):
        sync_health(day, 460, 8600, "sample_watch", db_path=db_path)
        st.rerun()
    if health and st.button(tr("清除今日同步，恢复计划估算", "Clear today’s sync and restore plan estimates"),
                            key="clear_health", width="stretch"):
        clear_health(day, db_path=db_path)
        st.rerun()


def sync_button(day, db_path, health):
    label = tr("✓ 已同步健康", "✓ Health synced") if health else tr("↻ 同步健康数据", "↻ Sync health")
    if st.button(label, key="sync_health", type="tertiary"):
        st.dialog(tr("获取个人健康数据", "Sync personal health data"))(_sync_panel)(day, db_path, health)


def energy_ledger(plan, eaten, health, partial):
    if not health:
        return
    activity = tr(f"活动 {health.active_kcal:g} kcal", f"{health.active_kcal:g} active kcal")
    if health.steps is not None:
        activity += tr(f" · {health.steps:,} 步", f" · {health.steps:,} steps")
    if not plan or plan.output_kcal is None:
        st.caption(activity + tr(" · 建立个人计划后可估算总输出。", " · Create a personal plan to estimate expenditure."))
        return
    lo, hi = plan.output_kcal
    intake = round(eaten)
    balance = f"{intake - hi:+d}" if lo == hi else f"{intake - hi:+d} … {intake - lo:+d}"
    intake_label = tr("已记小计", "Subtotal") if partial else tr("已记摄入", "Logged intake")
    st.markdown(f"**{intake_label} {intake} − " + tr("输出 ", "output ") + span((lo, hi)) +
                tr(" = 差值 ", " = balance ") + f"{balance} kcal**")
    source = tr("示例手表", "Sample watch") if health.source == "sample_watch" else "Apple Health"
    st.caption(source + tr(f" · 全天基础代谢 {span(plan.bmr)} kcal + 截至同步时的",
                           f" · Full-day BMR {span(plan.bmr)} kcal + activity so far · ") + activity)
    if partial:
        return
    if plan.maintenance:
        note = tr("今天以维持为参考，照常安排下一餐。", "Today uses a maintenance estimate. Plan your next meal as usual.")
    elif plan.goal == "lose":
        note = tr("减脂目标已留出温和缺口。下一餐按下方参考量和自己的饱腹感来。", "Your fat-loss target already includes a deficit. Use the meal guide and your appetite for the next meal.")
    elif plan.goal == "gain":
        note = tr("今天为增肌留了一点余量，下一餐可以分配一些主食和蛋白质。", "Today’s muscle-gain target includes a little extra for your next meal.")
    elif plan.goal == "recomp" and plan.training and plan.theme not in CARDIO:
        note = tr("今天练力量，给下一餐留一些主食和蛋白质。", "It’s a strength day. Make room for carbs and protein at your next meal.")
    else:
        note = tr("今天的参考目标已按活动量更新，可以照自己的胃口安排下一餐。", "Your target now reflects recorded activity. Let your appetite guide the next meal.")
    st.caption(note)
