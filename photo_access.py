"""Resolve server-side scan credentials and authorize free-text coach questions."""

import hmac
import sys
from contextlib import closing

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from api_credentials import local_setting, read_api_key, save_windows_key
from device_diary import _diary_path
from i18n import tr
from meals import open_db


def _cloud_secret(name):
    try:
        return str(st.secrets.get(name, "")).strip()
    except StreamlitSecretNotFoundError:
        return ""


def _device_authorized(code, device, *, grant=False):
    path = _diary_path(device)
    proof = hmac.digest(code.encode(), ("team-photo:" + (device or "session")).encode(), "sha256").hex()
    if path is None:
        if grant:
            st.session_state.photo_access_proof = proof
        return hmac.compare_digest(proof, st.session_state.get("photo_access_proof", ""))
    with closing(open_db(path)) as db, db:
        if grant:
            db.execute("INSERT OR REPLACE INTO photo_access VALUES (1, ?)", (proof,))
        row = db.execute("SELECT proof FROM photo_access WHERE id=1").fetchone()
    return bool(row and hmac.compare_digest(proof, row[0]))


def _local_photo_key(purpose="photo"):
    try:
        key = read_api_key()
    except (OSError, UnicodeError):
        key = ""
    if key or sys.platform != "win32":
        return key
    with st.expander(tr("配置本机 OpenAI 密钥", "Set up a local OpenAI key")):
        with st.form(f"local_openai_key_{purpose}", clear_on_submit=True):
            value = st.text_input("OpenAI API key", type="password", autocomplete="off",
                                  key=f"local_openai_input_{purpose}")
            if st.form_submit_button(tr("保存密钥", "Save key")):
                try:
                    save_windows_key(value)
                except (OSError, ValueError):
                    st.error(tr("密钥未保存，请检查输入或本机凭据管理器。", "Check the key and Windows Credential Manager."))
                else:
                    return value.strip()
    return ""


def photo_api_key(*, public_demo):
    return _team_api_key(public_demo, coach=False)


def coach_api_key(*, public_demo):
    return _team_api_key(public_demo, coach=True)


def _team_api_key(public_demo, *, coach):
    local_only = not public_demo and st.get_option("server.address") in {"127.0.0.1", "::1", "localhost"}
    if local_only:
        key = _local_photo_key("coach" if coach else "photo")
        if not key:
            st.info(tr("请配置 OpenAI 密钥以启用自由提问，快捷问题可以直接使用。", "Set up an OpenAI key for free-text questions. Quick actions are available.")
                    if coach else tr("照片已保存。请配置 OpenAI 密钥，或直接填写菜名。",
                                     "Photo saved. Set up an OpenAI key or enter the food names below."))
        return key

    get_setting = _cloud_secret if public_demo else local_setting
    key = get_setting("OPENAI_API_KEY")
    if not coach:
        if not key:
            st.info(tr("照片已保存。识别服务尚未配置，可先手动记录。",
                       "Photo saved. Scanning has not been configured yet. You can still enter the meal manually."))
        return key

    # Existing deployments use the original setting for free-text coach access.
    code = get_setting("TEAM_COACH_CODE") or get_setting("TEAM_PHOTO_CODE")
    if not key or len(code) < 12 or code == key:
        st.info(tr("自由提问尚未配置，可以先使用快捷问题。", "Free-text questions are not configured yet. Use the quick actions."))
        return ""
    device = st.session_state.get("diary_token")
    if _device_authorized(code, device):
        return key
    st.caption(tr("组内顾问码可启用自由提问。快捷问题免费。", "Use your team’s coach code for free-text questions. Quick actions are free."))
    with st.form("unlock_team_coach", clear_on_submit=True):
        entered = st.text_input(tr("组内顾问码", "Team coach code"), type="password", max_chars=128,
                                autocomplete="off", key="coach_code_input")
        label = tr("启用自由提问", "Enable free-text questions")
        if st.form_submit_button(label):
            if hmac.compare_digest(code.encode(), entered.strip().encode()):
                _device_authorized(code, device, grant=True)
                st.rerun()
            st.error(tr("顾问码不匹配，请核对后再试。", "That code did not match. Check the team code and try again."))
    return ""
