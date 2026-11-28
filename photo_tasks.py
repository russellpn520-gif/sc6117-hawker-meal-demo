"""Run a captured meal's recognition without holding its browser session open."""

from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore

from meals import claim_pending, finish_pending, get_pending, load_foods

_workers = ThreadPoolExecutor(max_workers=4, thread_name_prefix="meal-photo")
_slots = BoundedSemaphore(4)


def _recognize(draft, db_path, lease, api_key, use_qwen):
    try:
        from recognition import identify_photo

        if api_key:
            result = identify_photo(draft["photo"], "餐食照片", load_foods(), api_key=api_key, use_qwen=use_qwen)
            result.update(id=draft["id"], status="ready")
        else:
            result = {**draft, "status": "failed", "error": "照片已保存。识别服务尚未配置，可以先按菜名补记。"}
    except Exception:
        # Keep the photo and allow a manual retry. Provider errors can include
        # sensitive request details and must not be put in the user's diary.
        result = {**draft, "status": "failed", "error": "照片已保存。这次识别未完成，可重试或按菜名补记。"}
    try:
        finish_pending(result, claim=lease, db_path=db_path)
    finally:
        _slots.release()


def start_recognition(draft_id, db_path, api_key, use_qwen):
    if not _slots.acquire(blocking=False):
        return
    submitted = False
    try:
        lease = claim_pending(draft_id, db_path=db_path)
        if lease:
            draft = get_pending(draft_id, db_path=db_path)
            if draft is not None:
                _workers.submit(_recognize, draft, db_path, lease, api_key, use_qwen)
                submitted = True
    finally:
        if not submitted:
            _slots.release()
