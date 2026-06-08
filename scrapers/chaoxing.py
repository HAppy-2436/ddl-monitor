"""学习通 DDL 抓取

支持 tab 参数: '作业' / '考试' / '任务'

流程:
1. playwright 打开 fycourse 课程列表, 抓所有 entercoursenewfy URL
2. 对每门课打开 entercoursenewfy, 点击指定 tab, 从生成的 iframe 拿 HTML
3. 解析未交/未完成项 + 剩余时间 -> 截止时间

输出格式 (对齐 v2):
[{
    'source': '学习通',
    'title': '[课程名] 作业标题',
    'deadline': '2026-06-15T23:59:00',
    'status': '未交',
    'url': 'https://i.mooc.chaoxing.com/space/index',
    'tab': '作业',
    'course': '课程名',
}, ...]
"""
import sys
import re
import datetime as dt
from pathlib import Path

# 让 scrapers/chaoxing.py 能 import 父目录的 config
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright
import config as app_config
import state_io

SOURCE_LABEL = '学习通'

CHAOXING_COOKIE = state_io.BASE_DIR / 'cookies' / 'chaoxing.json'
FY_COURSE_URL = 'https://fycourse.fanya.chaoxing.com/fyportal/courselist/course'
SPACE_URL = 'https://i.mooc.chaoxing.com/space/index'


def _parse_remaining(text: str, now: dt.datetime):
    """'剩余 X 天 Y 小时 Z 分钟' / '剩余 X 小时' / '剩余 X 分钟' / '剩余 X 天'"""
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


def _parse_list_html(html: str, course_name: str, tab: str, now: dt.datetime) -> list:
    """解析 work/list / exam / task iframe 出来的 <li>"""
    items = []
    for m in re.finditer(r'<li[^>]*>(.*?)</li>', html, re.S):
        content = m.group(1)
        if '剩余' not in content:
            continue
        title_m = re.search(r'class="overHidden2\s*fl"[^>]*>\s*([^<]+)', content)
        if not title_m:
            # 兼容其他 tab 的 title 选择器
            title_m = re.search(r'class="[^"]*title[^"]*"[^>]*>\s*([^<]+)', content, re.I)
        if not title_m:
            continue
        title = title_m.group(1).strip()

        status_m = re.search(r'class="status\s*fl"[^>]*>\s*([^<]+)', content)
        status = status_m.group(1).strip() if status_m else ''

        time_m = re.search(
            r'剩余\s*(\d+\s*天\s*\d+\s*小时\s*\d+\s*分钟|\d+\s*小时\s*\d+\s*分钟|\d+\s*分钟|\d+\s*天)',
            content
        )
        if not time_m:
            continue
        deadline = _parse_remaining(time_m.group(0), now)
        if deadline is None:
            continue

        items.append({
            'source': SOURCE_LABEL,
            'title': f'[{course_name}] {title}',
            'deadline': deadline.isoformat(),
            'status': status if status else '未知',
            'url': SPACE_URL,
            'tab': tab,
            'course': course_name,
        })
    return items


def fetch(tab: str = '作业') -> list:
    """抓取指定 tab 的 DDL

    Args:
        tab: '作业' / '考试' / '任务'

    Returns:
        DDL 列表, 失败返回 []
    """
    if not CHAOXING_COOKIE.exists():
        print(f"[chaoxing] 无 storage_state {CHAOXING_COOKIE}, 跳过 (需先跑 login_chaoxing_qr.py 登录)", flush=True)
        return []

    items = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                args=["--no-sandbox", "--single-process", "--disable-dev-shm-usage", "--disable-gpu"]
            )
            ctx = browser.new_context(storage_state=str(CHAOXING_COOKIE))
            page = ctx.new_page()
            try:
                page.goto(FY_COURSE_URL, wait_until='domcontentloaded', timeout=30000)
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
                print(f"[chaoxing] 找到 {len(courses)} 门课 (tab={tab})", flush=True)

                now = dt.datetime.now()
                for c in courses:
                    try:
                        page.goto(c['href'], wait_until='domcontentloaded', timeout=20000)
                        page.wait_for_timeout(2000)
                    except Exception as e:
                        print(f"[chaoxing] {c['name']}: 进入失败 {e}", flush=True)
                        continue
                    try:
                        # tab 选择器: "作业" / "考试" / "任务" 文本
                        page.locator(f'li:has-text("{tab}")').first.click(timeout=5000)
                        page.wait_for_timeout(4000)
                    except Exception as e:
                        print(f"[chaoxing] {c['name']}: 点{tab} tab 失败 {e}", flush=True)
                        continue
                    # 找 work/list / exam / task iframe
                    list_frame = None
                    for f in page.frames:
                        if any(kw in f.url for kw in ['work/list', 'exam', 'task', 'worklist']):
                            list_frame = f
                            break
                    if not list_frame:
                        print(f"[chaoxing] {c['name']}: 无 {tab} iframe", flush=True)
                        continue
                    try:
                        html = list_frame.content()
                    except Exception:
                        html = list_frame.evaluate('() => document.documentElement.outerHTML')
                    course_items = _parse_list_html(html, c['name'], tab, now)
                    if course_items:
                        print(f"[chaoxing]   {c['name'][:20]}: {len(course_items)} 条{tab}", flush=True)
                    items.extend(course_items)
            except Exception as e:
                print(f"[chaoxing] 抓取失败: {e}", flush=True)
            finally:
                browser.close()
    except Exception as e:
        print(f"[chaoxing] playwright 启动失败: {e}", flush=True)

    return items


if __name__ == "__main__":
    import sys
    tab = sys.argv[1] if len(sys.argv) > 1 else '作业'
    print(f"=== 抓取学习通 {tab} tab ===")
    items = fetch(tab)
    print(f"\n共 {len(items)} 条:")
    for it in items:
        print(f"  [{it['course']}] {it['title']} - {it['deadline']} (状态: {it['status']})")
