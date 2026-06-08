"""DDL 监控主入口

每分钟跑一次 (cron *) 或 long-running 模式 (LONG_RUNNING=1):
1. 读 cache (TTL=5min). 过期就重 scrape 学习通 + 编程帮的 DDL
2. 处理用户主动查询的 Gmail 邮件
3. 判定当前时间 slot:
   - 11:30 -> 发所有 DDL
   - 14:00 / 18:00 -> 发 <= 2 天的 DDL
   - 极紧急 (DDL 30min 内) -> 发 1 封; 同 1 分钟内不重发
4. 更新 state.json
"""
import sys
import os
import json
import datetime as dt
from pathlib import Path
import config
import state
import notify
from scrapers import chaoxing, mynereus

BASE_DIR = Path(__file__).resolve().parent
CACHE_FILE = BASE_DIR / "cache.json"
LOCK_FILE = BASE_DIR / ".main.lock"
CACHE_TTL_MIN = 5


def _acquire_lock() -> bool:
    """简单的 PID 锁。返回 True 表示获得锁, False 表示已有实例在跑"""
    try:
        if LOCK_FILE.exists():
            old_pid = int(LOCK_FILE.read_text().strip())
            try:
                import os
                os.kill(old_pid, 0)  # 进程存在?
                return False
            except (OSError, ProcessLookupError):
                # 旧进程已死, 锁可清理
                LOCK_FILE.unlink(missing_ok=True)
        LOCK_FILE.write_text(str(__import__('os').getpid()))
        return True
    except Exception:
        return True  # 锁失败也允许跑, 避免锁机制成为单点故障


def _release_lock():
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass

SOURCES = {
    "chaoxing": ("学习通", chaoxing.fetch_ddls),
    "mynereus": ("编程帮", mynereus.fetch_ddls),
}


# --- scrape cache ---

def _load_cache():
    if not CACHE_FILE.exists():
        return None
    try:
        d = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        scraped_at = dt.datetime.fromisoformat(d["scraped_at"])
        if (dt.datetime.now() - scraped_at).total_seconds() < CACHE_TTL_MIN * 60:
            return d
    except Exception:
        pass
    return None


