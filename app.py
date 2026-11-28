import base64
import binascii
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import streamlit as st

from photo_access import photo_api_key
from coach_ui import coach_entry, open_dinner
from device_diary import cloud_diary
from i18n import food_name, language_switch, tr
from meal_review import review_meal
from meal_memory import suggest_corrections, usual_meals_ui
from label_ui import review_label
from meals import (
    SG_TIME, IncompleteMealError, MealChangedError, create_pending, discard_pending, get_pending, get_profile,
    list_meals, list_pending,
    load_foods, make_draft, match_text, save_meal, total_nutrients, update_pending,
)
from mobile_ui import apply_mobile_style, coverage_status, day_strip, diary_rhythm, meal_history, saved_receipt
from photo_tasks import start_recognition
from plan_ui import calendar_for_view, day_summary, profile_form, settings, training_plan
from planning import day_plan
from recognition import prepare_photo
from sample_meal import start_practice


ROOT = Path(__file__).resolve().parent
photo_picker = st.components.v2.component(
    "meal_camera", html=(ROOT / "capture.html").read_text("utf-8"), js=(ROOT / "capture.js").read_text("utf-8")
)


def capture_meal(db_path, public_demo):
    device = st.session_state.get("diary_token", "session" if public_demo else "local")
    modes = {"photo": tr("餐盘", "Meal"), "label": tr("包装营养标签", "Nutrition label")}
    mode = st.segmented_control(tr("拍什么？", "What are you photographing?"), list(modes),
                                format_func=modes.__getitem__, default="photo", key="capture_mode",
                                label_visibility="collapsed") or "photo"
    result = photo_picker(key="capture_meal", data={"device": device, "mode": mode, "ack": st.session_state.get("capture_ack"),
                                                  "lang": st.session_state.get("ui_lang", "zh")},
                          default={"capture": None}, on_capture_change=lambda: None)
    if mode == "label":
        hint = tr("拍清营养成分表和份量单位。", "Include the panel and serving units.")
    else:
        hint = tr("先拍照，吃完再确认。", "Take a photo now and confirm after eating.")
    access = (tr("OpenAI 识别首次需组员码。", "The first OpenAI scan needs a team access code.") if public_demo
              else tr("照片由 OpenAI 识别。", "OpenAI scans the photo."))
    st.caption(f"{hint} {access}")
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
        st.error(tr("这张图片无法读取，请重新拍照或选择其他图片。", "Could not read this photo. Retake it or choose another image."))
        if record.get("id"):
            st.session_state.capture_ack = record["id"]
            st.session_state.notice = tr("这张照片未能保存，请重新选择。", "Could not save this photo. Please choose it again.")
            st.rerun()
        return
    method = "label" if record.get("mode") == "label" else "photo"
    draft = make_draft(method, "包装营养标签" if method == "label" else "餐食照片", {}, [])
    draft["input"]["ui_lang"] = st.session_state.get("ui_lang", "zh")
    if method == "photo" and isinstance(record.get("portion_hint"), str):
        draft["input"]["portion_hint"] = record["portion_hint"].strip()[:150]
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
        name = st.text_input(tr("这餐吃了什么？", "What did you eat?"), placeholder=tr("例如 白饭、鸡蛋", "e.g. white rice, boiled egg"), max_chars=400)
        submitted = st.form_submit_button(tr("查找并加入草稿", "Find foods and create draft"), width="stretch")
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
def wait_for_recognition(key, db_path, api_key):
    draft = get_pending(key, db_path=db_path)
    if not draft or draft["status"] != "queued":
        st.rerun()
    start_recognition(key, db_path, api_key)
    st.caption(tr("正在识别。可以先锁屏，吃完再回来。", "Identifying the food. You can lock your phone and return after eating."))


