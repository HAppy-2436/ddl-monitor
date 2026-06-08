"""学习通 DDL 抓取（登录态下）

流程:
1. playwright 打开 fycourse 课程列表, 抓所有 entercoursenewfy URL
2. 对每门课打开 entercoursenewfy, 点击"作业" tab, 从生成的 iframe (work/list) 拿 HTML
3. 解析未交/未完成作业 + 剩余时间 -> 截止时间
"""
import sys
import re
import datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright
import config


def _parse_remaining(text: str, now: dt.datetime):
    text = text.strip()
    m = re.search(r'剩余\s*(\d+)\s*天\s*(\d+)\s*小时\s*(\d+)\s*分钟', text)
    if m:
        d, h, mi = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return now + dt.timedelta(days=d, hours=h, minutes=mi)
    m = re.search(r'剩余\s*(\d+)\s*小时\s*(\d+)\s*分钟', text)
    if m:
        return now + dt.timedelta(hours=int(m.group(1)), minutes=int(m.group(2)))
    m = re.search(r'剩余\s*(\d+)\s*分钟', text)
    if m:
        return now + dt.timedelta(minutes=int(m.group(1)))
    m = re.search(r'剩余\s*(\d+)\s*天', text)
    if m:
        return now + dt.timedelta(days=int(m.group(1)))
    return None


def _parse_work_list_html(html: str, course_name: str, now: dt.datetime) -> list:
    items = []
    for m in re.finditer(r'<li[^>]*>(.*?)</li>', html, re.S):
        content = m.group(1)
        if '剩余' not in content:
            continue
        title_m = re.search(r'class="overHidden2\s*fl"[^>]*>\s*([^<]+)', content)
        if not title_m:
            continue
        title = title_m.group(1).strip()
        status_m = re.search(r'class="status\s*fl"[^>]*>\s*([^<]+)', content)
        status = status_m.group(1).strip() if status_m else ''
        time_m = re.search(r'剩余\s*(\d+\s*天\s*\d+\s*小时\s*\d+\s*分钟|\d+\s*小时\s*\d+\s*分钟|\d+\s*分钟|\d+\s*天)', content)
        if not time_m:
            continue
        deadline = _parse_remaining(time_m.group(0), now)
        if deadline is None:
            continue
        items.append({
            'source': 'chaoxing',
            'title': f"[{course_name}] {title}",
            'deadline': deadline.isoformat(),
            'status': status if status else '未知',
            'url': 'https://i.mooc.chaoxing.com/space/index',
        })
    return items


def fetch_ddls() -> list:
    if not config.CHAOXING_COOKIE.exists():
        print("[cx] 无 storage_state, 跳过（先跑 python3 login/chaoxing_qr.py）", flush=True)
        return []
    items = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--no-sandbox", "--single-process", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        ctx = browser.new_context(storage_state=str(config.CHAOXING_COOKIE))
        page = ctx.new_page()
        try:
            page.goto('https://fycourse.fanya.chaoxing.com/fyportal/courselist/course',
                      wait_until='domcontentloaded', timeout=30000)
            page.wait_for_timeout(5000)
            courses = page.evaluate('''() => {
                const items = Array.from(document.querySelectorAll('.course-list .w_couritem, [class*=couritem]'));
                return items.map(it => {
                    const nameEl = it.querySelector('.overHidden2, .courseName, [class*=name]');
                    const link = it.querySelector('a[href*="entercoursenewfy"]');
                    return {
                        name: nameEl ? nameEl.innerText.trim() : '',
                        href: link ? link.href : ''
                    };
                }).filter(x => x.href);
            }''')
            print(f"[cx] 找到 {len(courses)} 门课", flush=True)
            now = dt.datetime.now()
            for c in courses:
                try:
                    page.goto(c['href'], wait_until='domcontentloaded', timeout=20000)
                    page.wait_for_timeout(2000)
                except Exception as e:
                    print(f"[cx] {c['name']}: 进入失败 {e}", flush=True)
                    continue
                try:
                    page.locator('li:has-text("作业")').first.click(timeout=5000)
                    page.wait_for_timeout(4000)
                except Exception as e:
                    print(f"[cx] {c['name']}: 点作业失败 {e}", flush=True)
                    continue
                work_frame = None
                for f in page.frames:
                    if 'work/list' in f.url:
                        work_frame = f
                        break
                if not work_frame:
                    print(f"[cx] {c['name']}: 无 work/list iframe", flush=True)
                    continue
                try:
                    html = work_frame.content()
                except Exception:
                    html = work_frame.evaluate('() => document.documentElement.outerHTML')
                course_items = _parse_work_list_html(html, c['name'], now)
                if course_items:
                    print(f"[cx]   {c['name'][:20]}: {len(course_items)} 条作业", flush=True)
                items.extend(course_items)
        except Exception as e:
            print(f"[cx] 抓取失败: {e}", flush=True)
        browser.close()
    return items
