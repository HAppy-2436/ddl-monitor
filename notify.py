"""Gmail 邮件发送 + 收件箱拉取（IMAP）
- send_email: 发邮件给 TO_EMAIL
- send_reply_email: reply to 指定发件人
- fetch_reply_emails: 拉 INBOX 里 subject 含 "DDL" 的未读邮件
"""
import imaplib
import email
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.utils import formataddr, parseaddr
import config


def _smtp_send(msg):
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=20) as s:
        s.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
        s.sendmail(config.GMAIL_USER, msg["To"].split(","), msg.as_string())


def send_email(subject, html_body, text_body="", inline_images=None):
    if not all([config.GMAIL_USER, config.GMAIL_APP_PASSWORD, config.TO_EMAIL]):
        print("ERROR: 邮件配置缺失", flush=True)
        return False
    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = formataddr(("DDL Monitor", config.GMAIL_USER))
    msg["To"] = config.TO_EMAIL
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(text_body or html_body, "plain", "utf-8"))
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt)
    for cid, data in (inline_images or {}).items():
        img = MIMEImage(data, "png")
        img.add_header("Content-ID", f"<{cid}>")
        img.add_header("Content-Disposition", "inline", filename=f"{cid}.png")
        msg.attach(img)
    try:
        _smtp_send(msg)
        return True
    except Exception as e:
        print(f"ERROR: send_email 失败: {e}", flush=True)
        return False


def send_reply_email(to_addr, subject, html_body, text_body="", in_reply_to=None):
    if not all([config.GMAIL_USER, config.GMAIL_APP_PASSWORD]):
        print("ERROR: 邮件配置缺失", flush=True)
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject if subject.startswith("Re:") else f"Re: {subject}"
    msg["From"] = formataddr(("DDL Monitor", config.GMAIL_USER))
    msg["To"] = to_addr
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.attach(MIMEText(text_body or html_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    try:
        _smtp_send(msg)
        return True
    except Exception as e:
        print(f"ERROR: send_reply_email 失败: {e}", flush=True)
        return False


def fetch_reply_emails(trigger_substrings=("ddl", "DDL")):
    """拉 INBOX 里 subject 含触发词的未读邮件
    返回 list[dict]: {from_addr, from_name, subject, message_id, body_text}
    """
    if not all([config.GMAIL_USER, config.GMAIL_APP_PASSWORD]):
        print("ERROR: 邮件配置缺失, 跳过 fetch_reply_emails", flush=True)
        return []
    results = []
    try:
        s = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        s.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
        s.select("INBOX")
        # 搜未读
        typ, data = s.search(None, "UNSEEN")
        if typ != "OK" or not data or not data[0]:
            s.logout()
            return []
        for num in data[0].split():
            typ, msg_data = s.fetch(num, "(RFC822)")
            if typ != "OK":
                continue
            raw = msg_data[0][1]
            try:
                msg = email.message_from_bytes(raw)
            except Exception:
                continue
            subj = (msg.get("Subject") or "").strip()
            from_header = msg.get("From", "")
            from_addr = parseaddr(from_header)[1]
            if not from_addr:
                continue
            # 跳过自己 loop 出去的回复 (主题已带 Re:)
            if subj.lower().startswith("re:"):
                continue
            # 主题含触发词
            if not any(subs.lower() in subj.lower() for subs in trigger_substrings):
                continue
            # 拿 body
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    ct = part.get_content_type()
                    if ct == "text/plain":
                        try:
                            body = part.get_payload(decode=True).decode("utf-8", "ignore")
                        except Exception:
                            body = ""
                        break
            else:
                try:
                    body = msg.get_payload(decode=True).decode("utf-8", "ignore")
                except Exception:
                    body = ""
            results.append({
                "uid": num.decode(),
                "from_addr": from_addr,
                "from_name": parseaddr(from_header)[0] or from_addr,
                "subject": subj,
                "message_id": msg.get("Message-ID", ""),
                "body": body[:2000].strip(),
            })
        s.logout()
    except Exception as e:
        print(f"ERROR: fetch_reply_emails 失败: {e}", flush=True)
    return results


def mark_emails_read(uids):
    """标记 IMAP 邮件为已读"""
    if not uids:
        return
    try:
        s = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        s.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
        s.select("INBOX")
        for uid in uids:
            s.store(uid, "+FLAGS", "\\Seen")
        s.logout()
    except Exception as e:
        print(f"ERROR: mark_emails_read 失败: {e}", flush=True)