def review_pending(draft, db_path, public_demo):
    is_label = draft["input"].get("method") == "label"
    if draft["photo"] and draft["input"].get("sample"):
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.image(draft["photo"], width=88, alt=tr("示例烧鸡、油饭和清汤", "Sample roast chicken, seasoned rice and broth"))
            st.caption(tr("示例鸡饭 · 剩半碗饭？只调米饭就好。", "Sample chicken rice · Half the rice left? Just adjust the rice."))
    elif draft["photo"]:
        with st.expander(tr("查看包装标签", "View package label") if is_label else tr("查看这餐的照片", "View meal photo"),
                         expanded=is_label):
            st.image(draft["photo"], width="stretch",
                     alt=tr("包装营养标签", "Package nutrition panel") if is_label else tr("这餐的照片", "Photo of your meal"))
    status = draft["status"]
    if status == "queued":
        api_key = photo_api_key(public_demo=public_demo)
        if api_key:
            wait_for_recognition(draft["id"], db_path, api_key)
        elif not is_label:
            text_entry(db_path, draft)
    elif status == "failed":
        st.caption(tr(draft.get("error") or "照片已保存，可重试识别或补填菜名。",
                      draft.get("error_en") or "Photo saved. Retry recognition or log the foods by name."))
        if st.button(tr("重新识别", "Retry recognition"), key="retry-" + draft["id"]):
            update_pending({**draft, "status": "queued"}, db_path=db_path)
            st.rerun()
        if not is_label:
            text_entry(db_path, draft)
    else:
        if not is_label and draft["input"].get("method") == "photo":
            suggest_corrections(draft, load_foods(), db_path)
        confirmed = review_label(draft, db_path) if is_label else review_meal(draft, db_path)
        if confirmed:
            payload, items = confirmed
            try:
                saved = save_meal(payload, items, db_path=db_path)
            except MealChangedError:
                st.session_state.notice = tr("这餐的饮品刚刚有更新。请看一眼份量，再确认记餐。",
                                             "This meal’s drinks changed. Check the updated portions and confirm.")
                st.rerun()
            except IncompleteMealError as exc:
                st.warning(tr(str(exc), "Some foods still need a match. Review them or explicitly save a partial meal."))
                return
            if saved:
                st.session_state.receipt = {
                    "totals": total_nutrients([i["nutrients"] for i in items]), "date": draft["captured_at"][:10],
                    "input": payload["input"], "items": items, "confirmed_on": datetime.now(SG_TIME).date().isoformat(),
                }
            else:
                st.session_state.notice = tr("这餐已在另一处处理。", "This meal has already been handled in another tab.")
            st.rerun()
    if is_label and status in ("queued", "failed"):
        if st.button(tr("按包装手动填写", "Enter label values manually"), key="manual-label-"+draft["id"]):
            update_pending({**draft, "status": "ready"}, db_path=db_path)
            st.rerun()
    with st.expander(tr("管理这份草稿", "Manage draft")):
        if st.button(tr("放弃这份草稿", "Discard this draft"), key="discard-" + draft["id"]):
            discard_pending(draft["id"], db_path=db_path)
            st.session_state.notice = tr("草稿已移除。", "Draft removed.")
            st.rerun()


def draft_label(draft, *, time_only=False):
    stamp = datetime.fromisoformat(draft["captured_at"]).astimezone(SG_TIME)
    when = tr(stamp.strftime("%m/%d %H:%M"), stamp.strftime("%d %b %H:%M"))
    if time_only:
        return when
    if draft["input"].get("method") == "label":
        name = (draft["input"].get("label") or {}).get("product_name") or tr("包装营养标签", "Nutrition label")
    elif draft["input"].get("unmatched_foods"):
        name = tr("有食物待补选", "Food still to match")
    else:
        keys = draft["input"].get("suggested_grams", {})
        foods = load_foods() if keys else {}
        names = [food_name(foods[k]) for k in keys if k in foods][:2]
        name = tr("、", ", ").join(names) or tr("餐食草稿", "Meal draft")
    return f"{when} · {name}"


def meal_entry(db_path, public_demo):
    if not st.session_state.get("practice_mode"):
        capture_meal(db_path, public_demo)
        if st.button(tr("没带饭？用示例鸡饭试走一遍（免码）", "Try with a sample chicken rice photo (no code needed)"),
                     key="sample_chicken", width="stretch"):
            _, key = start_practice(db_path, datetime.now(SG_TIME).date(), restart=True)
            _switch_practice(True, key)
    with st.expander(tr("按菜名记餐", "Log by food name")):
        text_entry(db_path)
    usual_meals_ui(db_path)


def _switch_practice(enabled, draft_id=None):
    st.session_state.section = "记餐"
    for key in ("active_draft", "receipt", "mituan_state", "edit_profile", "edit_training_setup",
                "training_move_preview", "notice"):
        st.session_state.pop(key, None)
    if draft_id:
        st.session_state.active_draft = draft_id
    if enabled:
        st.query_params["practice"] = "1"
    elif "practice" in st.query_params:
        del st.query_params["practice"]
    st.rerun()


def next_meal_due(records, now):
    # A late confirmation can belong to an earlier meal. Old entries only have
    # a confirmation timestamp, which is the closest available fallback.
    def meal_time(record):
        stamp = record["at"]
        if raw := record["input"].get("captured_at"):
            try:
                stamp = datetime.fromisoformat(raw)
            except (TypeError, ValueError):
                pass
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=SG_TIME)

    return bool(records and now - max(map(meal_time, records)) >= timedelta(hours=3))


