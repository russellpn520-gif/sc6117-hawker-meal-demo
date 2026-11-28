import base64
import binascii
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from api_credentials import read_api_key, save_windows_key
from device_diary import cloud_diary
from meal_review import review_meal
from meals import (
    SG_TIME, create_pending, discard_pending, get_pending, get_profile, list_meals, list_pending,
    load_foods, make_draft, match_text, save_meal, total_nutrients, update_pending,
)
from mobile_ui import apply_mobile_style, day_strip, meal_history, saved_receipt
from photo_tasks import start_recognition
from plan_ui import calendar_for_view, day_summary, profile_form, settings, training_plan
from planning import day_plan
from recognition import prepare_photo


ROOT = Path(__file__).resolve().parent
photo_picker = st.components.v2.component(
    "meal_camera", html=(ROOT / "capture.html").read_text("utf-8"), js=(ROOT / "capture.js").read_text("utf-8")
)


def photo_api_key(*, use_qwen):
    if use_qwen:
        key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
        if not key:
            try:
                key = st.secrets.get("DASHSCOPE_API_KEY", "").strip()
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


def capture_meal(db_path, public_demo):
    device = st.session_state.get("diary_token", "session" if public_demo else "local")
    provider = "阿里云千问" if public_demo or os.environ.get("DASHSCOPE_API_KEY") else "OpenAI"
    st.caption(f"选图后由{provider}识别。先留作草稿，吃完再确认。")
    result = photo_picker(key="capture_meal", data={"device": device, "ack": st.session_state.get("capture_ack")},
                          default={"capture": None}, on_capture_change=lambda: None)
    record = result.capture
    if (not isinstance(record, dict) or record.get("device") != device
            or record.get("id") == st.session_state.get("capture_ack")):
        return
    try:
        key = str(UUID(record["id"]))
        encoded = record["jpeg"]
        if not isinstance(encoded, str) or len(encoded) > 2_000_000:
            raise ValueError("invalid photo")
        jpeg = prepare_photo(base64.b64decode(encoded, validate=True))
    except (ValueError, KeyError, TypeError, AttributeError, binascii.Error):
        st.error("这张图片无法读取，请重新拍照或选择其他图片。")
        if record.get("id"):
            st.session_state.capture_ack = record["id"]
            st.session_state.notice = "这张照片未能保存，请重新选择。"
            st.rerun()
        return
    draft = make_draft("photo", "餐食照片", {}, [])
    draft.update(id=key, captured_at=record.get("captured_at"))
    new = create_pending(draft, jpeg, db_path=db_path)
    st.session_state.capture_ack = record["id"]
    if new:
        st.session_state.active_draft = key
        st.session_state.pop("receipt", None)
    st.rerun()


def text_entry(db_path, draft=None):
    key = draft["id"] if draft else "new"
    with st.form(f"by-name-{key}", clear_on_submit=True):
        name = st.text_input("这餐吃了什么？", placeholder="例如 白饭、鸡蛋", max_chars=400)
        submitted = st.form_submit_button("查找并加入草稿", width="stretch")
    if submitted and name.strip():
        matched = match_text(name.strip(), load_foods())
        matched["status"] = "ready"
        if draft:
            matched["id"] = draft["id"]
            matched["input"]["method"] = "photo"
            update_pending(matched, db_path=db_path)
        else:
            create_pending(matched, db_path=db_path)
        st.session_state.active_draft = matched["id"]
        st.session_state.pop("receipt", None)
        st.rerun()


@st.fragment(run_every=2)
def wait_for_recognition(key, db_path, api_key, use_qwen):
    draft = get_pending(key, db_path=db_path)
    if not draft or draft["status"] != "queued":
        st.rerun()
    start_recognition(key, db_path, api_key, use_qwen)
    st.caption("正在识别。可以先锁屏，吃完再回来。")


