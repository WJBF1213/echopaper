#!/bin/bash
# 双击启动「EchoPaper」后端（macOS, Apple Silicon）
# 首次运行自动：创建 .venv → 国内镜像安装依赖 → 检查 ffmpeg → 打开浏览器
cd "$(dirname "$0")"

PY=python3
PORT="${PORT:-8300}"
export PORT
VENV=.venv

# 1) Python 检查（需 3.10+）
if ! command -v $PY >/dev/null 2>&1; then
  echo "[ERROR] python3 not found. Install it first:"
  echo "   brew install python@3.12"
  read -r -p "Press Enter to close..." _; exit 1
fi

# 2) 首次建 venv + 装依赖（清华 PyPI 镜像；macOS 会自动多装 parakeet-mlx）
if [ ! -x "$VENV/bin/python" ]; then
  echo "[SETUP] First run: creating the virtual environment and installing dependencies (about 2-5 minutes)..."
  $PY -m venv "$VENV" || { echo "[ERROR] Failed to create $VENV"; exit 1; }
  ./"$VENV/bin/pip" install --upgrade pip -q \
    -i https://pypi.tuna.tsinghua.edu.cn/simple || true
  ./"$VENV/bin/pip" install -r backend/requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    || { echo "[ERROR] Dependency install failed. Check your network, delete $VENV, and double-click this file again."; exit 1; }
fi

# 3) spaCy 英文小模型（词性标注兜底用，装不上不影响主流程）
if ! ./"$VENV/bin/python" -c "import en_core_web_sm" >/dev/null 2>&1; then
  ./"$VENV/bin/pip" install \
    https://mirrors.tuna.tsinghua.edu.cn/github-release/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl \
    -i https://pypi.tuna.tsinghua.edu.cn/simple || \
  echo "[WARN] spaCy English model install failed; question generation will use the heuristic word list."
fi

# 4) ffmpeg 检查（识别引擎解码音频依赖它）
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[WARN] ffmpeg not found; speech recognition needs it. Run: brew install ffmpeg, then double-click this file again."
  echo "       (You can continue for now if you only paste transcripts without recognition.)"
fi

# 5) 默认 .env（已存在则不动）
if [ ! -f .env ]; then
  cat > .env <<'EOF'
# HuggingFace 模型下载镜像（国内加速，首次识别时下载 ~1.5GB）
HF_ENDPOINT=https://hf-mirror.com
# 空闲多少分钟自动卸载识别模型释放内存（0=常驻）
ASR_IDLE_UNLOAD_MIN=10
EOF
fi

# 6) 启动（保持窗口开着；关闭窗口或 Ctrl-C 即完全退出并释放全部内存）
echo "Starting the server at http://127.0.0.1:$PORT (the first transcription downloads the model; keep this window open)"
( sleep 2 && open "http://127.0.0.1:$PORT" ) &
cd backend
exec "../$VENV/bin/python" -m app.main
