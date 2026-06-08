"""端到端测试: 用 mock 数据模拟完整流程

场景:
1. 准备 schedule.json (3 条 DDL: 7 天后/1 天后/30 分钟后)
2. 准备 sent_log.json (空)
3. 跑 main.py (mock SMTP/IMAP), 验证:
   - 30 分钟后那条 DDL 触发紧急档
   - 1 天后那条触发 12:00 明日档
   - 7 天后那条触发 09:00 每日档
4. 再跑一次, 验证不重复发
"""
import sys
import json
import datetime as dt
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

# 隔离 BASE_DIR 到临时目录
tmpdir = tempfile.mkdtemp(prefix='ddl_test_')
print(f"[test] tmpdir = {tmpdir}")

# 修改 state_io 的 BASE_DIR 指向 tmpdir
import state_io
state_io.BASE_DIR = Path(tmpdir)
state_io.DDL_LIST_FILE = state_io.BASE_DIR / 'ddl_list.json'
state_io.MANUAL_DDLS_FILE = state_io.BASE_DIR / 'manual_ddls.json'
state_io.SCHEDULE_FILE = state_io.BASE_DIR / 'schedule.json'
state_io.SENT_LOG_FILE = state_io.BASE_DIR / 'sent_log.json'
state_io.SCRAPE_LOCK = state_io.BASE_DIR / '.scrape.lock'

# mock 凭据
import config
config.GMAIL_USER = 'hahappy2436@gmail.com'
config.GMAIL_APP_PASSWORD = 'mock_password'
config.QQ_MAIL = '2357356249@qq.com'

# mock SMTP (收集发送记录, 不真发)
SENT_EMAILS = []
import smtp_client
def mock_send(subject, html, text, to_addr=None):
    SENT_EMAILS.append({
        'subject': subject,
        'to': to_addr or config.QQ_MAIL,
        'text_preview': text[:100],
    })
    print(f"  [mock send] {subject} -> {to_addr or config.QQ_MAIL}")
    return True
smtp_client.send_email = mock_send

# mock IMAP (返回空, 无指令邮件)
import imap_client
imap_client.fetch_inbox_emails = lambda **kw: []

# mock process_replies 走 imap_client, 已 mock fetch_inbox_emails 返回 [], 自然啥也不做
import process_replies
# (不需要再 mock, 因为 fetch_inbox_emails 已 mock)

# ===== 准备数据 =====
import schedule_calc
import manual_ddls

# 清理可能的旧文件
for f in [state_io.DDL_LIST_FILE, state_io.MANUAL_DDLS_FILE, state_io.SCHEDULE_FILE, state_io.SENT_LOG_FILE]:
    if f.exists():
        f.unlink()

# 手动加 3 条 DDL (覆盖各种场景)
now = dt.datetime.now()
r1 = manual_ddls.add('期末大作业', '明天 17:00', '数据结构')  # ~29h
# Lab14 30 分钟后截止: deadline = now + 30min, 表达为 'M-D HH:MM' 今天
deadline_lab14 = now + dt.timedelta(minutes=30)
r2 = manual_ddls.add('Lab14 课后上机', f'{deadline_lab14.month}-{deadline_lab14.day} {deadline_lab14.hour}:{deadline_lab14.minute:02d}', '')
# 7 天后 23:59
deadline_week = now + dt.timedelta(days=7)
r3 = manual_ddls.add('一周后大作业', f'{deadline_week.month}-{deadline_week.day} 23:59', '')

assert r1['ok']
assert r2['ok']
assert r3['ok']
print(f"[test] 已加 3 条 DDL")

# 重算 schedule (实际部署时 scrape.py 会做, 测试里手动调)
import scrape
result = scrape.scrape_all(is_monday=False)
print(f"[test] scrape 重算 schedule: {result}")

# ===== 测试 1: 第一次跑 main.py =====
print("\n=== 测试 1: 第一次跑 main.py (覆盖 09:00/12:00 触发场景) ===")
# 把 now 模拟成 09:01 (让 daily 触发)
mock_now = dt.datetime.combine(now.date(), dt.time(9, 1))
print(f"[test] 模拟 now = {mock_now}")

# mock _send_summary_emails 用 mock_now
import main
from main import _send_summary_emails, _send_urgent_emails

# 直接传 mock_now 给函数, 不需要 patch (函数签名是 (schedule, sent_log, now))
schedule = state_io.load_schedule()
sent_log = state_io.load_sent_log()
n_summary = _send_summary_emails(schedule, sent_log, mock_now)
n_urgent = _send_urgent_emails(schedule, sent_log, mock_now)
state_io.save_sent_log(sent_log)

print(f"[test] 第一次跑: 汇总={n_summary}, 紧急={n_urgent}, 总发邮件={len(SENT_EMAILS)}")

# 验证: 09:01 跑
# - daily 09:00 (现在 09:01) 触发, 3 条 DDL 都会列 (只要 deadline >= 09:00, 全列)
# - tomorrow 12:00 (现在 09:01) 还没到, 不触发
# - urgent (Lab14 30min 后) 还没到 deadline - 30min, 不触发
# - urgent_backup (Lab14 4min 后) 同上
# 预期: 1 封 daily 邮件
assert n_summary == 1, f"期望 1 封汇总, 实际 {n_summary}"
assert n_urgent == 0, f"期望 0 封紧急, 实际 {n_urgent}"
assert SENT_EMAILS[0]['subject'].startswith('[DDL·汇总]')
print(f"OK: 09:01 跑 1 封 daily 汇总")