def review_pending(draft, db_path, public_demo):
    if draft["photo"]:
        st.image(draft["photo"], width=220, alt="这餐的照片")
    status = draft["status"]
    if status == "queued":
        use_qwen = public_demo or bool(os.environ.get("DASHSCOPE_API_KEY", "").strip())
        api_key = photo_api_key(use_qwen=use_qwen)
        wait_for_recognition(draft["id"], db_path, api_key, use_qwen)
    elif status == "failed":
        st.caption(draft.get("error") or "照片已保存，可重试识别或补填菜名。")
        if st.button("重新识别", key="retry-" + draft["id"]):
            update_pending({**draft, "status": "queued"}, db_path=db_path)
            st.rerun()
        text_entry(db_path, draft)
    else:
        confirmed = review_meal(draft)
        if confirmed:
            payload, items = confirmed
            if save_meal(payload, items, db_path=db_path):
                st.session_state.receipt = {
                    "totals": total_nutrients([i["nutrients"] for i in items]), "date": draft["captured_at"][:10],
                }
            else:
                st.session_state.notice = "这餐已在另一处处理。"
            st.rerun()
    with st.expander("管理这份草稿"):
        if st.button("放弃这份草稿", key="discard-" + draft["id"]):
            discard_pending(draft["id"], db_path=db_path)
            st.session_state.notice = "草稿已移除。"
            st.rerun()


def draft_label(draft):
    stamp = datetime.fromisoformat(draft["captured_at"]).astimezone(SG_TIME)
    keys = draft["input"].get("suggested_grams", {})
    names = [load_foods()[k].name for k in keys if k in load_foods()][:2]
    return f"{stamp.month}/{stamp.day} {stamp:%H:%M}　" + ("、".join(names) if names else "餐食草稿")


def home(db_path, public_demo, today, profile, plan, eaten):
    pending = list_pending(db_path=db_path)
    if receipt := st.session_state.get("receipt"):
        current = receipt["date"] == today.isoformat()
        saved_receipt(receipt, plan if current else None, eaten)
        if not current:
            st.caption(f"用餐日期 {receipt['date']}")
    if pending:
        st.subheader("待确认的餐")
        docs = {d["id"]: d for d in pending}
        chosen = st.session_state.get("active_draft")
        if chosen not in docs:
            chosen = pending[0]["id"]
        if len(docs) > 1:
            chosen = st.selectbox("选择待确认的餐", list(docs), index=list(docs).index(chosen),
                                  format_func=lambda i: draft_label(docs[i]))
        else:
            st.caption(draft_label(docs[chosen]))
        review_pending(docs[chosen], db_path, public_demo)
        with st.expander("再记一餐"):
            capture_meal(db_path, public_demo)
            text_entry(db_path)
    else:
        st.subheader("记录一餐")
        capture_meal(db_path, public_demo)
        with st.expander("按菜名记餐"):
            text_entry(db_path)
    if profile:
        day_strip(today, plan, eaten)
    elif st.button("建立个人计划", width="stretch"):
        st.session_state.edit_profile = True
        st.rerun()


def main(*, public_demo=False):
    st.set_page_config(page_title="食阁记餐", page_icon="🍚", layout="centered")
    apply_mobile_style()
    st.title("食阁记餐")
    db_path = cloud_diary() if public_demo else None
    today = datetime.now(SG_TIME).date()
    profile = get_profile(db_path=db_path)
    if notice := st.session_state.pop("notice", None):
        st.info(notice)
    if st.session_state.get("edit_profile"):
        profile_form(profile, today, db_path, public_demo)
        return
    records = list_meals(today, db_path=db_path)
    eaten = total_nutrients([r["totals"] for r in records])
    days = calendar_for_view(profile, today, db_path) if profile else ()
    plan = day_plan(profile, today, days) if profile else None
    sections = ["记餐", "日记"] + (["训练安排"] if profile else [])
    section = st.segmented_control("打开", sections, default="记餐", key="section",
                                   label_visibility="collapsed") or "记餐"
    if st.session_state.get("device_storage_blocked"):
        st.info("此浏览器限制了设备存储。请允许网站数据后再拍照，以便重新打开时找回草稿。")
    elif st.session_state.get("draft_backup_limited"):
        st.caption("浏览器的备份空间不足。先确认已有草稿可腾出空间。")
    if section == "记餐":
        home(db_path, public_demo, today, profile, plan, eaten)
    elif section == "训练安排":
        training_plan(profile, today, days, db_path)
        with st.expander("今日目标明细"):
            day_summary(profile, today, plan, eaten)
    else:
        day = st.date_input("用餐日期", value=today, max_value=today)
        meal_history(records if day == today else list_meals(day, db_path=db_path), day=day)
    settings(profile, db_path, public_demo)


if __name__ == "__main__":
    try:
        main()
    except sqlite3.Error:
        st.error("暂时无法读写记餐记录，请稍后重试。")
