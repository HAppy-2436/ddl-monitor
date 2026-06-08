"""DDL 监控主入口 - 每分钟 cron 跑一次

每分钟做的事:
1. 拉指令邮件 (add/del/list) - process_replies
2. 找该发的邮件 (schedule.json + sent_log.json)
3. 按 slot 分组 + 排序 + 发邮件
4. 标记已发

业务规则 (5 档):
- daily 09:00 汇总
- tomorrow 12:00 明日 (≤36h)
- one_week 14:00 一周 (154-178h)
- today 18:00 今日 (≤6h)
- urgent DDL-30min (单条)
- urgent_backup DDL-4min (兜底)
"""
import sys
import datetime as dt
import fcntl
import os
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))

import state_io
import smtp_client
import email_render
import process_replies
import config

MAIN_LOCK = state_io.BASE_DIR / '.main.lock'


def _send_summary_emails(schedule: dict, sent_log: dict, now: dt.datetime) -> int:
    """发汇总类邮件 (daily/tomorrow/one_week/today)
    按 slot 分组, 同一 slot 多条 DDL 合并 1 封

    Returns:
        发送邮件数
    """
    # 找该发的: now ≥ send_at 且未标记
    pending_by_slot = defaultdict(list)  # slot -> [item_dict]
    pending_ddl_ids = set()

    for ddl_id, d in schedule.items():
        for send_at_str, slot in d.get('send_at', []):
            try:
                send_at = dt.datetime.fromisoformat(send_at_str)
            except Exception:
                continue
            if send_at > now:
                continue  # 还没到点
            # 是否已发过这个 slot
            if ddl_id in sent_log and slot in sent_log[ddl_id]:
                if send_at_str in sent_log[ddl_id][slot]:
                    continue  # 已发
            # 该发!
            pending_by_slot[slot].append({
                'ddl_id': ddl_id,
                'source': d.get('source', '?'),
                'title': d.get('title', '?'),
                'deadline': d.get('deadline', ''),
                'url': d.get('url', ''),
            })
            pending_ddl_ids.add(ddl_id)

    if not pending_by_slot:
        return 0

    # 按 slot 发邮件
    sent_count = 0
    for slot, items in pending_by_slot.items():
        if slot == 'urgent' or slot == 'urgent_backup':
            continue  # 紧急档单独发
        try:
            subject, html, text = email_render.render_summary(items, slot, now)
        except Exception as e:
            print(f"[main] 渲染 {slot} 失败: {e}", flush=True)
            continue
        if smtp_client.send_email(subject, html, text):
            sent_count += 1
            # 标记已发
            for it in items:
                ddl_id = it['ddl_id']
                if ddl_id not in sent_log:
                    sent_log[ddl_id] = {}
                if slot not in sent_log[ddl_id]:
                    sent_log[ddl_id][slot] = []
                # 标记该 DDL 该 slot 这次的具体 send_at 为已发
                for sa_str, sa_slot in schedule[ddl_id].get('send_at', []):
                    if sa_slot == slot and sa_str not in sent_log[ddl_id][slot]:
                        sent_log[ddl_id][slot].append(sa_str)
    return sent_count


def _send_urgent_emails(schedule: dict, sent_log: dict, now: dt.datetime) -> int:
    """发紧急档邮件 (单条 DDL)"""
    sent_count = 0
    for ddl_id, d in schedule.items():
        for send_at_str, slot in d.get('send_at', []):
            if slot not in ('urgent', 'urgent_backup'):
                continue
            try:
                send_at = dt.datetime.fromisoformat(send_at_str)
            except Exception:
                continue
            if send_at > now:
                continue
            if ddl_id in sent_log and slot in sent_log[ddl_id] and send_at_str in sent_log[ddl_id][slot]:
                continue
            # 该发
            item = {
                'source': d.get('source', '?'),
                'title': d.get('title', '?'),
                'deadline': d.get('deadline', ''),
                'url': d.get('url', ''),
            }
            try:
                subject, html, text = email_render.render_urgent(item, now, backup=(slot == 'urgent_backup'))
            except Exception as e:
                print(f"[main] 渲染 urgent 失败: {e}", flush=True)
                continue
            if smtp_client.send_email(subject, html, text):
                sent_count += 1
                if ddl_id not in sent_log:
                    sent_log[ddl_id] = {}
                if slot not in sent_log[ddl_id]:
                    sent_log[ddl_id][slot] = []
                sent_log[ddl_id][slot].append(send_at_str)
    return sent_count


def main():
    now = dt.datetime.now()
    print(f"[main] tick @ {now.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)

    # 0. 文件锁 (防并发)
    try:
        lock_fd = os.open(str(MAIN_LOCK), os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        # 有别的 main 在跑, 跳过
        print(f"[main] 已有 main 在跑, 跳过本次", flush=True)
        try:
            os.close(lock_fd)
        except Exception:
            pass
        return

    try:
        # 1. 处理指令邮件
        try:
            log = process_replies.process_inbox()
            if log:
                print(f"[main] 处理 {len(log)} 条指令", flush=True)
        except Exception as e:
            print(f"[main] process_inbox 失败: {e}", flush=True)

        # 2. 找该发的邮件
        schedule = state_io.load_schedule()
        sent_log = state_io.load_sent_log()

        # 2a. 汇总类 (daily/tomorrow/one_week/today)
        n_summary = _send_summary_emails(schedule, sent_log, now)
        # 2b. 紧急档
        n_urgent = _send_urgent_emails(schedule, sent_log, now)

        if n_summary or n_urgent:
            print(f"[main] 已发: {n_summary} 汇总 + {n_urgent} 紧急", flush=True)
        else:
            print(f"[main] 无需发邮件", flush=True)

        # 3. 保存 sent_log
        state_io.save_sent_log(sent_log)
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        except Exception:
            pass


if __name__ == "__main__":
    main()