def _save_cache(items):
    CACHE_FILE.write_text(
        json.dumps({
            "scraped_at": dt.datetime.now().isoformat(),
            "items": items,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def _scrape_fresh() -> list:
    """全量 scrape 一次"""
    all_items = []
    for _key, (label, fn) in SOURCES.items():
        try:
            items = fn()
            for it in items:
                it["source_label"] = label
            all_items.extend(items)
            print(f"[main] {label}: {len(items)} 条", flush=True)
        except Exception as e:
            print(f"[main] {label} 抓取异常: {e}", flush=True)
    return all_items


def collect_items() -> list:
    """优先用 cache; 过期则全量 scrape"""
    cached = _load_cache()
    if cached:
        print(f"[main] 用 cache ({len(cached['items'])} 条, scrape @ {cached['scraped_at']})", flush=True)
        return cached["items"]
    print("[main] cache 过期, 重新 scrape", flush=True)
    items = _scrape_fresh()
    _save_cache(items)
    return items


# --- 过滤已完成 ---

COMPLETED_STATUSES = {"已完成", "已交", "已批改", "已批阅", "完成", "已批"}


def filter_completed(st: dict, items: list) -> list:
    """过滤已完成 + 标记新完成的 DDL。
    已完成的标志 (满足任一即视为完成):
      1. scraper 抓到的 status 字段显示已完成
      2. deadline 已过期 (说明作业过了)
    scrape 抓不到的 DDL 不当作完成 (避免 scrape 失败误判)"""
    now = dt.datetime.now()
    new_keys = set()
    result = []
    for it in items:
        key = f"{it['source']}:{it['title']}"
        new_keys.add(key)
        status = it.get("status", "")
        deadline_str = it.get("deadline", "")
        # 1. status 字段显示已完成
        if status in COMPLETED_STATUSES:
            state.mark_completed(st, key, deadline_str)
            print(f"[main]   完成(status): {key} (status={status})", flush=True)
            continue
        # 2. deadline 已过期 (现在 > deadline)
        is_expired = False
        if deadline_str:
            try:
                d = dt.datetime.fromisoformat(deadline_str)
                if d < now:
                    is_expired = True
            except Exception:
                pass
        if is_expired:
            state.mark_completed(st, key, deadline_str)
            print(f"[main]   完成(过期): {key} (deadline={deadline_str})", flush=True)
            continue
        if state.is_completed(st, key):
            # 之前已完成, 这次又出现 (教师撤回完成), 重置
            st["items"].pop(key, None)
            print(f"[main]   重置: {key} (之前完成, 重新出现)", flush=True)
        result.append(it)
    return result


# --- 时间 slot 判定 ---

def current_slot(now: dt.datetime) -> str | None:
    """返回当前时间的 slot 标识, None 表示不发邮件"""
    h, m = now.hour, now.minute
    if h == 11 and m == 30:
        return "all_1130"
    if h == 14 and m == 0:
        return "urgent_2d_1400"
    if h == 18 and m == 0:
        return "urgent_2d_1800"
    return None


def find_urgent_ddls(items: list, now: dt.datetime, window_sec: int = 1800) -> list:
    """找 0 < 剩余秒数 <= window 的 DDL (默认 30 分钟)"""
    out = []
    for it in items:
        try:
            d = dt.datetime.fromisoformat(it["deadline"])
        except Exception:
            continue
        sec_left = (d - now).total_seconds()
        if 0 < sec_left <= window_sec:
            out.append((it, int(sec_left)))
    return out


# --- 渲染 ---

def render_all(items: list, slot: str, now: dt.datetime) -> tuple:
    items_sorted = sorted(items, key=lambda x: x["deadline"])
    if not items_sorted:
        return ("[DDL Monitor] 当前没有未完成作业", "<p>当前没有未完成作业 ✨</p>", "当前没有未完成作业")
    slot_label = {
        "all_1130": "11:30 汇总",
        "urgent_2d_1400": "14:00 紧急提醒 (≤2天)",
        "urgent_2d_1800": "18:00 紧急提醒 (≤2天)",
        "urgent_5min": "极紧急 (≤30分钟)",
    }.get(slot, slot)
    subject = f"[DDL Monitor] {slot_label} · {len(items_sorted)} 项未完成"
    parts = [f"<h2>你当前有 <b style='color:#dc2626'>{len(items_sorted)}</b> 项未完成 DDL</h2>"]
    parts.append("<p style='color:#888;font-size:12px'>按截止时间升序</p><ol>")
    for it in items_sorted:
        try:
            d = dt.datetime.fromisoformat(it["deadline"])
            d_str = d.strftime("%Y-%m-%d %H:%M")
            h_left = (d - now).total_seconds() / 3600
            h_str = f"{h_left:.1f}h" if h_left >= 0 else f"已过期 {abs(h_left):.1f}h"
        except Exception:
            d_str = it["deadline"]
            h_str = ""
            h_left = 99999
        color = "#dc2626" if h_left <= 24 else ("#ea580c" if h_left <= 48 else "#ca8a04")
        parts.append(
            f"<li><b>{it['title']}</b> "
            f"<span style='color:{color}'>{d_str}</span> "
            f"<small>({it['source_label']} · 剩 {h_str})</small> "
            f"<a href='{it.get('url', '')}'>链接</a></li>"
        )
    parts.append("</ol>")
    parts.append(f"<hr><p style='color:#888;font-size:12px'>触发: {slot_label} @ {now.strftime('%H:%M')}</p>")
    html = "".join(parts)
    text = f"你当前有 {len(items_sorted)} 项未完成 DDL ({slot_label})\n\n"
    for it in items_sorted:
        d_str = it.get("deadline", "")
        text += f"  [{it['source_label']}] {it['title']}  截止 {d_str}\n"
    text += f"\n触发: {now.strftime('%Y-%m-%d %H:%M')}\n"
    return subject, html, text


def render_urgent_minute(items_with_sec, now: dt.datetime) -> tuple:
    items = [it for it, _ in items_with_sec]
    items_sorted = sorted(items, key=lambda x: x["deadline"])
    subject = f"[DDL Monitor] 极紧急！{len(items_sorted)} 项马上截止"
    parts = [f"<h2 style='color:#dc2626'>！极紧急！{len(items_sorted)} 项 DDL 在 30 分钟内截止</h2>"]
    for it in items_sorted:
        try:
            d = dt.datetime.fromisoformat(it["deadline"])
            d_str = d.strftime("%H:%M:%S")
            sec = (d - now).total_seconds()
            h_str = f"{sec:.0f} 秒" if sec < 60 else f"{sec/60:.1f} 分钟"
        except Exception:
            d_str = it["deadline"]
            h_str = "?"
        parts.append(
            f"<p><b style='color:#dc2626;font-size:18px'>{it['title']}</b><br>"
            f"截止 <b>{d_str}</b> (剩 {h_str}) "
            f"<small>({it['source_label']})</small></p>"
        )
    parts.append(f"<p style='color:#888;font-size:12px'>每分钟提醒一次直到完成 · 触发 @ {now.strftime('%H:%M:%S')}</p>")
    html = "".join(parts)
    text = f"！极紧急！{len(items_sorted)} 项 DDL 在 30 分钟内截止\n\n"
    for it, sec in sorted(items_with_sec, key=lambda x: x[1]):
        d_str = it["deadline"]
        text += f"  [{it['source_label']}] {it['title']}  截止 {d_str}  剩 {sec:.0f}s\n"
    return subject, html, text


# --- reply ---

def render_reply_html(items: list) -> str:
    if not items:
        return "<p>当前未抓到任何未完成 DDL。</p>"
    items_sorted = sorted(items, key=lambda x: x["deadline"])
    rows = []
    for it in items_sorted:
        try:
            d = dt.datetime.fromisoformat(it["deadline"])
            d_str = d.strftime("%Y-%m-%d %H:%M")
        except Exception:
            d_str = it["deadline"]
        rows.append(
            f"<tr><td>{it['source_label']}</td><td>{it['title']}</td>"
            f"<td>{d_str}</td><td>{it.get('status', '?')}</td>"
            f"<td><a href='{it.get('url', '')}'>链接</a></td></tr>"
        )
    return (
        f"<h3>当前共 {len(items)} 项未完成 DDL</h3>"
        "<table border=1 cellpadding=6 style='border-collapse:collapse'>"
        "<tr style='background:#f5f5f5'><th>平台</th><th>作业</th><th>截止时间</th><th>状态</th><th>链接</th></tr>"
        + "".join(rows)
        + "</table>"
        f"<p style='color:#888;font-size:12px'>抓取时间: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>"
    )


def render_reply_text(items: list) -> str:
    if not items:
        return "当前未抓到任何未完成 DDL。"
    items_sorted = sorted(items, key=lambda x: x["deadline"])
    lines = [f"当前共 {len(items)} 项未完成 DDL：\n"]
    for it in items_sorted:
        lines.append(f"  [{it['source_label']}] {it['title']}  截止 {it['deadline']}  状态: {it.get('status', '?')}")
    return "\n".join(lines)


def process_replies(items: list):
    print("[main] 检查 Gmail INBOX...", flush=True)
    pending = notify.fetch_reply_emails(trigger_substrings=("ddl", "DDL"))
    if not pending:
        print("[main] 没有待处理的查询邮件", flush=True)
        return
    print(f"[main] 找到 {len(pending)} 封待处理邮件", flush=True)
    for em in pending:
        subject = f"Re: {em['subject']}"
        html = render_reply_html(items)
        text = render_reply_text(items)
        ok = notify.send_reply_email(em["from_addr"], subject, html, text, in_reply_to=em.get("message_id"))
        if ok:
            print(f"[main]   -> reply sent to {em['from_addr']}: {subject}", flush=True)
        else:
            print(f"[main]   -> reply FAILED to {em['from_addr']}", flush=True)
    notify.mark_emails_read([em["uid"] for em in pending])
    print(f"[main] 已标记 {len(pending)} 封邮件为已读", flush=True)


# --- main ---

def main():
    if not _acquire_lock():
        print("[main] 已有实例在跑, 跳过本次", flush=True)
        return 0
    try:
        return _main()
    finally:
        _release_lock()


def _main():
    now = dt.datetime.now()
    print(f"[main] tick @ {now.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    st = state.load()
    items = collect_items()
    # 1. 处理用户主动查询
    process_replies(items)
    # 2. 过滤已完成 (status + scrape 消失的)
    items = filter_completed(st, items)
    if not items:
        print("[main] 没未完成的 DDL, 跳过提醒邮件", flush=True)
        state.cleanup_old(st)
        state.save(st)
        return 0
    # 3. 判定当前 slot
    slot = current_slot(now)
    sent_something = False
    if slot == "all_1130":
        # 11:30 汇总: 发所有未完成 DDL (排除已过期)
        alive = []
        for it in items:
            try:
                d = dt.datetime.fromisoformat(it["deadline"])
                if (d - now).total_seconds() > 0:
                    alive.append(it)
            except Exception:
                continue
        if alive:
            subject, html, text = render_all(alive, slot, now)
            if notify.send_email(subject, html, text):
                for it in alive:
                    state.mark_reminded(st, f"{it['source']}:{it['title']}", slot)
                sent_something = True
                print(f"[main] [{slot}] 发所有 {len(alive)} 项 (排除 {len(items)-len(alive)} 过期)", flush=True)
    elif slot in ("urgent_2d_1400", "urgent_2d_1800"):
        # 14:00 / 18:00: 只发 <= 2 天的
        urgent_items = []
        for it in items:
            try:
                d = dt.datetime.fromisoformat(it["deadline"])
                hours_left = (d - now).total_seconds() / 3600
                if 0 < hours_left <= 48:
                    urgent_items.append(it)
            except Exception:
                continue
        if urgent_items:
            # 过滤: 同 slot 同 key 今天没发过
            to_send = []
            for it in urgent_items:
                key = f"{it['source']}:{it['title']}"
                if not state.was_reminded_in_slot(st, key, slot):
                    to_send.append(it)
            if to_send:
                subject, html, text = render_all(to_send, slot)
                if notify.send_email(subject, html, text):
                    for it in to_send:
                        state.mark_reminded(st, f"{it['source']}:{it['title']}", slot)
                    sent_something = True
                    print(f"[main] [{slot}] 发 {len(to_send)} 项 (≤2天)", flush=True)
    else:
        # 其它时间: 检查极紧急 (0-5 min)
        urgent = find_urgent_ddls(items, now, window_sec=1800)
        if urgent:
            # 每分钟发: 同分钟 (key, "urgent_5min") 之前没发过
            to_send = []
            for it, sec in urgent:
                key = f"{it['source']}:{it['title']}"
                slot_urgent = f"urgent_5min_{now.strftime('%H%M')}"
                if not state.was_reminded_in_slot(st, key, slot_urgent):
                    to_send.append((it, sec))
            if to_send:
                subject, html, text = render_urgent_minute(to_send, now)
                if notify.send_email(subject, html, text):
                    for it, _ in to_send:
                        state.mark_reminded(st, f"{it['source']}:{it['title']}", f"urgent_5min_{now.strftime('%H%M')}")
                    sent_something = True
                    print(f"[main] [urgent_5min] 发 {len(to_send)} 项", flush=True)
    if not sent_something:
        print(f"[main] 当前 slot={slot or 'idle'} 无需发邮件", flush=True)
    state.cleanup_old(st)
    state.save(st)
    return 0


def main_loop():
    """Long-running 主循环: 对齐到下一分钟 0 秒触发
    关键: 必须踩在整分 (HH:MM:00), 否则 11:30/14:00/18:00 slot 会被错过
    keep_alive 监督这个进程, 6 小时主动重启一次 (防内存泄漏)"""
    import time as _t
    print(f"[main] long-running loop 启动, 对齐到整分触发", flush=True)
    while True:
        # 计算到下一整分 (HH:MM:00) 还差多少秒
        now = dt.datetime.now()
        nxt = (now + dt.timedelta(minutes=1)).replace(second=0, microsecond=0)
        wait_sec = (nxt - now).total_seconds()
        # 减 0.5s 让 sleep 提前醒 (保证不晚于整分)
        wait_sec = max(0.5, wait_sec - 0.5)
        print(f"[main] 下次 tick 等待 {wait_sec:.1f}s (目标 {nxt.strftime('%H:%M:%S')})", flush=True)
        _t.sleep(wait_sec)
        try:
            main()
        except SystemExit:
            raise
        except Exception as e:
            print(f"[main] tick 异常: {e}", flush=True)


if __name__ == "__main__":
    # 单次跑: python3 main.py
    # 长跑模式: LONG_RUNNING=1 python3 main.py
    if os.environ.get("LONG_RUNNING") == "1":
        main_loop()
    else:
        sys.exit(main())
