# DDL 监控 (ddl-monitor)

自动抓取**学习通**和**编程帮**的作业 DDL, 按 5 档规则发邮件到 QQ 邮箱提醒. 也支持邮件手动加 DDL.

> **v2.0 重构版** - schedule 模式 + cron 调度 + 过期忽略 + GitHub 托管

---

## 功能

- **自动抓取**:
  - 学习通: 作业 tab (每天) + 考试/任务 tab (每周一)
  - 编程帮: 主页表 (每天, 班级详情 TODO)
- **5 档邮件提醒** (按截止时间实时分档):
  - 09:00 每日汇总 (所有未完成 DDL)
  - 12:00 明日截止 (≤36h)
  - 14:00 一周截止 (154-178h)
  - 18:00 今日截止 (≤6h)
  - DDL-30min 紧急档 + DDL-4min 兜底档 (单条)
- **手动加 DDL**: 发邮件到 `hahappy2436@gmail.com`, 主题 `add` / `del` / `list`
- **过期忽略**: scrape 抓到的过期 DDL 自动从 schedule 删除
- **QQ 邮箱自动归类**: 主题 `[DDL·...]` 进 DDL 文件夹, 微信推送开着

---

## 邮件主题格式

| 主题前缀 | 含义 | 微信推送 |
|---------|------|---------|
| `[DDL·汇总]` | 每天 09:00 列出所有未完成 DDL | 响 |
| `[DDL·明日]` | 每天 12:00 列 ≤36h 内截止 | 响 |
| `[DDL·一周]` | 每天 14:00 列 154-178h 窗口 | 响 |
| `[DDL·今日]` | 每天 18:00 列 ≤6h 内截止 | 响 |
| `[DDL·紧急]` | 截止前 30min + 4min 兜底 | 响 |
| `[DDL·回复]` | add/del/list 指令回复 | 响 |
| `[DDL·警告]` | scrape 异常 | 响 |

---

## 手动加 DDL (QQ 邮箱 -> Gmail)

**加 DDL**:
```
收件人: hahappy2436@gmail.com
主题: add
正文:
标题: 阿里云ACA考试
截止: 2026-06-15 14:00
备注: ACA 备考
```

**删 DDL** (严格匹配标题):
```
主题: del 数据结构期末大作业
```

**查 DDL**:
```
主题: list
```

支持日期格式:
- `2026-06-15 14:00` / `2026/06/15 14:00` / `2026.06.15 14:00`
- `6-15 14:00` (无年份默认今年, 过去日期自动明年)
- `6月15日 14:00` / `6月15日14:00` (中文, 可无空格)
- `明天 14:00` / `后天 14:00` / `今天 14:00` / `下周一 14:00`
- `2026-06-15` (只日期, 默认 23:59)
- `2026-06-15T14:00:00` (ISO)

> 注意: 邮件正文中 `标题` / `截止` / `备注` 后的冒号必须用**英文半角** `:` (中文全角 `：` 不行)

---

## 部署

### 1. 服务器初始化 (一次性)

```bash
# 在服务器上
git clone https://github.com/HAppy-2436/ddl-monitor.git ~/ddl-monitor
cd ~/ddl-monitor
bash setup.sh
```

`setup.sh` 会:
1. 检查 Python3
2. 创建 venv + 装 playwright
3. 装 chromium
4. 创建 `.env` 模板 (你编辑填 Gmail app password)
5. 提示你跑登录脚本
6. 配置 2 条 cron

### 2. 登录 (一次性, 7 天有效)

```bash
cd ~/ddl-monitor
source .venv/bin/activate
python3 login_chaoxing_qr.py    # 学习通扫码
python3 login_mynereus_pwd.py   # 编程帮账号密码
```

完成后 `cookies/chaoxing.json` + `cookies/mynereus.json` 生成.

### 3. 配 Gmail 应用专用密码

