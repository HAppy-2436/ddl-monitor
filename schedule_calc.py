"""5 档 send_at 计算引擎

业务规则 (跟用户商定):
1. 每日汇总: 每天 09:00 发, 包含所有未完成 DDL
2. 明日截止: 每天 12:00 发, 包含 DDL ∈ [12:00, 12:00+36h] = 距截止 0-36h
3. 一周截止: 每天 14:00 发, 包含 DDL ∈ [14:00+154h, 14:00+178h] = 距截止 154-178h
4. 今日截止: 每天 18:00 发, 包含 DDL ∈ [18:00, 18:00+6h] = 距截止 0-6h
5. 紧急档: DDL-30min 单条
6. 紧急档兜底: DDL-4min 单条

send_at 是 [(datetime, slot), ...] 列表, 升序排列。
slot 字段直接标注, 避免时间反推歧义 (如 14:00 同时是 one_week 触发时刻 + urgent 兜底时刻)。
"""
import datetime as dt
from typing import List, Tuple


SlotName = str  # 'daily' / 'tomorrow' / 'one_week' / 'today' / 'urgent' / 'urgent_backup'

SendAt = Tuple[dt.datetime, SlotName]


def compute_send_at(deadline: dt.datetime, today: dt.date = None) -> List[SendAt]:
    """给定 DDL 截止时间, 算出所有 (send_at, slot) (升序)

    Args:
        deadline: DDL 截止时间
        today: 计算起点日期 (今天), 默认系统今天

    Returns:
        升序排列的 (datetime, slot_name) 列表
    """
    if today is None:
        today = dt.date.today()

    send_at: List[SendAt] = []
    now_start = dt.datetime.combine(today, dt.time(0, 0))

    # 1. 每日汇总 09:00: 从今天到 deadline 当天, 每天 09:00
    cursor = dt.datetime.combine(today, dt.time(9, 0))
    deadline_day_9am = dt.datetime.combine(deadline.date(), dt.time(9, 0))
    last = max(deadline_day_9am, cursor)
    while cursor <= last:
        if cursor >= now_start:
            send_at.append((cursor, 'daily'))
        cursor += dt.timedelta(days=1)

    # 2. 明日截止 12:00: 找哪天 12:00 触发时 DDL 在 [12:00, 12:00+36h] 内
    cursor = dt.datetime.combine(today, dt.time(12, 0))
    while cursor <= deadline:
        if cursor >= now_start and 0 <= (deadline - cursor).total_seconds() <= 36 * 3600:
            send_at.append((cursor, 'tomorrow'))
        cursor += dt.timedelta(days=1)

    # 3. 一周截止 14:00: 找哪天 14:00 触发时 DDL 在 [14:00+154h, 14:00+178h] 内
    cursor = dt.datetime.combine(today, dt.time(14, 0))
    while cursor <= deadline:
        if cursor >= now_start:
            delta_h = (deadline - cursor).total_seconds() / 3600
            if 154 <= delta_h <= 178:
                send_at.append((cursor, 'one_week'))
        cursor += dt.timedelta(days=1)

    # 4. 今日截止 18:00: 找哪天 18:00 触发时 DDL 在 [18:00, 18:00+6h] 内
    cursor = dt.datetime.combine(today, dt.time(18, 0))
    while cursor <= deadline:
        if cursor >= now_start and 0 <= (deadline - cursor).total_seconds() <= 6 * 3600:
            send_at.append((cursor, 'today'))
        cursor += dt.timedelta(days=1)

    # 5. 紧急档 30 分钟前
    urgent = deadline - dt.timedelta(minutes=30)
    if urgent >= now_start:
        send_at.append((urgent, 'urgent'))

    # 6. 紧急档兜底 4 分钟前
    urgent_backup = deadline - dt.timedelta(minutes=4)
    if urgent_backup >= now_start and urgent_backup != urgent:
        send_at.append((urgent_backup, 'urgent_backup'))

    # 按时间升序
    send_at.sort(key=lambda x: x[0])

    return send_at


