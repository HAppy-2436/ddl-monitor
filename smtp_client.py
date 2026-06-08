"""Gmail SMTP 发邮件"""
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
import config


def send_email(subject: str, html: str, text: str, to_addr: str = None) -> bool:
    """发邮件 (Gmail SMTP)

    Args:
        subject: 主题
        html: HTML 正文
        text: 纯文本正文 (备选)
        to_addr: 收件人, 默认 QQ_MAIL

    Returns:
        True=成功
    """
    if to_addr is None:
        to_addr = config.QQ_MAIL
    if not config.GMAIL_APP_PASSWORD:
        print("[smtp] GMAIL_APP_PASSWORD 未配置, 无法发邮件")
        return False

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = formataddr(('DDL 监控', config.GMAIL_USER))
        msg['To'] = to_addr

        # 纯文本 + HTML 两个版本
        part_text = MIMEText(text, 'plain', 'utf-8')
        part_html = MIMEText(html, 'html', 'utf-8')
        msg.attach(part_text)
        msg.attach(part_html)

        context = ssl.create_default_context()
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
            server.sendmail(config.GMAIL_USER, to_addr, msg.as_string())
        print(f"[smtp] 已发邮件: {subject}")
        return True
    except Exception as e:
        print(f"[smtp] 发邮件失败: {e}")
        return False


if __name__ == "__main__":
    # 自测: 用真凭据发测试邮件 (需要 .env 配置)
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'send':
        subject = "[DDL·测试] SMTP 发邮件测试"
        text = "这是一封测试邮件, 验证 SMTP 发送链路"
        html = "<h1>测试邮件</h1><p>验证 SMTP 发送链路</p>"
        ok = send_email(subject, html, text)
        print(f"结果: {'OK' if ok else 'FAIL'}")
    else:
        print("用法: python smtp_client.py send")
        print("(需要 .env 配 GMAIL_APP_PASSWORD)")