- 访问 https://myaccount.google.com/apppasswords
- 生成新密码, 填到 `.env` 的 `GMAIL_APP_PASSWORD`

### 4. 配 QQ 邮箱收信规则

- QQ 邮箱网页 -> 设置 -> 收信规则 -> 新建
- 条件: 主题包含 `[DDL·]`
- 动作: 移动到文件夹 `DDL` (你建好)
- 微信推送: QQ 邮箱绑定微信 "邮箱助手", 全部邮件推送开着

### 5. 验证

- 等 8:00 看 `logs/scrape.log` 有抓取记录
- 等下一分钟看 `logs/main.log` 有 `tick @` 记录
- 收到第一封 `[DDL·汇总]` 邮件 = 成功

---

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│  服务器: 23.95.146.206                                       │
│                                                              │
│  cron 调度 (系统自带)                                        │
│   ├─ 0 8 * * *  →  scrape.sh  →  scrape.py                  │
│   └─ * * * * *  →  main.sh    →  main.py                    │
│                                                              │
│  4 个 JSON 持久化                                            │
│   ├─ ddl_list.json    (平台抓的 DDL)                         │
│   ├─ manual_ddls.json (手动加的 DDL)                         │
│   ├─ schedule.json    (send_at 列表)                         │
│   └─ sent_log.json    (已发记录)                             │
│                                                              │
│  Gmail SMTP (发) / IMAP (收)                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 文件结构

```
ddl-monitor/
├── config.py              # .env 加载
├── date_parser.py         # 多格式日期解析
├── schedule_calc.py       # 5 档 send_at 计算
├── state_io.py            # JSON 持久化 + 文件锁
├── smtp_client.py         # Gmail SMTP
├── imap_client.py         # Gmail IMAP + 指令解析
├── email_render.py        # 5 档邮件渲染
├── manual_ddls.py         # 手动 DDL 增删查
├── process_replies.py     # 指令邮件处理
├── scrape.py              # 抓取 + schedule 重算
├── main.py                # 每分钟主入口
├── login_chaoxing_qr.py   # 学习通扫码登录
├── login_mynereus_pwd.py  # 编程帮密码登录
├── scrapers/
│   ├── chaoxing.py        # 学习通 scraper
│   └── mynereus.py        # 编程帮 scraper
├── setup.sh               # 服务器一键初始化
├── scrape.sh              # 抓取入口
├── main.sh                # 主循环入口
├── .env                   # 凭据 (chmod 600, 不进 git)
├── cookies/               # 登录态 (不进 git)
├── logs/                  # 日志 (不进 git)
└── ddl_list.json / manual_ddls.json / schedule.json / sent_log.json  # 运行时数据
```

---

## 资源占用 (1h1g 服务器)

- **scrape 每天 1 次** (8:00, 30-90 秒): 启 chromium 350MB, 跑完释放
- **main 每分钟 1 次** (1-2 秒): 进程峰值 15MB, 跑完释放
- **scrape 期间 main 跳过** (文件锁)
- **总内存**: 平时 50MB, scrape 峰值 400MB (1GB 余 600MB)
- **网络**: 每天 < 20MB
- **磁盘**: < 10MB (日志 + JSON)

---

## 维护

- **看 scrape 日志**: `tail -f logs/scrape.log`
- **看 main 日志**: `tail -f logs/main.log`
- **看 cron**: `crontab -l`
- **手动触发 scrape**: `bash scrape.sh`
- **手动触发 main**: `bash main.sh`
- **更新代码**: `cd ~/ddl-monitor && git pull`
- **重登学习通** (cookie 7 天过期): `python3 login_chaoxing_qr.py`

---

## GitHub

https://github.com/HAppy-2436/ddl-monitor

提交历史:
- v1.0 烂代码基线 (cron + keep_alive)
- v2.0 重构 (schedule 模式 + cron + 3 指令 + GitHub 托管)
