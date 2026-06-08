#!/bin/bash
# 清 __pycache__ + 重启 main.py (通过重启 keep_alive)
cd /home/ha/ddl-monitor
find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null
find . -name '*.pyc' -delete 2>/dev/null
echo "cache cleared"
ls -la __pycache__ 2>&1 | head -3
