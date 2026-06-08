"""5 档邮件渲染 (HTML + text)

档位 -> 主题前缀:
- daily         -> [DDL·汇总]  YYYY-MM-DD N 项 DDL
- tomorrow      -> [DDL·明日]  N 项 DDL 36h 内截止
- one_week      -> [DDL·一周]  N 项 DDL 一周内截止
- today         -> [DDL·今日]  N 项 DDL 6h 内截止
- urgent        -> [DDL·紧急]  <标题> 30 分钟后截止
- urgent_backup -> [DDL·紧急]  <标题> 4 分钟后截止 (兜底)
- reply         -> [DDL·回复]  ...

所有汇总邮件按 DDL 截止时间升序 (近->远) 排序。
"""
import datetime as dt
from typing import List, Dict, Tuple


SLOT_LABELS = {
    'daily': '汇总',
    'tomorrow': '明日',
    'one_week': '一周',
    'today': '今日',
    'urgent': '紧急',
    'urgent_backup': '紧急',
    'reply': '回复',
}


def _format_time_left(deadline: dt.datetime, now: dt.datetime) -> str:
    """算剩余时间, 返回 'X 天 Y 小时' / 'Y 小时' / 'Z 分钟'"""
    delta = deadline - now
    secs = int(delta.total_seconds())
    if secs < 0:
        return '已过期'
    if secs < 3600:
        return f'{secs // 60} 分钟'
    if secs < 86400:
        h = secs // 3600
        m = (secs % 3600) // 60
        return f'{h} 小时 {m} 分钟' if m else f'{h} 小时'
    d = secs // 86400
    h = (secs % 86400) // 3600
    return f'{d} 天 {h} 小时' if h else f'{d} 天'


def _format_deadline_str(deadline_str: str) -> str:
    """把 ISO 字符串格式化为 'MM-DD HH:MM'"""
    try:
        d = dt.datetime.fromisoformat(deadline_str)
        return d.strftime('%m-%d %H:%M')
    except Exception:
        return deadline_str


def sort_by_deadline(items: List[Dict]) -> List[Dict]:
    """按 deadline 升序 (近->远)"""
    def parse(it):
        try:
            return dt.datetime.fromisoformat(it['deadline'])
        except Exception:
            return dt.datetime.max
    return sorted(items, key=parse)


# ===== HTML 渲染 =====
HTML_STYLE = """
<style>
  body { font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; padding: 16px; color: #333; }
  .ddl-item { padding: 10px 12px; border-left: 3px solid #4a90e2; background: #f8f9fa; margin: 6px 0; border-radius: 4px; }
  .ddl-title { font-size: 15px; font-weight: 600; color: #222; }
  .ddl-meta { font-size: 13px; color: #666; margin-top: 4px; }
  .ddl-source { display: inline-block; background: #4a90e2; color: white; padding: 1px 8px; border-radius: 3px; font-size: 12px; margin-right: 8px; }
  .ddl-urgent { border-left-color: #e74c3c; background: #fff5f5; }
  .ddl-urgent .ddl-source { background: #e74c3c; }
  .ddl-expired { opacity: 0.5; text-decoration: line-through; }
  .footer { font-size: 12px; color: #999; margin-top: 16px; padding-top: 8px; border-top: 1px solid #eee; }
  .note { color: #999; font-size: 12px; }
  .reply-info { background: #f0f8ff; padding: 10px; border-radius: 4px; margin: 8px 0; font-size: 13px; }
</style>
"""


