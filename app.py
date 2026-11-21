import hashlib
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from api_credentials import read_api_key, save_windows_key
from meals import (
    SG_TIME, list_meals, load_foods, match_text, portion_items, save_meal,
    schedule_workout, total_nutrients, workout_days,
)


FOODS = load_foods()
EXAMPLE = "白饭、水煮鸡"
# Fictional targets for demonstrating what a change of training day does.
TARGETS = {"训练日": (2200, 110), "休息日": (2000, 100)}


def photo_api_key(public_demo=False):
    if public_demo:
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            try:
                key = st.secrets.get("OPENAI_API_KEY", "").strip()
            except StreamlitSecretNotFoundError:
                pass
        if not key:
            st.info("照片识别尚未启用。现在可以选「按菜名查表」试用记餐。")
        return key
    try:
        api_key = read_api_key()
    except (OSError, UnicodeError):
        st.error("暂时无法读取 Windows 凭据。也可以在电脑上设置 OPENAI_API_KEY 后重新启动服务。")
        return ""

    # Use the server's bind address, independent of any browser-supplied headers.
    local_windows = sys.platform == "win32" and st.get_option("server.address") in {
        "127.0.0.1", "::1", "localhost",
    }
    if local_windows and not os.environ.get("OPENAI_API_KEY", "").strip():
        with st.expander("配置 OpenAI API Key", expanded=not api_key):
            st.caption("保存在这台电脑的 Windows 凭据管理器。"
                       " [打开 OpenAI 密钥管理页](https://platform.openai.com/api-keys)")
            with st.form("local_openai_key", clear_on_submit=True):
                value = st.text_input("OpenAI API Key", type="password", autocomplete="off")
                save = st.form_submit_button("保存密钥")
            if save:
                try:
                    save_windows_key(value)
                except (OSError, ValueError) as exc:
                    st.error(str(exc))
                else:
                    api_key = value.strip()
                    st.success("密钥已保存在本机。在 iPhone 上刷新页面即可上传照片。")
    elif not api_key:
        if sys.platform == "win32":
            st.info("先在电脑本机页面打开「照片识别」，保存 OpenAI API Key，然后刷新手机页面。")
        else:
            st.info("请在服务器设置 OPENAI_API_KEY 后重新启动应用。")
    return api_key


def input_draft(public_demo=False):
    mode = st.radio("录入方式", ["按菜名查表", "照片识别"], horizontal=True)
    current = st.session_state.draft
    if mode == "按菜名查表":
        text = st.text_input("这餐吃了什么？", value=EXAMPLE, max_chars=400,
                             help="用顿号分隔。例如「半份白饭、蒸鱼、水煮蛋」或「白饭 90g、水煮鸡」。")
        if st.button("查找食物", disabled=not text.strip()):
            current = match_text(text.strip(), FOODS)
            st.session_state.draft = current
        if current["input"]["method"] == "text" and current["input"]["description"] == text.strip():
            return current
        st.caption("修改描述后，点击「查找食物」更新待确认的项目。")
        return None

    api_key = photo_api_key(public_demo)
    if not api_key:
        return None
    upload = st.file_uploader("选择餐食照片", type=["jpg", "jpeg", "png"], max_upload_size=8)
    if upload is None:
        return None
    from recognition import identify_photo, prepare_photo

    raw = upload.getvalue()
    photo_hash = hashlib.sha256(raw).hexdigest()
    try:
        preview = prepare_photo(raw)
    except ValueError as exc:
        st.error(str(exc))
        return None
    st.image(preview, width=235)
    if st.button("发送照片给 OpenAI 识别"):
        from openai import AuthenticationError, OpenAIError, PermissionDeniedError, RateLimitError

        try:
            with st.spinner("正在匹配照片与食物表…"):
                current = identify_photo(preview, upload.name, FOODS, api_key=api_key)
            current["photo_hash"] = photo_hash
            st.session_state.draft = current
        except ValueError:
            st.error("识别结果格式有误，请重试或按菜名查表。")
            return None
        except AuthenticationError:
            st.error("OpenAI 未接受这个密钥。请由应用维护者检查 API Key。")
            return None
        except PermissionDeniedError:
            st.error("请检查这个 Key 所属项目的模型访问权限及 Responses API 调用权限。")
            return None
        except RateLimitError as exc:
            if exc.code == "insufficient_quota":
                st.error("这个 OpenAI API 项目的可用额度不足，请检查该项目的 API 计费设置。")
            else:
                st.error("已达到 OpenAI API 的请求限制，请稍后再试。")
            return None
        except OpenAIError:
            st.error("模型请求失败，请检查网络、模型权限和 API 额度，或按菜名查表。")
            return None
    if current.get("photo_hash") == photo_hash:
        show_token_usage(current["input"])
        return current
    return None


