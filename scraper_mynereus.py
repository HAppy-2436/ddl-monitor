"""mynereus 编程帮 DDL 抓取（登录态下）"""
import sys
import datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright
import config


def _parse_time(s: str):
    s = s.strip().replace("/", "-")
    fmts = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y-%m-%d",
        "%m-%d %H:%M",
        "%m-%d",
    ]
    for f in fmts:
        try:
            t = dt.datetime.strptime(s, f)
            if t.year == 1900:
                t = t.replace(year=dt.datetime.now().year)
            return t
        except ValueError:
            continue
    return None


def _is_ddl_row(row: list, header: list) -> bool:
    if len(row) < 3:
        return False
    if row[0] == header[0] and row[1] == header[1] and row[2] == header[2]:
        return False
    if not row[1] or not row[2]:
        return False
    if '暂无' in row[0] or '暂无' in row[1]:
        return False
    return _parse_time(row[2]) is not None


def fetch_ddls() -> list:
    if not config.MYNEREUS_COOKIE.exists():
        print("[mynereus] 无 storage_state, 跳过（先跑 python3 login/mynereus_pwd.py）", flush=True)
        return []
    items = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--no-sandbox", "--single-process", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        ctx = browser.new_context(storage_state=str(config.MYNEREUS_COOKIE))
        page = ctx.new_page()
        try:
            page.goto("http://www.mynereus.com/#/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(8000)
            raw = page.evaluate('''() => {
                const tables = Array.from(document.querySelectorAll('table'));
                const HEADER = ['班级名称', '标题', '截止时间'];
                const matches = tables.filter(t => {
                    const firstRow = t.querySelector('tr');
                    if (!firstRow) return false;
                    const cells = Array.from(firstRow.querySelectorAll('th,td')).map(c => (c.innerText || '').trim());
                    return cells.length >= 3
                        && cells[0] === HEADER[0]
                        && cells[1] === HEADER[1]
                        && cells[2] === HEADER[2];
                });
                const allRows = [];
                for (const m of matches) {
                    let card = m.parentElement;
                    for (let i = 0; i < 5; i++) {
                        if (!card) break;
                        const pcls = (card.className || '').toString();
                        if (pcls.includes('el-card') || pcls.includes('card') || pcls.includes('panel')) break;
                        card = card.parentElement;
                    }
                    const root = card || m.parentElement;
                    const allTablesInCard = Array.from(root.querySelectorAll('table'));
                    for (const t of allTablesInCard) {
                        const rows = Array.from(t.querySelectorAll('tr'));
                        for (const r of rows) {
                            const cells = Array.from(r.querySelectorAll('th,td')).map(c => (c.innerText || c.textContent || '').trim());
                            allRows.push(cells);
                        }
                    }
                }
                return { tableCount: tables.length, headerMatches: matches.length, allRows };
            }''')
            print(f"[mynereus] tables={raw['tableCount']} headerMatches={raw['headerMatches']} allRows={len(raw['allRows'])}", flush=True)
            HEADER = ['班级名称', '标题', '截止时间']
            for row in raw['allRows']:
                if not _is_ddl_row(row, HEADER):
                    continue
                class_name, title, deadline_str = row[0], row[1], row[2]
                t = _parse_time(deadline_str)
                if not t:
                    continue
                items.append({
                    'source': 'mynereus',
                    'title': f"{class_name} - {title}",
                    'deadline': t.isoformat(),
                    'status': '未完成',  # mynereus 进行中的作业 tab 默认就是未完成
                    'url': 'http://www.mynereus.com/#/',
                })
        except Exception as e:
            print(f"[mynereus] 抓取失败: {e}", flush=True)
        browser.close()
    return items
