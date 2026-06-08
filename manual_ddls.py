"""手动 DDL 增删查

存储: manual_ddls.json
DDL 唯一 id: 'manual:<title>'

操作:
- add(title, deadline, note='') -> {ok, ...}
- delete_by_title(keyword, strict=True) -> {ok, deleted: [titles]}
- list_all() -> [items] (按截止时间升序)
"""
import datetime as dt
from typing import List, Dict, Optional

import state_io
import date_parser
import schedule_calc


SOURCE = 'manual'


def _make_id(title: str) -> str:
    return f"{SOURCE}:{title}"


def add(title: str, deadline_str: str, note: str = '') -> Dict:
    """加一条手动 DDL

    Args:
        title: DDL 标题
        deadline_str: 截止时间字符串 (多格式支持)
        note: 备注 (可选)

    Returns:
        {'ok': True, 'title': ..., 'deadline': iso, 'schedule': [(dt, slot), ...]}
        或 {'ok': False, 'error': ...}
    """
    title = title.strip()
    if not title:
        return {'ok': False, 'error': '标题为空'}

    try:
        deadline = date_parser.parse_deadline(deadline_str)
    except ValueError as e:
        return {'ok': False, 'error': f'截止时间解析失败: {e}'}

    # 检查重复
    data = state_io.load_manual_ddls()
    ddl_id = _make_id(title)
    if ddl_id in data:
        return {'ok': False, 'error': f'已存在标题为 "{title}" 的 DDL'}

    # 写入
    data[ddl_id] = {
        'source': SOURCE,
        'title': title,
        'deadline': deadline.isoformat(),
        'url': '',
        'note': note,
        'status': '未完成',
        'added_at': dt.datetime.now().isoformat(),
    }
    state_io.save_manual_ddls(data)
    schedule = schedule_calc.compute_send_at(deadline)
    return {
        'ok': True,
        'title': title,
        'deadline': deadline.isoformat(),
        'schedule': schedule,
    }


def delete_by_title(title: str) -> Dict:
    """严格匹配标题删除 (del 指令)

    Args:
        title: 完整标题

    Returns:
        {'ok': True, 'deleted': [title, ...]}
        或 {'ok': False, 'keyword': title}
    """
    title = title.strip()
    data = state_io.load_manual_ddls()

    # 严格匹配: 必须在 manual 里完全等于 (且只在 manual 里删)
    deleted = []
    ddl_id = _make_id(title)
    if ddl_id in data:
        del data[ddl_id]
        deleted.append(title)

    if deleted:
        state_io.save_manual_ddls(data)
        return {'ok': True, 'deleted': deleted}

    return {'ok': False, 'keyword': title, 'error': '没找到完全匹配的标题'}


def delete_ddl_id(ddl_id: str) -> bool:
    """通过 ddl_id 删 (scrape 标记完成时用)"""
    data = state_io.load_manual_ddls()
    if ddl_id in data:
        del data[ddl_id]
        state_io.save_manual_ddls(data)
        return True
    return False


def list_all() -> List[Dict]:
    """列出所有手动 DDL, 按 deadline 升序"""
    data = state_io.load_manual_ddls()
    items = []
    for ddl_id, d in data.items():
        items.append({
            'id': ddl_id,
            'source': d.get('source', SOURCE),
            'title': d.get('title', ''),
            'deadline': d.get('deadline', ''),
            'url': d.get('url', ''),
            'note': d.get('note', ''),
            'status': d.get('status', ''),
        })
    # 排序
    def parse(it):
        try:
            return dt.datetime.fromisoformat(it['deadline'])
        except Exception:
            return dt.datetime.max
    return sorted(items, key=parse)


def parse_kv_body(body: str) -> Dict[str, str]:
    """解析 add 邮件的正文 'key: value' 格式"""
    out = {}
    for line in body.splitlines():
        line = line.strip()
        if not line or ':' not in line:
            continue
        k, v = line.split(':', 1)
        out[k.strip()] = v.strip()
    return out


# ===== 单元测试 =====
def _self_test():
    import tempfile
    import os

    # 用临时目录隔离 (不影响真实文件)
    tmpdir = tempfile.mkdtemp()
    os.chdir(tmpdir)
    # 重新指向 BASE_DIR
    import state_io as si
    si.BASE_DIR = __import__('pathlib').Path(tmpdir)
    si.DDL_LIST_FILE = si.BASE_DIR / 'ddl_list.json'
    si.MANUAL_DDLS_FILE = si.BASE_DIR / 'manual_ddls.json'
    si.SCHEDULE_FILE = si.BASE_DIR / 'schedule.json'
    si.SENT_LOG_FILE = si.BASE_DIR / 'sent_log.json'

    # 1. add
    result = add('测试DDL 1', '2026-06-15 14:00', '备注1')
    assert result['ok'], f"add 失败: {result}"
    assert result['title'] == '测试DDL 1'
    assert len(result['schedule']) > 0
    print(f"OK: add 成功, 生成 {len(result['schedule'])} 个 send_at")

    # 2. add 重复
    result = add('测试DDL 1', '2026-06-20 14:00')
    assert not result['ok']
    assert '已存在' in result['error']
    print("OK: add 重复检测")

    # 3. add 错误日期
    result = add('测试DDL 2', 'abc')
    assert not result['ok']
    assert '截止时间' in result['error']
    print("OK: add 错误日期")

    # 4. list
    items = list_all()
    assert len(items) == 1
    assert items[0]['title'] == '测试DDL 1'
    print(f"OK: list 1 项: {items[0]['title']}")

    # 5. delete
    result = delete_by_title('测试DDL 1')
    assert result['ok']
    assert result['deleted'] == ['测试DDL 1']
    print("OK: delete 成功")

    # 6. delete 找不到
    result = delete_by_title('不存在的')
    assert not result['ok']
    assert result['keyword'] == '不存在的'
    print("OK: delete 找不到")

    # 7. parse_kv_body
    body = """
标题: 数据结构期末
截止: 2026-06-15 14:00
备注: ACA 备考
"""
    parsed = parse_kv_body(body)
    assert parsed == {'标题': '数据结构期末', '截止': '2026-06-15 14:00', '备注': 'ACA 备考'}
    print(f"OK: parse_kv_body = {parsed}")

    print("\n=== manual_ddls 单元测试全部通过 ===")


if __name__ == "__main__":
    _self_test()
