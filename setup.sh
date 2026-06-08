#!/bin/bash
# DDL 监控 - 服务器一键初始化
# 在全新服务器上部署时跑一次
set -e
cd "$(dirname "$0")"

echo "=== DDL 监控初始化 ==="
echo ""

# 1. 基础依赖
echo "[1/6] 检查 Python..."
if ! command -v python3 &> /dev/null; then
    echo "  python3 未安装, 请先 apt install python3 python3-pip"
    exit 1
fi
python3 --version

# 2. venv
echo "[2/6] 创建 venv..."
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet playwright python-dotenv

# 3. chromium
echo "[3/6] 安装 chromium (playwright)..."
python3 -m playwright install chromium

# 4. .env
echo "[4/6] 配置 .env..."
if [ ! -f .env ]; then
    cat > .env <<EOF
GMAIL_USER=hahappy2436@gmail.com
GMAIL_APP_PASSWORD=YOUR_GMAIL_APP_PASSWORD_HERE
QQ_MAIL=2357356249@qq.com
EOF
    echo "  已创建 .env, 请编辑填入 GMAIL_APP_PASSWORD (Gmail 应用专用密码)"
    echo "  获取: https://myaccount.google.com/apppasswords"
    chmod 600 .env
fi

# 5. 登录态 (手动跑)
echo "[5/6] 登录态 (cookies/) 需要手动跑..."
echo "  学习通:  python3 login_chaoxing_qr.py   (扫码登录)"
echo "  编程帮:  python3 login_mynereus_pwd.py  (密码登录)"
echo "  完成后 cookies/chaoxing.json + cookies/mynereus.json 会生成"

# 6. cron 配置
echo "[6/6] 配置 cron..."
(crontab -l 2>/dev/null | grep -v -E 'ddl-monitor/(scrape|main)\.sh' ; cat <<EOF
# DDL 监控: 每天 8:00 全量抓取
0 8 * * * /home/ha/ddl-monitor/scrape.sh >> /home/ha/ddl-monitor/logs/scrape.log 2>&1

# DDL 监控: 每分钟发邮件
* * * * * /home/ha/ddl-monitor/main.sh >> /home/ha/ddl-monitor/logs/main.log 2>&1
EOF
) | crontab -
crontab -l

echo ""
echo "=== 初始化完成 ==="
echo "接下来:"
echo "  1. 编辑 .env 填 GMAIL_APP_PASSWORD"
echo "  2. 跑 login_chaoxing_qr.py + login_mynereus_pwd.py 登录"
echo "  3. 等 8:00 看 scrape.log / 每分钟看 main.log"
echo "  4. 收到第一封 [DDL·汇总] 邮件 = 成功"
