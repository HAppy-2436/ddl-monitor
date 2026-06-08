#!/bin/bash
# ddl-monitor 入口脚本
# 默认 LONG_RUNNING=1 (keep_alive 监督模式), 设 0 = 单次跑 (cron 模式)
set -e
cd /home/ha/ddl-monitor
source .venv/bin/activate
export PYTHONUNBUFFERED=1  # 不缓冲, 立刻看到输出
LOG=/home/ha/ddl-monitor/logs/cron.log
echo "===== run at $(date '+%Y-%m-%d %H:%M:%S %Z') =====" >> $LOG
if [ "${LONG_RUNNING:-1}" = "1" ]; then
    LONG_RUNNING=1 python3 -u main.py >> $LOG 2>&1
else
    python3 -u main.py >> $LOG 2>&1
fi
RC=$?
echo "===== exit $RC =====" >> $LOG
exit $RC
