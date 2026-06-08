"""DDL 抓取 + 持久化 + schedule 重算

每天 cron 8:00 跑一次 (内部判断周一抓全, 其它天抓 daily):
- 学习通作业 tab (每天)
- 学习通考试 tab (周一)
- 学习通任务 tab (周一)
- 编程帮主页表 (每天)
- 编程帮班级详情 (每天, TODO)

流程:
1. 抓所有源
2. 过滤过期 DDL
3. 写 ddl_list.json (去重, 平台 DDL)
4. 重算 schedule.json (合并 manual_ddls)
5. 清空 sent_log.json 里过期 DDL 的已发记录
"""
import sys
import datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import state_io
import schedule_calc
import smtp_client
from scrapers import chaoxing, mynereus
import manual_ddls


SCRAPE_LOCK = state_io.BASE_DIR / '.scrape.lock'


def _send_alert_if_needed(old_count: int, new_count: int, source: str):
    """抓取数据异常时发警告邮件"""
    if new_count == 0 and old_count > 0:
        subject = f'[DDL·警告] {source} 抓取返回 0 条 (上次 {old_count} 条)'
        text = f'{source} 抓取突然返回 0 条, 可能是:\n1. 登录态过期 (重跑 login_*.py 重新登录)\n2. 页面结构变化 (scraper 需要更新)\n3. 网络问题\n\n建议: 立即检查, 否则今天没 DDL 提醒.'
        html = f'<p style="color: #e74c3c;"><b>⚠️ {source} 抓取异常</b></p><p>本次抓取 0 条, 上次 {old_count} 条。</p><p>可能是登录态过期 / 页面结构变化 / 网络问题。</p>'
        smtp_client.send_email(subject, html, text)
        print(f"[scrape] 发送警告邮件: {source} 0 条", flush=True)
    elif new_count < old_count * 0.5:
        subject = f'[DDL·警告] {source} 抓取数据大幅减少 ({old_count} -> {new_count})'
        text = f'{source} 抓取数据减少超 50%, 请检查是否漏抓.'
        html = f'<p style="color: #e67e22;">⚠️ {source} 抓取数据: {old_count} → {new_count} (减少 {100*(old_count-new_count)//old_count}%)</p>'
        smtp_client.send_email(subject, html, text)
        print(f"[scrape] 发送警告邮件: {source} 大幅减少", flush=True)


def _filter_expired(items: list, now: dt.datetime) -> list:
    """过期 DDL 直接忽略, 不进 schedule"""
    out = []
    for it in items:
        try:
            d = dt.datetime.fromisoformat(it['deadline'])
            if d < now:
                print(f"[scrape]   跳过(过期): {it.get('title', '?')} (deadline={it['deadline']})", flush=True)
                continue
        except Exception:
            pass
        out.append(it)
    return out


def _make_ddl_id(it: dict) -> str:
    """DDL 唯一 id: source:title"""
    return f"{it.get('source', '?')}:{it.get('title', '?')}"


def scrape_all(is_monday: bool = False) -> dict:
    """主入口: 全量抓取 + 重算 schedule

    Args:
        is_monday: True=周一, 抓所有 tab; False=其它天, 只抓作业/主页

    Returns:
        统计 dict
    """
    now = dt.datetime.now()
    print(f"[scrape] 开始抓取 @ {now.isoformat()} (周一: {is_monday})", flush=True)

    # 1. 抓数据
    all_items = []

    # 1a. 学习通 (根据 is_monday 决定抓哪些 tab)
    old_chaoxing_count = len([k for k in state_io.load_ddl_list() if k.startswith('学习通:')])
    cx_items = chaoxing.fetch('作业')
    if is_monday:
        cx_items.extend(chaoxing.fetch('考试'))
        cx_items.extend(chaoxing.fetch('任务'))
    all_items.extend(cx_items)
    _send_alert_if_needed(old_chaoxing_count, len(cx_items), '学习通')

    # 1b. 编程帮
    old_mynereus_count = len([k for k in state_io.load_ddl_list() if k.startswith('编程帮:')])
    myn_items = mynereus.fetch()
    all_items.extend(myn_items)
    _send_alert_if_needed(old_mynereus_count, len(myn_items), '编程帮')

    print(f"[scrape] 抓取共 {len(all_items)} 条", flush=True)

    # 2. 过滤过期
    all_items = _filter_expired(all_items, now)
    print(f"[scrape] 过滤后 {len(all_items)} 条 (过期已忽略)", flush=True)

    # 3. 写 ddl_list.json (去重, 同 id 后覆盖前)
    ddl_list = state_io.load_ddl_list()
    for it in all_items:
        ddl_id = _make_ddl_id(it)
        ddl_list[ddl_id] = {
            'source': it.get('source', '?'),
            'title': it.get('title', '?'),
            'deadline': it.get('deadline', ''),
            'url': it.get('url', ''),
            'status': it.get('status', ''),
            'scraped_at': now.isoformat(),
            # 额外字段
            **{k: v for k, v in it.items() if k not in ('source', 'title', 'deadline', 'url', 'status')},
        }
    state_io.save_ddl_list(ddl_list)
    print(f"[scrape] ddl_list.json 写入 {len(ddl_list)} 条", flush=True)

    # 4. 重算 schedule.json (合并平台 + 手动)
    schedule = {}
    for ddl_id, d in ddl_list.items():
        try:
            deadline = dt.datetime.fromisoformat(d['deadline'])
            schedule[ddl_id] = {
                'source': d.get('source', '?'),
                'title': d.get('title', '?'),
                'deadline': d.get('deadline', ''),
                'url': d.get('url', ''),
                'send_at': [(t.isoformat(), s) for t, s in schedule_calc.compute_send_at(deadline, now.date())],
            }
        except Exception as e:
            print(f"[scrape] 重算 schedule 失败: {ddl_id}: {e}", flush=True)
    # 合并 manual
    for ddl_id, d in manual_ddls.list_all_dict().items():
        try:
            deadline = dt.datetime.fromisoformat(d['deadline'])
            schedule[ddl_id] = {
                'source': d.get('source', '手动'),
                'title': d.get('title', '?'),
                'deadline': d.get('deadline', ''),
                'url': d.get('url', ''),
                'send_at': [(t.isoformat(), s) for t, s in schedule_calc.compute_send_at(deadline, now.date())],
            }
        except Exception as e:
            print(f"[scrape] 重算 manual schedule 失败: {ddl_id}: {e}", flush=True)

    state_io.save_schedule(schedule)
    print(f"[scrape] schedule.json 写入 {len(schedule)} 条", flush=True)

    # 5. 清空 sent_log 里过期 DDL 的记录
    sent_log = state_io.load_sent_log()
    valid_ids = set(schedule.keys())
    cleaned = {k: v for k, v in sent_log.items() if k in valid_ids}
    state_io.save_sent_log(cleaned)
    print(f"[scrape] sent_log 清理: {len(sent_log)} -> {len(cleaned)}", flush=True)

    return {
        'scraped': len(all_items),
        'platform_ddls': len(ddl_list),
        'manual_ddls': len(manual_ddls.list_all()),
        'schedule': len(schedule),
    }


def main():
    # 文件锁: 防止 main.py 同时跑
    try:
        with state_io.file_lock(SCRAPE_LOCK, exclusive=True, timeout=60):
            now = dt.datetime.now()
            is_monday = now.weekday() == 0
            result = scrape_all(is_monday=is_monday)
            print(f"[scrape] 完成: {result}", flush=True)
    except TimeoutError as e:
        print(f"[scrape] 文件锁超时: {e}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
