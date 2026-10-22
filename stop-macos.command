#!/bin/bash
# 停止「EchoPaper」后端：结束 8300 端口进程 = 识别模型与全部内存立即释放
cd "$(dirname "$0")"
PIDS=$(lsof -ti tcp:8300 2>/dev/null)
if [ -z "$PIDS" ]; then
  echo "[INFO] The server is not running (nothing is listening on port 8300)."
else
  echo "$PIDS" | xargs kill
  echo "[OK] Stopped: $PIDS"
fi
