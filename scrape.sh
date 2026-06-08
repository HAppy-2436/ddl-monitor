#!/bin/bash
# DDL 监控 - 全量抓取入口
# cron: 0 8 * * * (每天 8:00)
set -e
cd /home/ha/ddl-monitor
source .venv/bin/activate
export PYTHONUNBUFFERED=1
exec python3 scrape.py
