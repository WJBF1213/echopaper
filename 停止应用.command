#!/bin/bash
# 停止「雅思听力挖空练习」后端：结束 8300 端口进程 = 识别模型与全部内存立即释放
cd "$(dirname "$0")"
PIDS=$(lsof -ti tcp:8300 2>/dev/null)
if [ -z "$PIDS" ]; then
  echo "ℹ️  服务未在运行（8300 端口无进程）。"
else
  echo "$PIDS" | xargs kill
  echo "✅ 已停止：$PIDS"
fi