def render_summary(items: List[Dict], slot: str, now: dt.datetime = None) -> Tuple[str, str, str]:
    """渲染汇总类邮件 (daily/tomorrow/one_week/today)

    Args:
        items: DDL 列表 (每项含 source/title/deadline/url/status/note)
        slot: 'daily' / 'tomorrow' / 'one_week' / 'today'
        now: 当前时间

    Returns:
        (subject, html, text)
    """
    if now is None:
        now = dt.datetime.now()
    items = sort_by_deadline(items)
    label = SLOT_LABELS[slot]
    n = len(items)

    slot_titles = {
        'daily': f'{now.strftime("%Y-%m-%d")} 汇总 {n} 项 DDL',
        'tomorrow': f'{n} 项 DDL 36h 内截止',
        'one_week': f'{n} 项 DDL 一周内截止',
        'today': f'{n} 项 DDL 6h 内截止',
    }
    subject = f'[DDL·{label}] {slot_titles[slot]}'

    # 文本版
    text_lines = [f'你有 {n} 项 DDL:', '']
    for it in items:
        d = _format_deadline_str(it['deadline'])
        src = it.get('source', '?')
        title = it.get('title', '?')
        left = _format_time_left(dt.datetime.fromisoformat(it['deadline']), now)
        note = f' ({it["note"]})' if it.get('note') else ''
        text_lines.append(f'  [{src}] {title}{note}')
        text_lines.append(f'    截止 {d}  剩余 {left}')
    text_lines.append('')
    text_lines.append('发件: DDL 监控 (Gmail → QQ 邮箱)')
    text = '\n'.join(text_lines)

    # HTML 版
    html_items = []
    for it in items:
        d = _format_deadline_str(it['deadline'])
        src = it.get('source', '?')
        title = it.get('title', '?')
        left = _format_time_left(dt.datetime.fromisoformat(it['deadline']), now)
        urgent_cls = ' ddl-urgent' if it.get('urgent') else ''
        note_html = f' <span class="note">({it["note"]})</span>' if it.get('note') else ''
        url = it.get('url', '')
        title_html = f'<a href="{url}" style="color: #4a90e2; text-decoration: none;">{title}</a>' if url else title
        html_items.append(
            f'<div class="ddl-item{urgent_cls}">'
            f'<div class="ddl-title"><span class="ddl-source">{src}</span>{title_html}{note_html}</div>'
            f'<div class="ddl-meta">截止 {d} · 剩余 {left}</div>'
            f'</div>'
        )

    intro_map = {
        'daily': f'<p>今天是 <b>{now.strftime("%Y-%m-%d")}</b>, 你共有 <b>{n}</b> 项 DDL 待办:</p>',
        'tomorrow': f'<p>未来 <b>36 小时</b>内截止的 DDL 共 <b>{n}</b> 项:</p>',
        'one_week': f'<p>未来 <b>一周</b>(154-178 小时)内截止的 DDL 共 <b>{n}</b> 项, 进入最后冲刺:</p>',
        'today': f'<p>未来 <b>6 小时</b>内截止的 DDL 共 <b>{n}</b> 项:</p>',
    }

    html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8">{HTML_STYLE}</head>
<body>
{intro_map[slot]}
{''.join(html_items)}
<div class="footer">DDL 监控 · Gmail 发出 · 自动归档到 QQ 邮箱 DDL 文件夹</div>
</body></html>'''

    return subject, html, text


def render_urgent(item: Dict, now: dt.datetime = None, backup: bool = False) -> Tuple[str, str, str]:
    """渲染紧急档邮件 (单条 DDL)

    Args:
        item: {source, title, deadline, url, note}
        now: 当前时间
        backup: True=兜底档 (4 分钟), False=正常档 (30 分钟)

    Returns:
        (subject, html, text)
    """
    if now is None:
        now = dt.datetime.now()
    deadline = dt.datetime.fromisoformat(item['deadline'])
    minutes_left = max(0, int((deadline - now).total_seconds() / 60))
    src = item.get('source', '?')
    title = item.get('title', '?')
    d = _format_deadline_str(item['deadline'])
    note = f' ({item["note"]})' if item.get('note') else ''

    if backup:
        subject = f'[DDL·紧急] {title} {minutes_left} 分钟后截止 (兜底提醒)'
        intro = f'⚠️ <b>兜底提醒</b>: 该 DDL 还有 <b>{minutes_left}</b> 分钟截止, 别忘了!'
    else:
        subject = f'[DDL·紧急] {title} {minutes_left} 分钟后截止'
        intro = f'⚠️ <b>紧急提醒</b>: 该 DDL 还有 <b>{minutes_left}</b> 分钟截止!'

    text = f'[{src}] {title}{note}\n截止 {d}  剩余 {minutes_left} 分钟\n'
    if item.get('url'):
        text += f'链接: {item["url"]}\n'

    note_html = f' <span class="note">({item["note"]})</span>' if item.get('note') else ''
    url_html = f'<p>链接: <a href="{item["url"]}">{item["url"]}</a></p>' if item.get('url') else ''

    html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8">{HTML_STYLE}</head>
<body>
<div class="ddl-item ddl-urgent">
  <div class="ddl-title"><span class="ddl-source">{src}</span>{title}{note_html}</div>
  <div class="ddl-meta">截止 {d} · 剩余 {minutes_left} 分钟</div>
</div>
<p>{intro}</p>
{url_html}
</body></html>'''

    return subject, html, text


