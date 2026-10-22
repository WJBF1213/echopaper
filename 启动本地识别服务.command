#!/bin/bash
# 双击启动 Qwen3-ASR 本地识别服务（保持窗口开启，识别完成后也别关）
cd "$(dirname "$0")"
./.asr-venv/bin/python asr_server.py 8399