def set_grams(key, weight):
    st.session_state[key] = weight


def show_token_usage(original):
    usage = original.get("token_usage")
    if usage:
        st.caption(f"本次照片识别 · {original['model']} · 输入 {usage['input_tokens']:,} "
                   f"＋ 输出 {usage['output_tokens']:,} ＝ {usage['total_tokens']:,} tokens")


def edit_meal(draft, db_path=None):
    original = draft["input"]
    suggested = original["suggested_grams"]
    if original.get("question"):
        st.info(original["question"])
    unknown = original["unmatched"]
    acknowledged = True
    if unknown:
        st.warning("待核对或超出食物表的项目：" + "、".join(unknown))
        acknowledged = st.checkbox("我已核对，只将下方选中的项目计入这餐。", key=f"ack-{draft['id']}")
    selected = st.multiselect(
        "核对食物，可补选或移除", options=list(FOODS), default=list(suggested),
        format_func=lambda food_id: FOODS[food_id].name, key=f"foods-{draft['id']}",
    )
    if not selected:
        st.info("请从食物表中选择至少一项。")
        return
    if "chicken-rice-plate" in selected:
        st.caption("「鸡饭（整盘）」的克数包含鸡肉和油饭。半份整盘与单独减少米饭是两种份量。")

    weights = {}
    for food_id in selected:
        food = FOODS[food_id]
        quantity_key = f"grams-{draft['id']}-{food_id}"
        if quantity_key not in st.session_state:
            st.session_state[quantity_key] = suggested.get(food_id, food.serving_g)
        name, amount, shortcut = st.columns([1.6, 1, 0.8], vertical_alignment="center")
        name.markdown(f"**{food.name}**")
        name.caption(f"标准一份 {food.serving_g} g")
        weights[food_id] = amount.number_input(f"{food.name}重量（克）", min_value=1,
                                               max_value=3000, key=quantity_key)
        shortcut.button("半份", key=f"half-{draft['id']}-{food_id}",
                        on_click=set_grams, args=(quantity_key, food.serving_g // 2))
    items = portion_items(FOODS, weights)
    totals = total_nutrients([item["nutrients"] for item in items])
    st.divider()
    for col, (label, value) in zip(st.columns(4), [
        ("热量", f"{totals['kcal']:.0f} kcal"), ("蛋白质", f"{totals['protein_g']:.1f} g"),
        ("碳水", f"{totals['carb_g']:.1f} g"), ("脂肪", f"{totals['fat_g']:.1f} g"),
    ]):
        col.metric(label, value)
    st.caption("按参考份量折算。摊位用油、酱料和实际重量会影响结果。")
    with st.expander("查看食物数值与来源"):
        for item in items:
            ref = item["reference_nutrients"]
            st.markdown(
                f"**{item['name']}** · 每 {item['reference_g']} g 含 {ref['kcal']:g} kcal，"
                f"蛋白质 {ref['protein_g']:g} g，碳水 {ref['carb_g']:g} g，脂肪 {ref['fat_g']:g} g。"
                f" [HPB 附表 A · {item['source_name']}]({item['source_url']})"
            )
    if st.button("确认并记入今天", type="primary", disabled=not acknowledged):
        save_meal(draft, items, db_path=db_path)
        st.session_state.saved = True
        st.rerun()


def show_plan(today, records, db_path=None):
    tomorrow = today + timedelta(days=1)
    planned = workout_days(today, tomorrow, db_path=db_path)
    today_trains = today.isoformat() in planned
    tomorrow_trains = tomorrow.isoformat() in planned
    day_type = "训练日" if today_trains else "休息日"
    next_type = "训练日" if tomorrow_trains else "休息日"
    kcal_goal, protein_goal = TARGETS[day_type]
    consumed = total_nutrients([record["totals"] for record in records])

    st.subheader("今日安排")
    st.write(f"**{today:%m 月 %d 日} · {day_type}**")
    st.caption(f"示例目标 {kcal_goal} kcal · 蛋白质 {protein_goal} g")
    for label, left, unit in [
        ("热量", kcal_goal - consumed["kcal"], "kcal"),
        ("蛋白质", protein_goal - consumed["protein_g"], "g"),
    ]:
        st.metric(label + ("还差" if left >= 0 else "超出"), f"{abs(left):.0f} {unit}")
    st.divider()
    st.caption(f"明天 · {next_type} · {TARGETS[next_type][0]} kcal / {TARGETS[next_type][1]} g 蛋白质")
    if today_trains and not tomorrow_trains:
        label, destination, origin = "把今天的训练移到明天", tomorrow, today
    elif tomorrow_trains and not today_trains:
        label, destination, origin = "把明天的训练移到今天", today, tomorrow
    elif not today_trains:
        label, destination, origin = "今天安排一次训练", today, None
    else:
        st.caption("今天和明天均已有训练。")
        return
    if st.button(label):
        schedule_workout(destination, origin, db_path=db_path)
        st.rerun()


def show_history(records):
    st.subheader(f"今日记餐 · {len(records)} 笔")
    if not records:
        st.caption("确认第一餐后，这里会显示实际份量和营养小计。")
        return
    total = total_nutrients([record["totals"] for record in records])
    st.write(f"合计 **{total['kcal']:.0f} kcal** · 蛋白质 {total['protein_g']:.1f} g · "
             f"碳水 {total['carb_g']:.1f} g · 脂肪 {total['fat_g']:.1f} g")
    for record in records:
        items = record["items"]
        names = "、".join(item["name"] for item in items)
        with st.expander(f"{record['at']:%H:%M}　{names}　·　{record['totals']['kcal']:.0f} kcal"):
            original = record["input"]
            st.text(("查表输入" if original["method"] == "text" else "照片文件") + " · " + original["description"])
            show_token_usage(original)
            if original["unmatched"]:
                st.text("原始输入中待核对的项目 · " + "、".join(original["unmatched"]))
            for item in items:
                st.markdown(f"{item['name']} · {item['confirmed_g']} g · "
                            f"{item['nutrients']['kcal']:.0f} kcal　[数据出处]({item['source_url']})")


def main(*, public_demo=False):
    st.set_page_config(page_title="食阁记餐", page_icon="🍚", layout="wide")
    st.title("食阁记餐")
    db_path = None
    if public_demo:
        st.caption("公开体验版 · 餐食和训练安排仅在你当前的浏览器会话中保留。")
        if "log_directory" not in st.session_state:
            st.session_state.log_directory = TemporaryDirectory(prefix="sc6117-meals-")
        db_path = Path(st.session_state.log_directory.name) / "meals.sqlite3"
    today = datetime.now(SG_TIME).date()
    records = list_meals(today, db_path=db_path)
    if "draft" not in st.session_state:
        st.session_state.draft = match_text(EXAMPLE, FOODS)
    left, right = st.columns([1.85, 1], gap="large")
    with left.container(border=True):
        st.subheader("记录一餐")
        if st.session_state.get("saved"):
            st.success("已记入今天的餐食日志。")
            if st.button("再记一餐"):
                st.session_state.saved = False
                st.session_state.draft = match_text(EXAMPLE, FOODS)
                st.rerun()
        else:
            draft = input_draft(public_demo)
            if draft is not None:
                edit_meal(draft, db_path)
    with right.container(border=True):
        show_plan(today, records, db_path)
    show_history(records)


if __name__ == "__main__":
    try:
        main()
    except sqlite3.Error:
        st.error("无法读写本地记餐文件。请检查数据库所在目录或稍后重试。")
