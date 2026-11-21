import re
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir
from uuid import uuid4

import streamlit as st

from meals import open_db


# The browser stores only a random, per-diary identifier. It never appears in a URL.
device_storage = st.components.v2.component(
    "sc6117_device_diary",
    html="<span hidden></span>",
    js="""
    export default function ({data, parentElement, setStateValue}) {
      const marker = parentElement.querySelector("span");
      const key = "sc6117.meals.diary.v1";
      let value;
      try {
        if (data.op === "save") localStorage.setItem(key, data.token);
        if (data.op === "forget") localStorage.removeItem(key);
        value = localStorage.getItem(key) || "guest";
      } catch {
        value = "unavailable";
      }
      if (marker.dataset.sent !== value) {
        marker.dataset.sent = value;
        setStateValue("token", value);
      }
    }
    """,
)


def _diary_path(token):
    if not isinstance(token, str) or not re.fullmatch("[a-f0-9]{32}", token):
        return None
    return Path(gettempdir()) / "sc6117-device-diaries-v1" / f"{token}.sqlite3"


def cloud_diary():
    state = st.session_state
    if "log_directory" not in state:
        state.log_directory = TemporaryDirectory(prefix="sc6117-meals-")
    guest = Path(state.log_directory.name) / "meals.sqlite3"
    command = state.get("device_command", {"op": "read"})
    result = device_storage(key="diary_device", data=command, default={"token": None},
                            on_token_change=lambda: None)
    token = result.token
    state.device_storage_blocked = token == "unavailable"
    if command["op"] == "read":
        path = _diary_path(token)
        if path and path.is_file():
            state.diary_token = token
        elif path:
            state.pop("diary_token", None)
            state.device_command = {"op": "forget"}
            state.notice = "上次的云端临时记录已到期，可以重新建立计划。"
    elif token == command.get("token", "guest") or token == "unavailable":
        state.pop("device_command", None)
    return _diary_path(state.get("diary_token")) or guest


def remember_diary(current_path):
    token = uuid4().hex
    path = _diary_path(token)
    with closing(open_db(current_path)) as source, closing(open_db(path)) as destination:
        source.backup(destination)
    st.session_state.diary_token = token
    st.session_state.device_command = {"op": "save", "token": token}
    return path


def forget_diary():
    # The caller clears the database before removing the browser's identifier.
    st.session_state.pop("diary_token", None)
    st.session_state.device_command = {"op": "forget"}
    directory = st.session_state.pop("log_directory", None)
    if directory:
        directory.cleanup()
