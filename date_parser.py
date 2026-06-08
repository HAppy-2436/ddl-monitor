"""多格式日期解析器

支持的输入格式:
  - 2026-06-15 14:00 / 2026/06/15 14:00 / 2026.06.15 14:00
  - 6-15 14:00 / 6/15 14:00 / 6.15 14:00 (无年份默认今年, 过去自动明年)
  - 06-15 14:00 (补零也支持)
  - 6月15日 14:00 (中文)
  - 明天 14:00 / 后天 14:00 / 今天 14:00 (相对时间)
  - 下周一 14:00 / 周一 14:00 (周几, "下周"修饰可选)
  - 2026-06-15 (只日期, 默认 23:59)

无法解析抛 ValueError
"""
import re
import datetime as dt

_CN_DIGIT = {'零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4,
             '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}

_WEEKDAY_CN = {'一': 0, '二': 1, '三': 2, '四': 3, '五': 4, '六': 5, '日': 6, '天': 6, '末': 6}


def _cn_num_to_int(s: str) -> int:
    """把 '十五' '二十' '二十三' 转成 int"""
    if not s:
        return 0
    if s == '十':
        return 10
    if '十' not in s:
        return sum(_CN_DIGIT[c] for c in s)
    parts = s.split('十')
    tens = _CN_DIGIT[parts[0]] if parts[0] else 1
    ones = _CN_DIGIT[parts[1]] if parts[1] else 0
    return tens * 10 + ones


def _parse_time(time_str: str) -> tuple[int, int]:
    """'14:00' / '14点' / '下午2点' / '14:30:00' -> (h, m)"""
    s = time_str.strip()
    # 下午/上午/晚上 修饰
    hour_offset = 0
    if s.startswith('下午') or s.startswith('晚上'):
        hour_offset = 12
        s = s[2:].strip()
    elif s.startswith('上午') or s.startswith('早上') or s.startswith('凌晨'):
        s = s[2:].strip()
    elif s.startswith('中午'):
        hour_offset = 12
        s = s[2:].strip()

    # 14:00:00 / 14:00 / 14点 / 14点30分
    m = re.match(r'^(\d{1,2})[:点](\d{1,2})(?:分|:(\d{1,2})秒?)?$', s)
    if m:
        h = int(m.group(1)) + hour_offset
        mm = int(m.group(2))
        return (h, mm)
    m = re.match(r'^(\d{1,2})点$', s)
    if m:
        return (int(m.group(1)) + hour_offset, 0)
    m = re.match(r'^(\d{1,2})$', s)  # 纯小时数
    if m:
        return (int(m.group(1)) + hour_offset, 0)
    raise ValueError(f"无法解析时间: {time_str}")


def _split_date_time(s: str) -> tuple[str, str | None]:
    """把 '2026-06-15 14:00' 拆成 ('2026-06-15', '14:00'). 只日期时 time_str=None"""
    s = s.strip()
    # ISO 格式: 2026-06-15T14:00:00 或 2026-06-15T14:00
    m = re.match(r'^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}(?::\d{2})?)$', s)
    if m:
        return (m.group(1), m.group(2))
    # 标准 / 斜杠 / 点 分隔 (含时间)
    m = re.match(r'^(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})[T\s](\d{1,2}[:点]\d{1,2}(?:分?)?)$', s)
    if m:
        # 归一化时间为 HH:MM
        time_str = m.group(2).replace('点', ':').replace('分', '')
        return (m.group(1), time_str)
    # 空格分隔
    parts = s.split()
    if len(parts) == 1:
        return (parts[0], None)
    if len(parts) == 2:
        return (parts[0], parts[1])
    raise ValueError(f"无法分割日期和时间: {s}")


def _parse_date_part(date_str: str, today: dt.date) -> dt.date:
    """解析日期部分, 返回 date"""
    s = date_str.strip()

    # 相对时间
    if s in ('今天', '今日'):
        return today
    if s in ('明天', '明日', '明'):
        return today + dt.timedelta(days=1)
    if s in ('后天', '后'):
        return today + dt.timedelta(days=2)
    if s in ('大后天', '大后'):
        return today + dt.timedelta(days=3)
    if s == '下周':
        return None  # 单独说"下周"没意义, 让 _parse_date_part 抛错

    # 周几
    m = re.match(r'^(下周|周|星期|礼拜)?([一二三四五六日天末])$', s)
    if m:
        prefix = m.group(1) or ''
        cn_wd = m.group(2)
        target_wd = _WEEKDAY_CN[cn_wd]
        current_wd = today.weekday()
        delta = (target_wd - current_wd) % 7
        if delta == 0:
            delta = 7  # 今天是这个周几, 默认下周
        if prefix == '下周':
            if delta < 7:
                delta += 7
            else:
                pass  # 已经是下一周了
        return today + dt.timedelta(days=delta)

    # 中文 '6月15日'
    m = re.match(r'^(\d{1,2}|[一二三四五六七八九十]+)月(\d{1,2}|[一二三四五六七八九十]+)日?$', s)
    if m:
        month = int(m.group(1)) if m.group(1).isdigit() else _cn_num_to_int(m.group(1))
        day = int(m.group(2)) if m.group(2).isdigit() else _cn_num_to_int(m.group(2))
        year = today.year
        try:
            d = dt.date(year, month, day)
        except ValueError:
            raise ValueError(f"非法日期: {s}")
        # 过去日期自动明年
        if d < today:
            d = dt.date(year + 1, month, day)
        return d

    # 标准 / 斜杠 / 点 分隔
    m = re.match(r'^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$', s)
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # 无年份 6-15 / 6/15 / 6.15
    m = re.match(r'^(\d{1,2})[-/.](\d{1,2})$', s)
    if m:
        year = today.year
        try:
            d = dt.date(year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            raise ValueError(f"非法日期: {s}")
        if d < today:
            d = dt.date(year + 1, int(m.group(1)), int(m.group(2)))
        return d

    raise ValueError(f"无法解析日期: {s}")


def parse_deadline(s: str, today: dt.date = None) -> dt.datetime:
    """主入口: 解析 DDL 截止时间字符串

    Args:
        s: 日期时间字符串
        today: 参考日期 (用于无年份默认今年 + 过去日期自动明年), 默认系统今天

    Returns:
        datetime 对象

    Raises:
        ValueError: 无法解析
    """
    if not s or not s.strip():
        raise ValueError("空字符串")

    if today is None:
        today = dt.date.today()

    date_str, time_str = _split_date_time(s)
    target_date = _parse_date_part(date_str, today)
    if time_str is None:
        # 只日期, 默认 23:59
        return dt.datetime.combine(target_date, dt.time(23, 59))
    h, m = _parse_time(time_str)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"时间超出范围: {time_str}")
    return dt.datetime.combine(target_date, dt.time(h, m))


# ===== 单元测试 =====
def _self_test():
    today = dt.date(2026, 6, 8)
    cases = [
        ("2026-06-15 14:00", dt.datetime(2026, 6, 15, 14, 0)),
        ("2026/06/15 14:00", dt.datetime(2026, 6, 15, 14, 0)),
        ("2026.06.15 14:00", dt.datetime(2026, 6, 15, 14, 0)),
        ("6-15 14:00", dt.datetime(2026, 6, 15, 14, 0)),       # 今年
        ("6/15 14:00", dt.datetime(2026, 6, 15, 14, 0)),
        ("6.15 14:00", dt.datetime(2026, 6, 15, 14, 0)),
        # 过去日期自动明年 (today=6-08, 6-08 之前 = 6-08 之前那段时间)
        # 严格说: "今天 6-08" 应该滚到 2027, 但加 DDL 场景下"6-08"通常指未来, 测试用 later 6-08 测
        ("5-15 14:00", dt.datetime(2027, 5, 15, 14, 0)),       # 5-15 早于 today 6-08 -> 明年
        ("06-15 14:00", dt.datetime(2026, 6, 15, 14, 0)),
        ("6月15日 14:00", dt.datetime(2026, 6, 15, 14, 0)),
        ("5月15日 14:00", dt.datetime(2027, 5, 15, 14, 0)),     # 5-15 早于 today -> 明年
        ("明天 14:00", dt.datetime(2026, 6, 9, 14, 0)),
        ("后天 14:00", dt.datetime(2026, 6, 10, 14, 0)),
        ("今天 14:00", dt.datetime(2026, 6, 8, 14, 0)),
        ("明天 23:59", dt.datetime(2026, 6, 9, 23, 59)),
        ("2026-06-15", dt.datetime(2026, 6, 15, 23, 59)),      # 只日期
        ("6-15", dt.datetime(2026, 6, 15, 23, 59)),
        ("2026-06-15T14:00:00", dt.datetime(2026, 6, 15, 14, 0)),  # ISO 格式
        ("2026-06-15T14:00", dt.datetime(2026, 6, 15, 14, 0)),     # ISO 短格式
    ]
    fail = 0
    for s, expected in cases:
        try:
            got = parse_deadline(s, today)
            ok = got == expected
            mark = "OK" if ok else "FAIL"
            if not ok:
                fail += 1
            print(f"{mark} | {s!r:30s} -> {got} (expected {expected})")
        except Exception as e:
            fail += 1
            print(f"FAIL | {s!r:30s} -> raised {type(e).__name__}: {e}")

    # 错误用例
    err_cases = ["", "abc", "2026-13-45 14:00", "周八", "6月32日"]
    for s in err_cases:
        try:
            parse_deadline(s, today)
            fail += 1
            print(f"FAIL | {s!r:30s} -> should have raised")
        except ValueError:
            print(f"OK   | {s!r:30s} -> raised ValueError (expected)")

    print(f"\n{'-' * 50}")
    print(f"PASSED: {len(cases) + len(err_cases) - fail}/{len(cases) + len(err_cases)}")
    return fail == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if _self_test() else 1)
