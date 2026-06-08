#!/usr/bin/env python3
"""keep_alive.py - 进程保活 + 定期重启

监督一个长跑命令, 出问题自动重启, 跑满时长主动重启.
自身低占用: 用 /proc 不用 psutil, 检查间隔 30s.

环境变量配置 (都可选):
  TARGET_CMD           要监督的命令 (默认 /home/ha/ddl-monitor/run.sh)
  MAX_RUNTIME_HOURS    跑满几小时主动重启 (默认 6)
  CHECK_INTERVAL_SEC   检查间隔秒 (默认 30)
  RESTART_DELAY_SEC    崩溃后等多久重启 (默认 5)
  MAX_FAILURES         连续失败几次停止监督 (默认 5)
  WATCHDOG_LOG         watchdog 日志路径 (默认 ~/ddl-monitor/logs/keep_alive.log)
  WATCHDOG_PIDFILE     watchdog pid 文件 (默认 ~/ddl-monitor/.keep_alive.pid)
  CHILD_NAME           在 ps 中用来找被监督进程名的关键字 (默认 run.sh)

用法:
  nohup python3 keep_alive.py >> /dev/null 2>&1 &
  pkill -TERM -f keep_alive.py    # 优雅退出
"""
import os
import sys
import time
import signal
import subprocess
from pathlib import Path

# 配置 (从环境变量读)
BASE_DIR = Path(__file__).resolve().parent
TARGET_CMD = os.environ.get('TARGET_CMD', str(BASE_DIR / 'run.sh'))
MAX_RUNTIME_HOURS = float(os.environ.get('MAX_RUNTIME_HOURS', '6'))
CHECK_INTERVAL_SEC = int(os.environ.get('CHECK_INTERVAL_SEC', '30'))
RESTART_DELAY_SEC = int(os.environ.get('RESTART_DELAY_SEC', '5'))
MAX_FAILURES = int(os.environ.get('MAX_FAILURES', '5'))
WATCHDOG_LOG = os.environ.get('WATCHDOG_LOG', str(BASE_DIR / 'logs' / 'keep_alive.log'))
WATCHDOG_PIDFILE = os.environ.get('WATCHDOG_PIDFILE', str(BASE_DIR / '.keep_alive.pid'))
CHILD_NAME = os.environ.get('CHILD_NAME', 'run.sh')

# 状态
keep_running = True
child_proc = None
child_started_at = None
consecutive_failures = 0
last_restart_reason = None
# 已知的 child 进程组: 启动 child 时记录, 避免 check_other_processes 把自家 child 误杀
known_child_pgids: set[int] = set()


def log_msg(msg: str):
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        Path(WATCHDOG_LOG).parent.mkdir(parents=True, exist_ok=True)
        with open(WATCHDOG_LOG, 'a') as f:
            f.write(line + '\n')
    except Exception:
        pass


def read_proc_rss_kb(pid: int) -> int | None:
    """读 /proc/<pid>/stat 拿 RSS (KB)。进程死了返回 None"""
    try:
        with open(f'/proc/{pid}/stat', 'r') as f:
            data = f.read().split()
        return int(data[23]) * 4  # RSS in pages * 4KB
    except (FileNotFoundError, IndexError, ValueError, PermissionError):
        return None


def kill_proc_tree(proc: subprocess.Popen, grace_sec: int = 10):
    """先 SIGTERM 整个进程组, 等 grace_sec, 还没死就 SIGKILL"""
    if proc.poll() is not None:
        return
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.wait(timeout=grace_sec)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    # child 死了, 从白名单移除
    try:
        pgid = os.getpgid(proc.pid)
        known_child_pgids.discard(pgid)
    except (ProcessLookupError, OSError):
        pass


def start_child():
    global known_child_pgids
    # 清空旧的白名单 (上一次启的 child 已死)
    known_child_pgids.clear()
    log_msg(f"启动: {TARGET_CMD}")
    # 用 shell=True 跑 (支持 run.sh 形式)
    # stdout/stderr 重定向到子日志 (跟 watchdog 日志分开)
    child_log = Path(WATCHDOG_LOG).with_name('child.log')
    log_f = open(child_log, 'a')
    proc = subprocess.Popen(
        TARGET_CMD,
        shell=True,
        stdout=log_f,
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,  # 独立进程组, 方便 killpg
    )
    # 记录 child 的进程组, 后续 check_other_processes 跳过
    try:
        pgid = os.getpgid(proc.pid)
        known_child_pgids.add(pgid)
        log_msg(f"  child pid={proc.pid} pgid={pgid}")
    except Exception as e:
        log_msg(f"  取 pgid 失败: {e}")
    return proc