def home(db_path, public_demo, today, profile, plan, eaten, records, partial_count, legacy_count):
    pending = list_pending(db_path=db_path)
    if pending:
        with st.container(key="home_pending"):
            pending_review(pending, db_path, public_demo)
        with st.expander(tr("再记一餐", "Start another meal")):
            meal_entry(db_path, public_demo)
        return

    receipt = st.session_state.get("receipt")
    just_saved = bool(receipt and receipt.get("confirmed_on", receipt["date"]) == today.isoformat())
    if records or just_saved:
        with st.container(key="home_after"):
            saved_receipt(receipt if just_saved else records[0], just_saved=just_saved)
            if just_saved and receipt["date"] != today.isoformat():
                st.caption(tr(f"用餐日期 {receipt['date']}", f"Meal date · {receipt['date']}"))
            day_strip(today, plan, eaten, len(records), partial_count, legacy_count)
            st.button(tr("看晚餐建议", "Plan dinner"), on_click=open_dinner, key="home_dinner",
                      type="primary", width="stretch")
        now = datetime.now(SG_TIME)
        next_meal = next_meal_due(records, now)
        with st.expander(tr("记下一餐", "Log the next meal"), expanded=next_meal):
            meal_entry(db_path, public_demo)
    else:
        with st.container(key="home_before"):
            st.subheader(tr("记录一餐", "Log a meal"))
            meal_entry(db_path, public_demo)
        if profile:
            with st.expander(tr("今天的目标", "Today's targets")):
                day_strip(today, plan, eaten, 0)
    if not profile and st.button(tr("建立个人计划", "Create a personal plan"), width="stretch"):
        st.session_state.edit_profile = True
        st.rerun()


def pending_review(pending, db_path, public_demo):
    count = len(pending)
    st.subheader(tr("待确认的餐", "Meal to confirm") if count == 1
                 else tr(f"{count} 餐待确认", f"{count} meals to confirm"))
    docs = {d["id"]: d for d in pending}
    chosen = st.session_state.get("active_draft")
    if chosen not in docs:
        chosen = pending[0]["id"]
    if count > 1:
        chosen = st.selectbox(tr("选择待确认的餐", "Choose a draft"), list(docs), index=list(docs).index(chosen),
                              format_func=lambda i: draft_label(docs[i]))
    else:
        st.caption(draft_label(docs[chosen], time_only=True))
    review_pending(docs[chosen], db_path, public_demo)


def _choose_section(control, sections):
    chosen = st.session_state.get(control)
    if chosen in sections:
        st.session_state.section = chosen


def navigation(has_plan):
    sections = ["记餐", "日记"] + (["训练安排"] if has_plan else [])
    current = st.session_state.get("section", "记餐")
    if current not in sections:
        current = "记餐"
    st.session_state.section = current
    titles = {"记餐": tr("记餐", "Log"), "日记": tr("日记", "Diary"), "训练安排": tr("训练安排", "Training")}
    # The browser serializes translated labels. Remount with an explicit
    # default when the route or language changes, including shortcut jumps.
    control = f"diary_nav_{st.session_state.ui_lang}_{current}"
    st.segmented_control(tr("打开", "Navigate"), sections, format_func=titles.__getitem__,
                         default=current, required=True, key=control, label_visibility="collapsed",
                         on_change=_choose_section, args=(control, sections))
    return current


def main(*, public_demo=False):
    st.set_page_config(page_title="Meal Diary · 食阁记餐", page_icon="🍚", layout="centered")
    apply_mobile_style()
    with st.container(key="meal_header", horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        title = st.empty()
        language_switch()
        title.title(tr("食阁记餐", "Meal Diary"))
    db_path = cloud_diary() if public_demo else None
    today = datetime.now(SG_TIME).date()
    practice = st.query_params.get("practice") == "1"
    st.session_state.practice_mode = practice
    if practice:
        db_path, _ = start_practice(db_path, today)
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
    section = navigation(bool(profile))
    if practice:
        st.caption(tr("示例日记 · 今天的训练与营养目标用于试玩。", "Practice diary · Today's workout and targets are examples."))
    if st.session_state.get("device_storage_blocked"):
        st.info(tr("此浏览器限制了设备存储。请允许网站数据后再拍照，以便重新打开时找回草稿。", "Allow website data in this browser to recover meal drafts after reopening."))
    elif st.session_state.get("draft_backup_limited"):
        st.caption(tr("浏览器的备份空间不足。先确认已有草稿可腾出空间。", "Browser backup storage is full. Confirm existing drafts to free up space."))
    statuses = [coverage_status(record) for record in records]
    partial_count, legacy_count = statuses.count("partial"), statuses.count("legacy_review")
    if section == "记餐":
        home(db_path, public_demo, today, profile, plan, eaten, records, partial_count, legacy_count)
    elif section == "训练安排":
        training_plan(profile, today, days, db_path)
        with st.expander(tr("今日目标明细", "Today's targets")):
            day_summary(profile, today, plan, eaten, partial_count=partial_count, legacy_count=legacy_count)
    else:
        diary_rhythm(today, db_path=db_path)
        day = st.date_input(tr("用餐日期", "Meal date"), value=today, max_value=today)
        meal_history(records if day == today else list_meals(day, db_path=db_path), day=day, db_path=db_path)
    if practice:
        if st.button(tr("结束试玩，回到我的日记", "Leave practice and return to my diary"), key="leave_practice"):
            _switch_practice(False)
    else:
        settings(profile, db_path, public_demo)
    coach_entry(today, db_path, public_demo)


if __name__ == "__main__":
    try:
        main()
    except sqlite3.Error:
        st.error(tr("暂时无法读写记餐记录，请稍后重试。", "Could not access the diary. Please try again shortly."))
