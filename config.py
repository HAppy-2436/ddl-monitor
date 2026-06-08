"""加载 .env 凭据 + 全局配置

Gmail SMTP/IMAP 用 app password (hahappy2436@gmail.com):
- SMTP_HOST=smtp.gmail.com:587
- IMAP_HOST=imap.gmail.com:993

QQ 邮箱收件地址: 2357356249@qq.com
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / '.env'

load_dotenv(ENV_FILE)


# Gmail 发件账户
GMAIL_USER = os.environ.get('GMAIL_USER', 'hahappy2436@gmail.com')
GMAIL_APP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD', '')

# QQ 邮箱收件地址
QQ_MAIL = os.environ.get('QQ_MAIL', '2357356249@qq.com')

# SMTP / IMAP
SMTP_HOST = 'smtp.gmail.com'
SMTP_PORT = 587
IMAP_HOST = 'imap.gmail.com'
IMAP_PORT = 993

# 凭据缺失检查
def check_credentials():
    missing = []
    if not GMAIL_USER:
        missing.append('GMAIL_USER')
    if not GMAIL_APP_PASSWORD:
        missing.append('GMAIL_APP_PASSWORD')
    if not QQ_MAIL:
        missing.append('QQ_MAIL')
    if missing:
        raise RuntimeError(f".env 缺少配置: {', '.join(missing)}")


# DDL 指令白名单
INSTRUCTION_SUBJECTS = ('add', 'del', 'list')
INSTRUCTION_FROM_FILTER = GMAIL_USER  # 只处理自己从 QQ 邮箱发到 Gmail 的指令


if __name__ == "__main__":
    check_credentials()
    print(f"GMAIL_USER: {GMAIL_USER}")
    print(f"QQ_MAIL: {QQ_MAIL}")
    print(f"SMTP: {SMTP_HOST}:{SMTP_PORT}")
    print(f"IMAP: {IMAP_HOST}:{IMAP_PORT}")
    print(f"凭据完整 ✓")
