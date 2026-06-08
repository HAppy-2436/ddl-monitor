"""JSON 持久化 + 文件锁

4 个 JSON 文件:
- ddl_list.json    平台抓的 DDL (scrape 写)
- manual_ddls.json 手动加的 DDL (邮件写)
- schedule.json    send_at 列表 (scrape + 手动 add 时重算)
- sent_log.json    已发记录 (main 写, 去重用)

并发: scrape 和 main 不重叠 (cron 错峰 + fcntl 锁)
"""
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable
from contextlib import contextmanager

# fcntl 仅 Linux 可用, Windows 用 msvcrt 替代 (本项目服务器为 Linux, Windows 只是开发环境)
if sys.platform == 'win32':
    try:
        import msvcrt
        HAS_MSVCRT = True
    except ImportError:
        HAS_MSVCRT = False
    fcntl = None
else:
    import fcntl

BASE_DIR = Path(__file__).resolve().parent

# 文件路径
DDL_LIST_FILE = BASE_DIR / 'ddl_list.json'
MANUAL_DDLS_FILE = BASE_DIR / 'manual_ddls.json'
SCHEDULE_FILE = BASE_DIR / 'schedule.json'
SENT_LOG_FILE = BASE_DIR / 'sent_log.json'


@contextmanager
def file_lock(path: Path, exclusive: bool = True, timeout: int = 30):
    """文件锁

    - Linux: 用 fcntl.flock
    - Windows: 用 msvcrt.locking (本地开发, 单进程, 弱保证)

    Args:
        path: 锁文件路径 (实际用 path.lock)
        exclusive: True=排他写锁, False=共享读锁
        timeout: 等待超时秒数
    """
    lock_path = path.with_suffix(path.suffix + '.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch(exist_ok=True)

    if fcntl is not None:
        # Linux: fcntl.flock
        fd = os.open(str(lock_path), os.O_RDWR)
        try:
            op = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(fd, op | fcntl.LOCK_NB)
            yield
        except BlockingIOError:
            import time
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    fcntl.flock(fd, op)
                    break
                except BlockingIOError:
                    time.sleep(0.1)
            else:
                raise TimeoutError(f"无法获取文件锁: {lock_path}")
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except Exception:
                pass
            os.close(fd)
    elif HAS_MSVCRT:
        # Windows: msvcrt.locking (本地开发弱保证, 不支持非阻塞)
        with open(lock_path, 'r+') as f:
            # 锁 1 字节
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
            except OSError:
                raise TimeoutError(f"Windows 文件锁失败: {lock_path}")
            try:
                yield
            finally:
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                except Exception:
                    pass
    else:
        # 无锁 fallback (单进程测试场景)
        yield


def load_json(path: Path, default: Any = None) -> Any:
    """读 JSON, 不存在或损坏返回 default"""
    if default is None:
        default = {} if path.suffix == '.json' else []
    if not path.exists():
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[state_io] {path} 读取失败: {e}, 用默认值")
        return default


def save_json(path: Path, data: Any) -> None:
    """写 JSON (原子写: 写临时文件 + rename)"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_ddl_list() -> dict:
    """ddl_list.json: {ddl_id: {source, title, deadline, url, status, scraped_at}}"""
    return load_json(DDL_LIST_FILE, {})


def save_ddl_list(data: dict) -> None:
    save_json(DDL_LIST_FILE, data)


def load_manual_ddls() -> dict:
    """manual_ddls.json: {ddl_id: {title, deadline, note, added_at}}"""
    return load_json(MANUAL_DDLS_FILE, {})


def save_manual_ddls(data: dict) -> None:
    save_json(MANUAL_DDLS_FILE, data)


def load_schedule() -> dict:
    """schedule.json: {ddl_id: {source, title, deadline, url, send_at: [(iso, slot), ...]}}"""
    return load_json(SCHEDULE_FILE, {})


def save_schedule(data: dict) -> None:
    save_json(SCHEDULE_FILE, data)


def load_sent_log() -> dict:
    """sent_log.json: {ddl_id: {slot: [iso_ts, ...]}}"""
    return load_json(SENT_LOG_FILE, {})


def save_sent_log(data: dict) -> None:
    save_json(SENT_LOG_FILE, data)


def make_ddl_id(source: str, title: str) -> str:
    """DDL 唯一 ID: source:title"""
    return f"{source}:{title}"


if __name__ == "__main__":
    # 自测: 读写 + 文件锁
    import tempfile
    import multiprocessing
    import time as _t

    # 1. 读写
    test_file = BASE_DIR / '.test_state_io.json'
    save_json(test_file, {"a": 1, "b": [1, 2, 3]})
    assert load_json(test_file) == {"a": 1, "b": [1, 2, 3]}, "读写不一致"
    test_file.unlink()
    print("OK: JSON 读写")

    # 2. 损坏的 JSON
    bad = BASE_DIR / '.test_bad.json'
    bad.write_text("{not json", encoding='utf-8')
    assert load_json(bad) == {}, "损坏文件应返回 default"
    bad.unlink()
    print("OK: 损坏 JSON 用 default")

    # 3. 文件锁 (仅 Linux 测试)
    if sys.platform != 'win32':
        lock_path = BASE_DIR / '.test.lock'

        def worker(n):
            with file_lock(lock_path, exclusive=True, timeout=2):
                print(f"worker {n} 拿到锁")
                _t.sleep(0.5)

        procs = [multiprocessing.Process(target=worker, args=(i,)) for i in range(3)]
        for p in procs:
            p.start()
        for p in procs:
            p.join()
        lock_path.unlink(missing_ok=True)
        print("OK: 文件锁 (3 进程串行)")
    else:
        print("SKIP: Windows 跳过 fcntl 测试")

    print("\n=== state_io 自测全部通过 ===")
