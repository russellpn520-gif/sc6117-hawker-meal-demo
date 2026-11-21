"""Resolve the server-side OpenAI key for the local photo demo."""

import os
import sys


WINDOWS_CREDENTIAL = "SC6117/track3-demo/OpenAI"


def read_api_key():
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key or sys.platform != "win32":
        return key
    from win32ctypes.pywin32 import pywintypes, win32cred

    try:
        entry = win32cred.CredRead(WINDOWS_CREDENTIAL, win32cred.CRED_TYPE_GENERIC)
    except pywintypes.error as exc:
        if exc.winerror == 1168:  # ERROR_NOT_FOUND
            return ""
        raise OSError("无法读取当前 Windows 用户的凭据管理器。") from None
    return entry["CredentialBlob"].decode("utf-16-le") if entry else ""


def save_windows_key(value):
    from win32ctypes.pywin32 import pywintypes, win32cred

    key = value.strip()
    if not key or not key.isascii() or not key.isprintable() or " " in key:
        raise ValueError("请粘贴完整的 OpenAI API Key。")
    try:
        win32cred.CredWrite({
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": WINDOWS_CREDENTIAL,
            "UserName": "OpenAI",
            "CredentialBlob": key,
            "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        })
    except pywintypes.error:
        raise OSError("密钥未保存，请检查 Windows 凭据管理器。") from None