# ===== 测试 2: 模拟 12:01 跑 =====
print("\n=== 测试 2: 12:01 跑 (12:00 明日档触发) ===")
SENT_EMAILS.clear()
mock_now = dt.datetime.combine(now.date(), dt.time(12, 1))
print(f"[test] 模拟 now = {mock_now}")

schedule = state_io.load_schedule()
sent_log = state_io.load_sent_log()
n_summary = _send_summary_emails(schedule, sent_log, mock_now)
n_urgent = _send_urgent_emails(schedule, sent_log, mock_now)
state_io.save_sent_log(sent_log)

print(f"[test] 12:01 跑: 汇总={n_summary}, 紧急={n_urgent}, 总邮件={len(SENT_EMAILS)}")
# 预期:
# - 12:00 明日档: 期末大作业 (29h ≤ 36h) + Lab14 (~2h30m ≤ 36h) → 2 条
# - 一周档 / 今日档 / 紧急档 都不到点
assert n_summary == 1, f"期望 1 封明日汇总, 实际 {n_summary}"
assert '[DDL·明日]' in SENT_EMAILS[0]['subject']
print(f"OK: 12:00 明日档触发, 主题={SENT_EMAILS[0]['subject']}")

# ===== 测试 3: 模拟 deadline - 30min 跑 (紧急档) =====
print("\n=== 测试 3: 紧急档 (Lab14 deadline - 30min) ===")
SENT_EMAILS.clear()
# 拿 Lab14 的 deadline
lab14_id = 'manual:Lab14 课后上机'
schedule = state_io.load_schedule()
lab14_deadline = dt.datetime.fromisoformat(schedule[lab14_id]['deadline'])
mock_now = lab14_deadline - dt.timedelta(minutes=29)  # 紧急档触发后 1 分钟
print(f"[test] Lab14 deadline = {lab14_deadline}, mock now = {mock_now}")

schedule = state_io.load_schedule()
sent_log = state_io.load_sent_log()
n_summary = _send_summary_emails(schedule, sent_log, mock_now)
n_urgent = _send_urgent_emails(schedule, sent_log, mock_now)
state_io.save_sent_log(sent_log)

print(f"[test] 紧急档: 汇总={n_summary}, 紧急={n_urgent}, 总邮件={len(SENT_EMAILS)}")
# 预期: 1 封一周档 (学期大作业 7 天后) + 1 封紧急 (Lab14) = 2 封
assert n_urgent == 1, f"期望 1 封紧急, 实际 {n_urgent}"
# 找到紧急档那封
urgent_emails = [e for e in SENT_EMAILS if '[DDL·紧急]' in e['subject']]
assert len(urgent_emails) == 1
assert 'Lab14' in urgent_emails[0]['subject']
print(f"OK: 紧急档触发, 主题={urgent_emails[0]['subject']}")

# ===== 测试 4: 紧急档兜底 (deadline - 4min) =====
print("\n=== 测试 4: 紧急档兜底 (deadline - 4min) ===")
SENT_EMAILS.clear()
mock_now = lab14_deadline - dt.timedelta(minutes=3)
print(f"[test] mock now = {mock_now}")

schedule = state_io.load_schedule()
sent_log = state_io.load_sent_log()
n_summary = _send_summary_emails(schedule, sent_log, mock_now)
n_urgent = _send_urgent_emails(schedule, sent_log, mock_now)
state_io.save_sent_log(sent_log)

print(f"[test] 兜底: 汇总={n_summary}, 紧急={n_urgent}, 总邮件={len(SENT_EMAILS)}")
# 预期: 1 封兜底 (Lab14 urgent_backup)
assert n_urgent == 1, f"期望 1 封兜底, 实际 {n_urgent}"
assert '兜底' in SENT_EMAILS[0]['subject']
print(f"OK: 紧急档兜底触发, 主题={SENT_EMAILS[0]['subject']}")

# ===== 测试 5: 重复跑不重发 =====
print("\n=== 测试 5: 重复跑同一时刻, 不重发 ===")
SENT_EMAILS.clear()
mock_now = dt.datetime.combine(now.date(), dt.time(9, 1))  # 跟测试 1 同一时刻

schedule = state_io.load_schedule()
sent_log = state_io.load_sent_log()
n_summary = _send_summary_emails(schedule, sent_log, mock_now)
n_urgent = _send_urgent_emails(schedule, sent_log, mock_now)
state_io.save_sent_log(sent_log)

print(f"[test] 重复跑: 汇总={n_summary}, 紧急={n_urgent}, 总邮件={len(SENT_EMAILS)}")
assert n_summary == 0, f"期望 0 封汇总 (已发过), 实际 {n_summary}"
assert n_urgent == 0, f"期望 0 封紧急 (已发过), 实际 {n_urgent}"
print("OK: 重复跑不重发")

# ===== 测试 6: del 指令 =====
print("\n=== 测试 6: del 指令删 DDL ===")
r = manual_ddls.delete_by_title('Lab14 课后上机')
assert r['ok']
assert r['deleted'] == ['Lab14 课后上机']
# 重算 schedule (因为 del 了)
import scrape
scrape.scrape_all(is_monday=False)
print("OK: del 删除 + 重算 schedule")

print("\n=== 端到端测试全部通过 ===")
print(f"\n总共发送 mock 邮件记录: {sum(1 for _ in SENT_EMAILS)}")
