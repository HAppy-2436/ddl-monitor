"""mynereus 编程帮 DDL 抓取（登录态下）

两层抓取:
1. 主页表 (class table): 班级任务, DDL 截止时间
2. 班级详情页 (class detail): 班级内具体作业 (用户要求)

输出格式 (对齐 v2):
[{
    'source': '编程帮',
    'title': '数据结构与算法 - [实践]Lab14-课后上机',
    'deadline': '2026-06-08T12:00:00',
    'status': '未完成',
    'url': 'http://www.mynereus.com/#/',
    'class': '数据结构与算法',
}, ...]
"""
import sys
import re
import datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
import state_io

SOURCE_LABEL = '编程帮'

MYNEREUS_COOKIE = state_io.BASE_DIR / 'cookies' / 'mynereus.json'
MYNEREUS_URL = 'http://www.mynereus.com/#/'


def _parse_time(s: str) -> dt.datetime:
    """'2026-06-08 12:00:00' / '2026-06-08 12:00' -> datetime"""
    s = s.strip()
    fmts = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d', '%Y/%m/%d %H:%M')
    for fmt in fmts:
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    # 尝试 ISO
    try:
        return dt.datetime.fromisoformat(s)
    except Exception:
        pass
    return None


def _is_logged_in(page) -> bool:
    """判断是否登录: 登录 dialog 不在 + 出现用户头像"""
    try:
        # 1) 登录 dialog 不可见 (登录后会隐藏/消失)
        dialog = page.locator(".el-dialog").first
        try:
            dialog_visible = dialog.is_visible() if dialog.count() > 0 else False
        except Exception:
            dialog_visible = True  # 出错时保守视为还可见 (未登录)
        # 2) 出现 el-icon-user (登录后右上角用户头像)
        has_user_icon = page.evaluate('() => !!document.querySelector(".el-icon-user")')
        return (not dialog_visible) and has_user_icon
    except Exception:
        return False


def fetch_main_table(page, now: dt.datetime) -> list:
    """抓主页表: 班级名称 + 标题 + 截止时间 + 状态"""
    items = []
    # 等表格渲染
    try:
        page.wait_for_timeout(8000)
    except Exception:
        pass
    # 解析页面里的表格 (JS 渲染后)
    rows = page.evaluate('''() => {
        const tables = Array.from(document.querySelectorAll('table'));
        const out = [];
        for (const tb of tables) {
            const headers = Array.from(tb.querySelectorAll('th, thead td')).map(h => h.innerText.trim());
            if (!headers.some(h => h.includes('班级') || h.includes('截止'))) continue;
            const trs = Array.from(tb.querySelectorAll('tbody tr, tr')).slice(1);
            for (const tr of trs) {
                const cells = Array.from(tr.querySelectorAll('td')).map(c => c.innerText.trim());
                if (cells.length >= 3) {
                    out.push({headers, cells});
                }
            }
        }
        return out;
    }''')
    for row in rows:
        cells = row['cells']
        headers = row['headers']
        # 找: 班级名称 / 标题 / 截止时间 / 状态
        cls = title = deadline_str = status = ''
        for i, h in enumerate(headers):
            if i >= len(cells):
                break
            if '班级' in h:
                cls = cells[i]
            elif '标题' in h or '作业' in h or '任务' in h:
                title = cells[i]
            elif '截止' in h:
                deadline_str = cells[i]
            elif '状态' in h:
                status = cells[i]
        # 兜底: 如果没识别到, 按位置猜
        if not cls and len(cells) >= 4:
            cls, title, deadline_str, status = cells[0], cells[1], cells[2], cells[3]
        elif not cls and len(cells) == 3:
            cls, title, deadline_str = cells[0], cells[1], cells[2]
        if not title or not deadline_str:
            continue
        deadline = _parse_time(deadline_str)
        if deadline is None:
            continue
        # 过滤已完成
        if '已交' in status or '已完成' in status or '已批' in status or '已批阅' in status:
            continue
        items.append({
            'source': SOURCE_LABEL,
            'title': f'{cls} - {title}' if cls else title,
            'deadline': deadline.isoformat(),
            'status': status if status else '未完成',
            'url': MYNEREUS_URL,
            'class': cls,
        })
    return items


def fetch_class_details(page, classes: list, now: dt.datetime) -> list:
    """进每个班级详情页抓作业 (调用方传入 class 名 + URL 列表)

    注: 编程帮的"班级详情"可能没标准 URL, 实际操作时用 hash 路由.
    此函数保留接口, 实际实现依赖具体页面结构.
    """
    # TODO: 实现班级详情作业抓取
    # 编程帮的班级详情路由是 hash, 实际抓取时要观察页面元素
    # 暂留空, 避免乱抓出错
    return []


def fetch() -> list:
    """抓编程帮 DDL (主页表)"""
    if not MYNEREUS_COOKIE.exists():
        print(f"[mynereus] 无 storage_state {MYNEREUS_COOKIE}, 跳过 (需先跑 login_mynereus_pwd.py)", flush=True)
        return []

    items = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                args=["--no-sandbox", "--single-process", "--disable-dev-shm-usage", "--disable-gpu"]
            )
            ctx = browser.new_context(storage_state=str(MYNEREUS_COOKIE))
            page = ctx.new_page()
            try:
                page.goto(MYNEREUS_URL, wait_until='domcontentloaded', timeout=30000)
                page.wait_for_timeout(5000)
                if not _is_logged_in(page):
                    print("[mynereus] 未登录或登录态过期", flush=True)
                    return []
                now = dt.datetime.now()
                main_items = fetch_main_table(page, now)
                if main_items:
                    print(f"[mynereus] 主页表: {len(main_items)} 条任务", flush=True)
                items.extend(main_items)
                # 班级详情暂不抓 (TODO: 等主页表稳定后再加)
            except Exception as e:
                print(f"[mynereus] 抓取失败: {e}", flush=True)
            finally:
                browser.close()
    except Exception as e:
        print(f"[mynereus] playwright 启动失败: {e}", flush=True)

    return items


if __name__ == "__main__":
    print("=== 抓取编程帮 DDL ===")
    items = fetch()
    print(f"\n共 {len(items)} 条:")
    for it in items:
        print(f"  [{it.get('class', '?')}] {it['title']} - {it['deadline']} (状态: {it['status']})")
