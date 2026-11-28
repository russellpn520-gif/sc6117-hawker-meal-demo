import re
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir
from uuid import uuid4

import streamlit as st

from meals import draft_cursor, export_pending, open_db, restore_pending


# The diary identifier is scoped to this browser and never appears in a URL.
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
        if (data.op === "forget" && localStorage.getItem(key) === data.old) {
          localStorage.removeItem("sc6117.meals.pending.v1." + data.old);
          localStorage.removeItem("sc6117.capture." + data.old);
          localStorage.setItem(key, data.next);
        }
        value = localStorage.getItem(key);
        if (!/^[0-9a-f]{32}$/.test(value || "")) {
          value = crypto.randomUUID().replaceAll("-", "");
          localStorage.setItem(key, value);
        }
      } catch {
        value = "unavailable";
      }
      if (marker.dataset.sent !== value) {
        marker.dataset.sent = value;
        setStateValue("token", value);
      }
      const onRotation = event => {
        if (event.key === key && /^[0-9a-f]{32}$/.test(event.newValue || "")
            && marker.dataset.sent !== event.newValue) {
          marker.dataset.sent = event.newValue;
          setStateValue("token", event.newValue);
        }
      };
      window.addEventListener("storage", onRotation);
      return () => window.removeEventListener("storage", onRotation);
    }
    """,
)


pending_storage = st.components.v2.component(
    "sc6117_pending_backup",
    html="<span hidden></span>",
    js="""
    export default function ({data, parentElement, setStateValue}) {
      const marker = parentElement.querySelector("span");
      const {op, token, generation, revision} = data;
      if (op === "idle") return;
      const stamp = [op, token, generation, revision].join(":");
      if (marker.dataset.sent === stamp) return;
      const key = "sc6117.meals.pending.v1." + token;
      const reply = {op, token, generation, revision, ok: true};
      try {
        if (localStorage.getItem("sc6117.meals.diary.v1") !== token) return;
        let previous = {};
        try { previous = JSON.parse(localStorage.getItem(key) || "{}") || {}; }
        catch { /* A fresh valid snapshot can replace damaged browser data. */ }
        if (op === "restore") {
          reply.rows = Array.isArray(previous.rows) ? previous.rows : [];
          // Claim the new disk generation before accepting another tab's writes.
          // Keep the old snapshot intact until the server acknowledges recovery.
          if (previous.generation !== generation)
            localStorage.setItem(key, JSON.stringify({generation, revision: -1, rows: reply.rows}));
        } else if (!previous.generation || previous.generation === generation) {
          if (!(previous.revision >= revision) || !previous.generation)
            localStorage.setItem(key, JSON.stringify({generation, revision, rows: data.rows}));
        } else {
          reply.ok = false;
        }
      } catch {
        reply.ok = false;
      }
      marker.dataset.sent = stamp;
      setStateValue("reply", reply);
    }
    """,
)


def _sync_pending(path, token):
    state = st.session_state
    generation, revision, hydrated = draft_cursor(db_path=path)
    command = {"op": "idle", "token": token, "generation": generation, "revision": revision}
    if not hydrated:
        command["op"] = "restore"
    elif state.get("last_draft_backup") != (token, generation, revision):
        command.update(export_pending(db_path=path), op="save")
    reply = pending_storage(key="pending_device", data=command, default={"reply": None},
                            on_reply_change=lambda: None).reply
    current = reply and (reply.get("token"), reply.get("generation")) == (token, generation)
    if not hydrated:
        if current and reply.get("op") == "restore":
            restore_pending(reply.get("rows", []), db_path=path)
            st.rerun()
        st.stop()
    if current and reply.get("op") == "save":
        state.last_draft_backup = (token, generation, reply.get("revision"))
        state.draft_backup_limited = not reply.get("ok")


def _diary_path(token):
    if not isinstance(token, str) or not re.fullmatch("[a-f0-9]{32}", token):
        return None
    return Path(gettempdir()) / "sc6117-device-diaries-v1" / f"{token}.sqlite3"


def cloud_diary():
    state = st.session_state
    command = state.get("device_command", {"op": "read"})
    result = device_storage(key="diary_device", data=command, default={"token": None},
                            on_token_change=lambda: None)
    token = result.token
    if token is None:
        st.stop()
    state.device_storage_blocked = token == "unavailable"
    if command["op"] != "read":
        # Concurrent clears in two tabs converge on whichever new token was
        # actually written. A tab must not wait for its losing proposal.
        waiting = token == command["old"] if command["op"] == "forget" else token != command.get("token")
        if token != "unavailable" and waiting:
            st.stop()
        state.pop("device_command", None)
    path = _diary_path(token)
    if path:
        if state.get("diary_token") and state.diary_token != token:
            for key in ("active_draft", "capture_ack", "receipt", "edit_profile", "retaking", "delete_diary_entry"):
                state.pop(key, None)
        state.diary_token = token
        _sync_pending(path, token)
        return path
    state.pop("diary_token", None)
    if "log_directory" not in state:
        state.log_directory = TemporaryDirectory(prefix="sc6117-meals-")
    return Path(state.log_directory.name) / "meals.sqlite3"


def remember_diary(current_path):
    if st.session_state.get("diary_token"):
        return current_path
    token = uuid4().hex
    path = _diary_path(token)
    with closing(open_db(current_path)) as source, closing(open_db(path)) as destination:
        source.backup(destination)
    st.session_state.diary_token = token
    st.session_state.device_command = {"op": "save", "token": token}
    return path


def forget_diary():
    # The caller clears the database before removing the browser's identifier.
    old = st.session_state.pop("diary_token", None)
    if old:
        st.session_state.device_command = {"op": "forget", "old": old, "next": uuid4().hex}
    st.session_state.pop("last_draft_backup", None)
    directory = st.session_state.pop("log_directory", None)
    if directory:
        directory.cleanup()