def handle_signal(sig, frame):
    global keep_running
    log_msg(f"收到信号 {sig}, 准备平滑退出")
    keep_running = False


def check_other_processes():
    """扫描 ps, 找带 CHILD_NAME 但不在 known_child_pgids 里的进程 (孤儿), 杀掉它们
    注意: 自身刚启的 child 用 setsid 独立进程组, 进程组跟 keep_alive 不同, 所以要靠 known_child_pgids 白名单"""
    try:
        out = subprocess.run(['pgrep', '-af', CHILD_NAME], capture_output=True, text=True, timeout=5)
        my_pid = os.getpid()
        for line in out.stdout.strip().split('\n'):
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                pid = int(parts[0])
            except ValueError:
                continue
            if pid == my_pid:
                continue
            if 'keep_alive' in line:
                continue
            try:
                pgid = os.getpgid(pid)
            except (ProcessLookupError, PermissionError, OSError):
                continue
            # 白名单: 在 known_child_pgids 里的进程组是自家 child, 不动
            if pgid in known_child_pgids:
                continue
            # 剩下的当孤儿, 杀
            log_msg(f"清理孤儿: {line}")
            try:
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


def main():
    global child_proc, child_started_at, consecutive_failures, last_restart_reason

    # 写 PID 文件, 防多实例
    pidfile = Path(WATCHDOG_PIDFILE)
    if pidfile.exists():
        try:
            old_pid = int(pidfile.read_text().strip())
            if old_pid and old_pid != os.getpid():
                # 看老进程是否还活着
                try:
                    os.kill(old_pid, 0)
                    print(f"[FATAL] 已有 keep_alive 实例在跑 (PID {old_pid}), 退出", flush=True)
                    sys.exit(1)
                except (ProcessLookupError, PermissionError):
                    pass  # 老进程死了, 可以接管
        except (ValueError, OSError):
            pass
    pidfile.write_text(str(os.getpid()))
    # 退出时清理 PID 文件
    import atexit
    atexit.register(lambda: pidfile.unlink(missing_ok=True))

    # 注册信号
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    log_msg(f"=== keep_alive 启动 ===")
    log_msg(f"TARGET_CMD={TARGET_CMD}")
    log_msg(f"MAX_RUNTIME_HOURS={MAX_RUNTIME_HOURS}  CHECK_INTERVAL_SEC={CHECK_INTERVAL_SEC}")
    log_msg(f"RESTART_DELAY_SEC={RESTART_DELAY_SEC}  MAX_FAILURES={MAX_FAILURES}")

    while keep_running:
        # 启动/重启判断
        need_restart = False
        if child_proc is None:
            need_restart = True
            reason = last_restart_reason or "初次启动"
        elif child_proc.poll() is not None:
            exit_code = child_proc.returncode
            log_msg(f"子进程退出: code={exit_code}")
            consecutive_failures += 1
            if consecutive_failures >= MAX_FAILURES:
                log_msg(f"连续失败 {consecutive_failures} 次, 停止监督, 等用户介入")
                break
            need_restart = True
            reason = f"崩溃 (exit={exit_code}, 连续{consecutive_failures}次)"

        if need_restart:
            try:
                child_proc = start_child()
                child_started_at = time.time()
                consecutive_failures = 0
                last_restart_reason = None
            except Exception as e:
                log_msg(f"启动失败: {e}")
                time.sleep(RESTART_DELAY_SEC * 3)
                continue

        # 检查运行时间
        elapsed = time.time() - (child_started_at or time.time())
        if elapsed > MAX_RUNTIME_HOURS * 3600:
            rss = read_proc_rss_kb(child_proc.pid) if child_proc else 0
            log_msg(f"子进程跑满 {MAX_RUNTIME_HOURS}h (RSS={rss}KB), 主动重启")
            kill_proc_tree(child_proc, grace_sec=10)
            child_proc = None
            last_restart_reason = f"定期重启 (跑满 {MAX_RUNTIME_HOURS}h)"
            time.sleep(1)
            continue

        # 定期清理孤儿 (跟当前 child 冲突的旧 run.sh)
        check_other_processes()

        # sleep (分片, 接收信号能更快响应)
        for _ in range(CHECK_INTERVAL_SEC):
            if not keep_running:
                break
            time.sleep(1)

    # 平滑退出
    log_msg("=== keep_alive 退出中 ===")
    if child_proc and child_proc.poll() is None:
        log_msg("kill 子进程")
        kill_proc_tree(child_proc, grace_sec=10)
    try:
        Path(WATCHDOG_PIDFILE).unlink(missing_ok=True)
    except Exception:
        pass
    log_msg("=== keep_alive 已退出 ===")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log_msg(f"FATAL: {e}")
        sys.exit(1)
