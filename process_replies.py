"""处理指令邮件 (add / del / list)

每分钟 main.py 调一次:
1. IMAP 拉未读邮件
2. 过滤出指令邮件 (主题是 add/del/list)
3. 解析 + 执行 + 回复

add: 解析正文 key: value, 加 DDL, 回复已添加 + 下次提醒时间
del: 严格匹配标题删 DDL (任何平台/手动都行), 回复已删或没找到
list: 列所有 DDL (按截止时间升序)
"""
import datetime as dt
import imaplib
from typing import List, Dict

import imap_client
import manual_ddls
import smtp_client
import email_render
import state_io


# 抓取所有 DDL (平台 + 手动) 合并用于 list
def _all_ddls() -> List[Dict]:
    items = []
    ddl_list = state_io.load_ddl_list()
    for ddl_id, d in ddl_list.items():
        items.append({
            'id': ddl_id,
            'source': d.get('source', '?'),
            'title': d.get('title', ''),
            'deadline': d.get('deadline', ''),
            'url': d.get('url', ''),
            'note': d.get('note', ''),
            'status': d.get('status', ''),
        })
    items.extend(manual_ddls.list_all())
    # 排序
    def parse(it):
        try:
            return dt.datetime.fromisoformat(it['deadline'])
        except Exception:
            return dt.datetime.max
    return sorted(items, key=parse)


def _handle_add(email: Dict) -> Dict:
    """处理 add 指令"""
    body = email.get('body', '')
    fields = manual_ddls.parse_kv_body(body)
    title = fields.get('标题', '').strip()
    deadline_str = fields.get('截止', '').strip()
    note = fields.get('备注', '').strip()
    if not title:
        return {'ok': False, 'error': '正文缺少 "标题" 字段'}
    if not deadline_str:
        return {'ok': False, 'error': '正文缺少 "截止" 字段'}
    return manual_ddls.add(title, deadline_str, note)


def _handle_del(email: Dict) -> Dict:
    """处理 del 指令 (arg 是要删的完整标题)"""
    arg = email.get('arg', '').strip()
    if not arg:
        return {'ok': False, 'error': 'del 需要指定标题, 例: del 数据结构期末大作业'}

    # 先在 manual 里严格匹配
    result = manual_ddls.delete_by_title(arg)
    if result['ok']:
        return result

    # 在 ddl_list (平台抓的) 里也找一下
    ddl_list = state_io.load_ddl_list()
    deleted = []
    for ddl_id, d in list(ddl_list.items()):
        if d.get('title', '').strip() == arg:
            del ddl_list[ddl_id]
            deleted.append(d.get('title', ''))
    if deleted:
        state_io.save_ddl_list(ddl_list)
        return {'ok': True, 'deleted': deleted}

    return {'ok': False, 'keyword': arg, 'error': '没找到完全匹配的标题'}


def _handle_list(email: Dict) -> Dict:
    """处理 list 指令"""
    items = _all_ddls()
    return {'items': items}


def process_inbox() -> List[Dict]:
    """主入口: 处理 INBOX 中所有指令邮件, 返回处理日志

    副作用: 每处理一封指令, 发一封回复邮件
    """
    log = []
    emails = imap_client.fetch_inbox_emails(mark_read=True)
    for em in emails:
        subject = em.get('subject', '').strip()
        instruction = imap_client.parse_instruction(subject)
        if instruction is None:
            continue  # 不是指令邮件
        action = instruction['action']
        em['arg'] = instruction['arg']

        if action == 'add':
            result = _handle_add(em)
        elif action == 'del':
            result = _handle_del(em)
        elif action == 'list':
            result = _handle_list(em)
        else:
            result = {'ok': False, 'error': f'未知 action: {action}'}

        # 发回复
        sub, html, text = email_render.render_reply(action, result)
        to_addr = imap_client._decode_header_value(em.get('from', ''))
        # 提取 email 地址 (可能 "Name <addr@x.com>" 格式)
        import re
        m = re.search(r'[\w.+-]+@[\w.-]+', to_addr)
        to_addr = m.group(0) if m else None
        if to_addr:
            smtp_client.send_email(sub, html, text, to_addr=to_addr)

        log.append({
            'subject': subject,
            'action': action,
            'result': result,
        })
    return log


if __name__ == "__main__":
    # 单元测试: mock imap_client 返回假邮件
    import sys
    sys.path.insert(0, '.')
    import tempfile
    import os
    tmpdir = tempfile.mkdtemp()
    os.chdir(tmpdir)
    from pathlib import Path
    import state_io as si
    si.BASE_DIR = Path(tmpdir)
    si.DDL_LIST_FILE = si.BASE_DIR / 'ddl_list.json'
    si.MANUAL_DDLS_FILE = si.BASE_DIR / 'manual_ddls.json'
    si.SCHEDULE_FILE = si.BASE_DIR / 'schedule.json'
    si.SENT_LOG_FILE = si.BASE_DIR / 'sent_log.json'

    # mock fetch_inbox_emails
    import imap_client as ic
    original_fetch = ic.fetch_inbox_emails
    ic.fetch_inbox_emails = lambda **kw: [
        {
            'subject': 'add',
            'from': 'me <2357356249@qq.com>',
            'body': '标题: 测试DDL\n截止: 2026-06-15 14:00\n备注: 测试',
            'message_id': '<1@qq.com>',
            'imap_num': b'1',
        },
        {
            'subject': 'del 数据结构期末大作业',  # 不存在
            'from': 'me <2357356249@qq.com>',
            'body': '',
            'message_id': '<2@qq.com>',
            'imap_num': b'2',
        },
        {
            'subject': 'list',
            'from': 'me <2357356249@qq.com>',
            'body': '',
            'message_id': '<3@qq.com>',
            'imap_num': b'3',
        },
        {
            'subject': '[DDL·汇总] 5 项 DDL',  # 不是指令, 应跳过
            'from': 'DDL 监控 <hahappy2436@gmail.com>',
            'body': '汇总',
            'message_id': '<4@qq.com>',
            'imap_num': b'4',
        },
    ]

    # mock send_email (避免真发)
    import smtp_client as sc
    sc.send_email = lambda *a, **kw: print(f"[mock send] {a[0]}") or True

    log = process_inbox()
    assert len(log) == 3, f"应该处理 3 条指令, 实际 {len(log)}"
    assert log[0]['action'] == 'add' and log[0]['result']['ok']
    assert log[1]['action'] == 'del' and not log[1]['result']['ok']
    assert log[2]['action'] == 'list' and len(log[2]['result']['items']) == 1
    print("OK: process_inbox 3 条指令 + 1 条 DDL 邮件跳过")
    print(f"\n=== process_replies 自测通过 ===")

    # 恢复
    ic.fetch_inbox_emails = original_fetch
