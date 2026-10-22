#!/bin/bash
# 双击启动「雅思听力挖空练习」后端（macOS, Apple Silicon）
# 首次运行自动：创建 .venv → 国内镜像安装依赖 → 检查 ffmpeg → 打开浏览器
cd "$(dirname "$0")"

PY=python3
PORT="${PORT:-8300}"
export PORT
VENV=.venv

# 1) Python 检查（需 3.10+）
if ! command -v $PY >/dev/null 2>&1; then
  echo "❌ 未找到 python3。请先安装："
  echo "   brew install python@3.12"
  read -r -p "按回车关闭…" _; exit 1
fi

# 2) 首次建 venv + 装依赖（清华 PyPI 镜像；macOS 会自动多装 mlx-whisper / parakeet-mlx）
if [ ! -x "$VENV/bin/python" ]; then
  echo "🛠  首次运行：创建虚拟环境并安装依赖（约 2-5 分钟）…"
  $PY -m venv "$VENV" || { echo "❌ venv 创建失败"; exit 1; }
  ./"$VENV/bin/pip" install --upgrade pip -q \
    -i https://pypi.tuna.tsinghua.edu.cn/simple || true
  ./"$VENV/bin/pip" install -r backend/requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    || { echo "❌ 依赖安装失败，请检查网络后重试（删除 $VENV 后再双击）"; exit 1; }
fi

# 3) spaCy 英文小模型（词性标注兜底用，装不上不影响主流程）
if ! ./"$VENV/bin/python" -c "import en_core_web_sm" >/dev/null 2>&1; then
  ./"$VENV/bin/pip" install \
    https://mirrors.tuna.tsinghua.edu.cn/github-release/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl \
    -i https://pypi.tuna.tsinghua.edu.cn/simple || \
  echo "⚠️  spaCy 英文模型安装失败，出题将使用启发式选词（不影响使用）"
fi

# 4) ffmpeg 检查（两个识别引擎解码音频都依赖它）
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "⚠️  未检测到 ffmpeg，语音识别需要它。请运行：brew install ffmpeg 后重新双击本文件。"
  echo "   （不识别、只用粘贴原文出题的话可以先继续）"
fi

# 5) 默认 .env（已存在则不动）
if [ ! -f .env ]; then
  cat > .env <<'EOF'
# HuggingFace 模型下载镜像（国内加速，首次识别时下载 ~1.2-1.6GB）
HF_ENDPOINT=https://hf-mirror.com
# ASR 引擎：parakeet（默认，更快更准）或 whisper，可在应用设置页随时切换
ASR_ENGINE=parakeet
ASR_PARAKEET_MODEL=mlx-community/parakeet-tdt-0.6b-v3
ASR_WHISPER_MODEL=mlx-community/whisper-large-v3-turbo
ASR_FASTER_WHISPER_MODEL=large-v3-turbo
# 空闲多少分钟自动卸载识别模型释放内存（0=常驻）
ASR_IDLE_UNLOAD_MIN=10
EOF
fi

# 6) 启动（保持窗口开着；关闭窗口或 Ctrl-C 即完全退出并释放全部内存）
echo "🚀 启动服务 http://127.0.0.1:$PORT （首次识别会先下载模型，请留意进度）"
( sleep 2 && open "http://127.0.0.1:$PORT" ) &
cd backend
exec "../$VENV/bin/python" -m app.main