def render_reply(action: str, result: dict, now: dt.datetime = None) -> Tuple[str, str, str]:
    """渲染指令回复邮件

    Args:
        action: 'add' / 'del' / 'list'
        result: 操作结果
        now: 当前时间

    Returns:
        (subject, html, text)
    """
    if now is None:
        now = dt.datetime.now()

    if action == 'add':
        if result.get('ok'):
            title = result.get('title', '?')
            deadline = result.get('deadline', '?')
            schedule = result.get('schedule', [])
            subject = f'[DDL·回复] 已添加 1 项 DDL'
            text_lines = [f'已添加 DDL: {title}', f'截止: {deadline}', '', '下次提醒:']
            html_items = [f'<li>{_format_send_at_line(sa)}</li>' for sa in schedule]
            for sa in schedule:
                text_lines.append(f'  - {_format_send_at_line(sa)}')
            text = '\n'.join(text_lines)
            html = f'''<p>已添加 DDL: <b>{title}</b></p>
<p>截止: <b>{deadline}</b></p>
<p>下次提醒:</p>
<ul>{''.join(html_items)}</ul>
<div class="reply-info">提示: 主题发 <code>del &lt;完整标题&gt;</code> 可删除/标记完成</div>'''
        else:
            subject = f'[DDL·回复] 添加失败'
            err = result.get('error', '未知错误')
            text = f'添加 DDL 失败: {err}'
            html = f'<p style="color: #e74c3c;">添加失败: {err}</p>'

    elif action == 'del':
        if result.get('ok'):
            deleted = result.get('deleted', [])
            subject = f'[DDL·回复] 已删除 {len(deleted)} 项 DDL'
            text_lines = [f'已删除 {len(deleted)} 项:']
            for d in deleted:
                text_lines.append(f'  - {d}')
            text = '\n'.join(text_lines)
            html_items = ''.join(f'<li>{d}</li>' for d in deleted)
            html = f'<p>已删除 <b>{len(deleted)}</b> 项 DDL:</p><ul>{html_items}</ul>'
        else:
            keyword = result.get('keyword', '?')
            subject = f'[DDL·回复] 没找到匹配 "{keyword}" 的 DDL'
            text = f'没找到标题完全匹配 "{keyword}" 的 DDL。\n请检查标题是否一致 (包括标点/空格)。'
            html = f'<p>没找到标题完全匹配 "<b>{keyword}</b>" 的 DDL。</p><p class="note">主题发 <code>list</code> 可查看所有 DDL 列表</p>'

    elif action == 'list':
        items = result.get('items', [])
        subject = f'[DDL·回复] 当前 {len(items)} 项 DDL'
        if not items:
            text = '当前没有 DDL。'
            html = '<p>当前没有 DDL。</p>'
        else:
            text_lines = []
            html_items = []
            for it in items:
                d = _format_deadline_str(it['deadline'])
                left = _format_time_left(dt.datetime.fromisoformat(it['deadline']), now)
                text_lines.append(f'[{it.get("source", "?")}] {it["title"]} - {d} (剩 {left})')
                note_html = f' <span class="note">({it["note"]})</span>' if it.get('note') else ''
                html_items.append(
                    f'<div class="ddl-item">'
                    f'<div class="ddl-title"><span class="ddl-source">{it.get("source", "?")}</span>{it["title"]}{note_html}</div>'
                    f'<div class="ddl-meta">截止 {d} · 剩余 {left}</div>'
                    f'</div>'
                )
            text = '\n'.join(text_lines)
            html = f'<p>当前 <b>{len(items)}</b> 项 DDL (按截止时间升序):</p>{"".join(html_items)}'
    else:
        subject = '[DDL·回复] 未知指令'
        text = f'未知指令: {action}'
        html = f'<p>未知指令: {action}</p>'

    return subject, html, text


