#!/bin/bash
# DDL 监控 - 主循环入口
# cron: * * * * * (每分钟)
set -e
cd /home/ha/ddl-monitor
source .venv/bin/activate
export PYTHONUNBUFFERED=1
exec python3 main.py
