"""Gmail IMAP 收邮件 + 解析指令"""
import imaplib
import email as emaillib
from email.message import Message as EmailMessage
from email.header import decode_header
from email.utils import parsedate_to_datetime
import datetime as dt
from typing import List, Dict, Optional
import config


def _decode_header_value(value: str) -> str:
    """解码邮件头 (可能是 base64 / quoted-printable)"""
    if not value:
        return ''
    parts = decode_header(value)
    out = []
    for content, charset in parts:
        if isinstance(content, bytes):
            out.append(content.decode(charset or 'utf-8', errors='replace'))
        else:
            out.append(content)
    return ''.join(out)


def _get_email_body(msg: EmailMessage) -> str:
    """提取邮件正文 (text/plain 优先)"""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get('Content-Disposition'))
            if content_type == 'text/plain' and 'attachment' not in content_disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or 'utf-8', errors='replace')
        # fallback: text/html
        for part in msg.walk():
            if part.get_content_type() == 'text/html':
                payload = part.get_payload(decode=True)
                if payload:
                    html = payload.decode(part.get_content_charset() or 'utf-8', errors='replace')
                    # 简单去 HTML 标签
                    import re
                    return re.sub(r'<[^>]+>', '', html)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode(msg.get_content_charset() or 'utf-8', errors='replace')
    return ''


def fetch_inbox_emails(since: dt.datetime = None, mark_read: bool = True) -> List[Dict]:
    """拉取 INBOX 未读邮件

    Args:
        since: 只看这个时间之后的邮件 (None = 所有未读)
        mark_read: 是否标记已读

    Returns:
        [{'subject', 'from', 'date', 'body', 'message_id'}, ...]
    """
    if not config.GMAIL_APP_PASSWORD:
        print("[imap] GMAIL_APP_PASSWORD 未配置, 无法收邮件")
        return []

    out = []
    try:
        with imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT) as imap:
            imap.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
            imap.select('INBOX')

            # 搜未读
            if since is not None:
                # imap 日期格式: 01-Jan-2026
                date_str = since.strftime('%d-%b-%Y')
                typ, data = imap.search(None, f'UNSEEN SINCE {date_str}')
            else:
                typ, data = imap.search(None, 'UNSEEN')

            if typ != 'OK' or not data or not data[0]:
                return []

            msg_nums = data[0].split()
            for num in msg_nums:
                typ, msg_data = imap.fetch(num, '(RFC822)')
                if typ != 'OK':
                    continue
                raw = msg_data[0][1]
                msg = emaillib.message_from_bytes(raw)

                subject = _decode_header_value(msg.get('Subject', ''))
                from_addr = _decode_header_value(msg.get('From', ''))
                date_str = msg.get('Date', '')
                try:
                    date = parsedate_to_datetime(date_str)
                except Exception:
                    date = None
                body = _get_email_body(msg)
                msg_id = msg.get('Message-ID', '')

                # 过滤: 只处理来自 QQ 邮箱 (或不是自己发自己) 的指令邮件
                # 自己发自己的会被 Gmail 拒收, 但保险起见过滤 from=GMAIL_USER
                if config.GMAIL_USER.lower() in from_addr.lower():
                    continue

                out.append({
                    'subject': subject.strip(),
                    'from': from_addr,
                    'date': date,
                    'body': body.strip(),
                    'message_id': msg_id,
                    'imap_num': num,
                })

                if mark_read:
                    imap.store(num, '+FLAGS', '\\Seen')
    except Exception as e:
        print(f"[imap] 拉邮件失败: {e}")

    return out


def is_instruction_email(subject: str) -> bool:
    """判断主题是否是 3 种指令之一 (add / del / list)"""
    if not subject:
        return False
    sub = subject.strip()
    for kw in config.INSTRUCTION_SUBJECTS:
        if sub == kw or sub.startswith(kw + ' ') or sub.startswith(kw + ':'):
            return True
    return False


def parse_instruction(subject: str) -> Optional[Dict]:
    """解析指令邮件主题

    Args:
        subject: 邮件主题

    Returns:
        {'action': 'add'|'del'|'list', 'arg': ...}
        None = 不是指令邮件
    """
    sub = (subject or '').strip()
    if sub == 'add':
        return {'action': 'add', 'arg': None}
    if sub.startswith('add '):
        return {'action': 'add', 'arg': sub[4:].strip()}
    if sub == 'del':
        return {'action': 'del', 'arg': None}
    if sub.startswith('del '):
        return {'action': 'del', 'arg': sub[4:].strip()}
    if sub == 'list':
        return {'action': 'list', 'arg': None}
    if sub.startswith('list '):
        return {'action': 'list', 'arg': sub[5:].strip()}
    return None


if __name__ == "__main__":
    # 自测: 解析指令
    cases = [
        ("add", {'action': 'add', 'arg': None}),
        ("add 数据结构期末", {'action': 'add', 'arg': '数据结构期末'}),
        ("del", {'action': 'del', 'arg': None}),
        ("del 数据结构期末大作业", {'action': 'del', 'arg': '数据结构期末大作业'}),
        ("list", {'action': 'list', 'arg': None}),
        ("list 明天", {'action': 'list', 'arg': '明天'}),
        ("[DDL·汇总] 5 项 DDL", None),
        ("", None),
    ]
    fail = 0
    for s, expected in cases:
        got = parse_instruction(s)
        ok = got == expected
        mark = "OK" if ok else "FAIL"
        if not ok:
            fail += 1
        print(f"{mark} | parse_instruction({s!r}) = {got}")
    print(f"\n{'-' * 50}")
    print(f"PASSED: {len(cases) - fail}/{len(cases)}")