# ===== 单元测试 =====
def _self_test():
    today = dt.date(2026, 6, 8)
    print(f"=== 测试 today = {today} ===\n")

    # 案例 1: 7 天后截止 (6-15 23:59)
    deadline = dt.datetime(2026, 6, 15, 23, 59)
    slots = compute_send_at(deadline, today)
    print(f"案例1: DDL = {deadline}")
    print(f"  共 {len(slots)} 个 send_at:")
    for t, s in slots:
        print(f"    {t}  [{s}]")
    # 验证 5/14/19
    daily_count = sum(1 for _, s in slots if s == 'daily')
    tomorrow_count = sum(1 for _, s in slots if s == 'tomorrow')
    one_week_count = sum(1 for _, s in slots if s == 'one_week')
    today_count = sum(1 for _, s in slots if s == 'today')
    urgent_count = sum(1 for _, s in slots if s == 'urgent')
    urgent_backup_count = sum(1 for _, s in slots if s == 'urgent_backup')
    print(f"  -> daily={daily_count} (期望 8) tomorrow={tomorrow_count} (期望 2: 6-14, 6-15) one_week={one_week_count} (期望 1: 6-08) today={today_count} (期望 1: 6-15) urgent={urgent_count} (期望 1) backup={urgent_backup_count} (期望 1)")
    print()

    # 案例 2: 1 天后截止 (6-9 14:00)
    deadline = dt.datetime(2026, 6, 9, 14, 0)
    slots = compute_send_at(deadline, today)
    print(f"案例2: DDL = {deadline}")
    for t, s in slots:
        print(f"    {t}  [{s}]")
    print()

    # 案例 3: 30 分钟后截止 (6-8 15:00)
    deadline = dt.datetime(2026, 6, 8, 15, 0)
    slots = compute_send_at(deadline, today)
    print(f"案例3: DDL = {deadline} (30min 后)")
    for t, s in slots:
        print(f"    {t}  [{s}]")
    print()

    # 案例 4: 5 天后截止 (6-13 12:00) - 验证"5 天时只发每日汇总"
    deadline = dt.datetime(2026, 6, 13, 12, 0)
    slots = compute_send_at(deadline, today)
    print(f"案例4: DDL = {deadline} (5天后)")
    for t, s in slots:
        print(f"    {t}  [{s}]")
    # 验证: 5 天时 (距 DDL = 120h) 明日档不触发 (120 > 36), 一周档不触发 (120 < 154)
    has_5day_12 = any((t.date() == today and s == 'tomorrow') for t, s in slots)
    print(f"  -> today 12:00 tomorrow 触发? {has_5day_12} (期望 False)")
    print()

    # 案例 5: 4 分钟后截止 (6-8 14:04) - 验证紧急 + 兜底
    deadline = dt.datetime(2026, 6, 8, 14, 4)
    slots = compute_send_at(deadline, today)
    print(f"案例5: DDL = {deadline} (4min 后)")
    for t, s in slots:
        print(f"    {t}  [{s}]")
    has_14_one_week = any((t.hour == 14 and t.minute == 0 and s == 'one_week') for t, s in slots)
    has_14_backup = any((t.hour == 14 and t.minute == 0 and s == 'urgent_backup') for t, s in slots)
    print(f"  -> 14:00 one_week 误触发? {has_14_one_week} (期望 False)")
    print(f"  -> 14:00 urgent_backup 触发? {has_14_backup} (期望 True)")
    print()

    # 案例 6: 已过期 (6-7 12:00)
    deadline = dt.datetime(2026, 6, 7, 12, 0)
    slots = compute_send_at(deadline, today)
    print(f"案例6: DDL = {deadline} (已过期)")
    for t, s in slots:
        print(f"    {t}  [{s}]")
    print(f"  -> 共 {len(slots)} 个, 都是今天 daily")
    print()

    print("=== 全部案例展示完毕 ===")


if __name__ == "__main__":
    _self_test()
