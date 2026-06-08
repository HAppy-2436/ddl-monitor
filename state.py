"""DDL 提醒状态管理 (基于时间 slot 跟踪)"""
import json
import datetime as dt
from config import STATE_FILE


def load() -> dict:
    if not STATE_FILE.exists():
        return {"items": {}}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"items": {}}


def save(state: dict):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _parse_deadline(s: str):
    try:
        return dt.datetime.fromisoformat(s)
    except Exception:
        return None


def is_completed(state: dict, key: str) -> bool:
    return state.get("items", {}).get(key, {}).get("status") == "completed"


def mark_completed(state: dict, key: str, deadline: str = ""):
    item = state["items"].setdefault(key, {})
    item["status"] = "completed"
    item["completed_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if deadline:
        item["deadline"] = deadline


def mark_reminded(state: dict, key: str, slot: str):
    """slot: 'all_1130' / 'urgent_2d_1400' / 'urgent_2d_1800' / 'urgent_5min_2123' 等
    同 slot 同 date 不重发"""
    item = state["items"].setdefault(key, {})
    reminded = item.setdefault("reminded_at", [])
    today_str = dt.datetime.now().strftime("%Y-%m-%d")
    tag = f"{slot}:{today_str}"
    if tag not in reminded:
        reminded.append(tag)
    # 只保留 60 天的记录
    cutoff = (dt.datetime.now() - dt.timedelta(days=60)).strftime("%Y-%m-%d")
    item["reminded_at"] = [t for t in reminded if t.rsplit(":", 1)[-1] >= cutoff]


def was_reminded_in_slot(state: dict, key: str, slot: str) -> bool:
    item = state["items"].get(key, {})
    reminded = item.get("reminded_at", [])
    today_str = dt.datetime.now().strftime("%Y-%m-%d")
    return f"{slot}:{today_str}" in reminded


def cleanup_old(state: dict):
    now = dt.datetime.now()
    keys = list(state["items"].keys())
    for k in keys:
        item = state["items"][k]
        if item.get("status") == "completed":
            # 已完成的 item 保留 30 天
            completed_at = item.get("completed_at", "")
            if completed_at:
                try:
                    ca = dt.datetime.strptime(completed_at, "%Y-%m-%d %H:%M:%S")
                    if (now - ca).days > 30:
                        del state["items"][k]
                except Exception:
                    pass
            continue
        deadline_str = item.get("deadline", "")
        d = _parse_deadline(deadline_str)
        if not d:
            continue
        if (now - d).days > 7:
            del state["items"][k]
