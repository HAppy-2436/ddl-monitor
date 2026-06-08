# DDL Monitor

> 部署在 23.95.146.206 上的 DDL 监控服务。每分钟跑一次，按"截止具体时间"智能发提醒：11:30 汇总、14:00/18:00 发 ≤2 天的、30 分钟内紧急档每分钟轰炸 5 次。

## 频率逻辑

| 时间 | 触发 | 发什么 |
|------|------|--------|
| 11:30 | 每天 | **所有未完成 DDL**（按截止时间升序，排除已过期）|
| 14:00 | 每天 | 剩余 ≤ 2 天的 DDL |
| 18:00 | 每天 | 剩余 ≤ 2 天的 DDL |
| 其他分钟 | 每分钟 | **0 < 剩余 ≤ 30 分钟**的 DDL（极紧急）|

每个 slot 每天每条 DDL 最多发一次（state.json 跟踪）。已完成作业自动跳过。

## 完成判断

- 作业 status 字段显示"已完成 / 已交 / 已批改 / 已批阅"
- 截止时间已过期
- → 不再发任何提醒

## 目录

```
ddl-monitor/
├── .env                 # 你的私密配置（chmod 600）
├── .env.example         # 配置模板
├── state.json           # 已提醒 + 已完成记录
├── cache.json           # scrape 缓存（5 分钟 TTL）
├── .main.lock           # 进程锁（防并发）
├── cookies/             # 持久化登录态
│   ├── chaoxing.json
│   └── mynereus.json
├── login/
│   ├── chaoxing_qr.py   # 学习通扫码登录
│   └── mynereus_pwd.py  # 编程帮账号密码登录
├── scrapers/
│   ├── chaoxing.py      # 枚举 9 门课 + work/list iframe 抓取
│   └── mynereus.py      # 主页"进行中的作业"表格
├── notify.py            # Gmail 发送 + IMAP 拉回复
├── main.py              # 主入口
├── run.sh               # cron 入口
├── logs/                # cron 日志
└── state.py
```

## 一次性配置

### 1. 填 .env

```bash
cd ~/ddl-monitor
cp .env.example .env
chmod 600 .env
vim .env   # 填：
# - GMAIL_USER: 发件 Gmail
# - GMAIL_APP_PASSWORD: 应用专用密码（myaccount.google.com → 安全 → 两步验证 → 应用专用密码）
# - TO_EMAIL: 收提醒的邮箱
# - MYNEREUS_USERNAME / MYNEREUS_PASSWORD: 编程帮账号密码
```

### 2. 首次登录

```bash
source .venv/bin/activate
python3 login/mynereus_pwd.py       # 编程帮 - 账号密码直登
python3 login/chaoxing_qr.py       # 学习通 - 扫码（终端会发二维码邮件到 TO_EMAIL）
# 收到邮件后用学习通 APP 扫一下, 等几秒终端会显示登录成功
```

### 3. 配 cron

```bash
* * * * * /home/ha/ddl-monitor/run.sh >> /home/ha/ddl-monitor/logs/cron.log 2>&1
```

### 4. 验证

```bash
./run.sh                            # 跑一次
tail -f logs/cron.log                # 看日志
```

## 用户主动查询

发邮件到 `hahappy2436@gmail.com`：
- 主题含 `DDL`（不区分大小写）
- 内容随意

下次 cron 触发时（最多等 1 分钟），服务会回复"当前所有未完成 DDL"列表。

## 维护

- **学习通 cookie 7 天失效**：跑 `python3 login/chaoxing_qr.py` 重新扫码
- **编程帮密码改了**：改 `.env` + 重跑 `python3 login/mynereus_pwd.py`
- **看 cron 日志**：`tail -f ~/ddl-monitor/logs/cron.log`
- **手动跑一次**：`cd ~/ddl-monitor && source .venv/bin/activate && python3 main.py`
- **清掉残留进程**（1h1g 内存紧张时）：`pkill -9 -f 'main.py|chromium'; rm -f .main.lock`

## 故障排查

- **chromium OOM**：1h1g 跑 chromium 紧巴巴，确保 `.main.lock` 残留进程已清
- **学习通抓不到 DDL**：页面结构可能改版了，看 cron.log 里的 HTML 片段
- **Gmail 认证失败**：重新生成"应用专用密码"
- **Gmail IMAP 拉不到回复邮件**：检查 `GMAIL_APP_PASSWORD`（同账号 SMTP+IMAP 用同一个 app password）

## 设计细节

- **scrape cache TTL = 5 分钟**：每分钟 cron 触发但 scrape 不每次跑，节省资源
- **进程锁 `.main.lock`**：PID 文件防 cron 并发触发冲突
- **state.json 跟踪**每个 (item_key, slot, date) 三元组是否已发
- **完成检测**结合 scraper status 字段 + deadline 时间判断，更鲁棒