def _format_send_at_line(sa: Tuple[dt.datetime, str]) -> str:
    """格式化一个 (datetime, slot) -> '06-15 09:00 [每日汇总]'"""
    t, slot = sa
    label = SLOT_LABELS.get(slot, slot)
    return f'{t.strftime("%m-%d %H:%M")} [{label}]'


# ===== 单元测试 =====
def _self_test():
    now = dt.datetime(2026, 6, 8, 11, 30)
    items = [
        {
            'source': '学习通',
            'title': '数据结构期末大作业',
            'deadline': '2026-06-15T23:59:00',
            'url': 'https://example.com',
            'status': '未交',
        },
        {
            'source': '编程帮',
            'title': 'Lab14',
            'deadline': '2026-06-08T12:00:00',  # 30 分钟后 (相对 now=11:30)
            'url': '',
            'status': '未完成',
        },
        {
            'source': '手动',
            'title': '阿里云ACA',
            'deadline': '2026-06-10T14:00:00',
            'url': '',
            'note': 'ACA 考试',
        },
    ]
    # 排序验证
    sorted_items = sort_by_deadline(items)
    assert sorted_items[0]['source'] == '编程帮'  # 6-8 12:00
    assert sorted_items[1]['source'] == '手动'  # 6-10 14:00
    assert sorted_items[2]['source'] == '学习通'  # 6-15 23:59
    print("OK: 排序近->远")

    # 渲染 daily
    subject, html, text = render_summary(items, 'daily', now)
    assert subject == '[DDL·汇总] 2026-06-08 汇总 3 项 DDL'
    assert '数据结构期末大作业' in text
    assert '阿里云ACA' in text
    assert 'Lab14' in text
    print(f"OK: daily subject = {subject}")

    # 渲染 tomorrow
    subject, html, text = render_summary(items, 'tomorrow', now)
    assert '明日' in subject
    print(f"OK: tomorrow subject = {subject}")

    # 渲染 urgent
    urgent_item = items[1]  # Lab14, 30 分钟后
    subject, html, text = render_urgent(urgent_item, now, backup=False)
    assert '[DDL·紧急]' in subject
    assert 'Lab14' in subject
    print(f"OK: urgent subject = {subject}")
    print(f"  text 片段: {text[:80]}")

    # 渲染 urgent 兜底
    subject, html, text = render_urgent(urgent_item, now, backup=True)
    assert '兜底' in subject
    print(f"OK: urgent_backup subject = {subject}")

    # 渲染 add 成功
    add_result = {
        'ok': True,
        'title': '测试DDL',
        'deadline': '2026-06-15 14:00',
        'schedule': [
            (dt.datetime(2026, 6, 14, 12, 0), 'tomorrow'),
            (dt.datetime(2026, 6, 15, 13, 30), 'urgent'),
        ],
    }
    subject, html, text = render_reply('add', add_result, now)
    assert '已添加' in subject
    assert '测试DDL' in text
    print(f"OK: add reply subject = {subject}")

    # 渲染 del 找不到
    del_result = {'ok': False, 'keyword': '不存在的DDL'}
    subject, html, text = render_reply('del', del_result, now)
    assert '没找到' in subject
    print(f"OK: del not-found subject = {subject}")

    # 渲染 list
    list_result = {'items': items}
    subject, html, text = render_reply('list', list_result, now)
    assert '当前 3 项' in subject
    print(f"OK: list subject = {subject}")

    print("\n=== email_render 单元测试全部通过 ===")


if __name__ == "__main__":
    _self_test()
