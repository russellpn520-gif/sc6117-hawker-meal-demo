"""Run a captured meal's recognition without holding its browser session open."""

from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore

from meals import claim_pending, finish_pending, get_pending, load_foods

_workers = ThreadPoolExecutor(max_workers=4, thread_name_prefix="meal-photo")
_slots = BoundedSemaphore(4)

_ERRORS = {
    "unconfigured": ("照片已保存。应用尚未配置 OpenAI API Key，可先按菜名记餐。",
                     "Your photo is saved. The app has no OpenAI API key yet. You can enter food names."),
    "key": ("照片已保存。请应用维护者检查 OpenAI 密钥和模型权限。",
            "Your photo is saved. The app owner needs to check the OpenAI key and model access."),
    "quota": ("照片已保存。OpenAI API 额度不足，可先按菜名记餐。",
              "Your photo is saved. OpenAI API credit is unavailable. You can enter food names."),
    "rate_limit": ("照片已保存。识别服务暂时达到请求上限，稍后可重试。",
                   "Your photo is saved. Recognition is temporarily rate-limited. Try again later."),
    "unavailable": ("照片已保存。这次未能连接识别服务，稍后可重试或按菜名记餐。",
                    "Your photo is saved. Recognition is temporarily unavailable. Try later or enter food names."),
    "unreadable": ("照片已保存。这次未能取得完整识别结果，可重试或按菜名记餐。",
                   "Your photo is saved. The scan did not return a complete result. Retry or enter food names."),
}


def _failure(draft, code):
    zh, en = _ERRORS[code]
    return {**draft, "status": "failed", "error_code": code, "error": zh, "error_en": en}


def _recognize(draft, db_path, lease, api_key):
    try:
        from recognition import identify_photo

        if api_key and api_key.strip():
            language = draft["input"].get("ui_lang", draft.get("ui_lang", "zh"))
            name = "Meal photo" if language == "en" else "餐食照片"
            if draft["input"].get("method") == "label":
                from label_scan import read_label
                result = read_label(draft["photo"], api_key=api_key, ui_lang=language)
            else:
                hint = draft["input"].get("portion_hint", "")
                options = {"portion_hint": hint[:150]} if hint else {}
                result = identify_photo(draft["photo"], name, load_foods(), api_key=api_key, ui_lang=language,
                                        **options)
            result.update(id=draft["id"], status="ready")
        else:
            result = _failure(draft, "unconfigured")
    except Exception as exc:
        # Provider exception messages can include request details or credentials.
        # Store only a known error category and its two UI messages.
        status = getattr(exc, "status_code", None)
        if getattr(exc, "code", "") in ("insufficient_quota", "billing_hard_limit_reached", "billing_not_active"):
            code = "quota"
        elif status in (401, 403):
            code = "key"
        elif status == 429:
            code = "rate_limit"
        else:
            code = "unreadable" if isinstance(exc, ValueError) else "unavailable"
        result = _failure(draft, code)
    try:
        finish_pending(result, claim=lease, db_path=db_path)
    finally:
        _slots.release()


def start_recognition(draft_id, db_path, api_key):
    if not _slots.acquire(blocking=False):
        return
    submitted = False
    try:
        lease = claim_pending(draft_id, db_path=db_path)
        if lease:
            draft = get_pending(draft_id, db_path=db_path)
            if draft is not None:
                _workers.submit(_recognize, draft, db_path, lease, api_key)
                submitted = True
    finally:
        if not submitted:
            _slots.release()
