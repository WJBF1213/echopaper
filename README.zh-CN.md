# EchoPaper

[English](README.md) | 中文

> 本文是英文 [README.md](README.md) 的中文翻译；若两者内容不一致，以英文版为准。

本地优先的 IELTS 风格听力练习应用：上传听力音频 → 本地语音识别（词级时间戳）→
混合出题（挖空题）→ 在浏览器中配合音频练习。

```
上传音频 ──► 本地 ASR（词级时间戳）──► 混合出题 ──► 浏览器练习
                                       ├─ spaCy 候选词池
                                       ├─ LLM 选择词跨度（可选）
                                       └─ 代码硬校验逐字锚定
```

后端为 FastAPI；前端为 Vue 3 SPA，由后端静态托管其构建产物 `frontend/dist/`。
该目录不入库——预构建包随 GitHub Release 附带；从源码运行需先执行一次
`npm run build`（见[手动安装](#手动安装)）。

## 功能

- **三种本地识别引擎，统一接口**
  - `parakeet` — 通过 `parakeet-mlx` 运行 NVIDIA Parakeet TDT（Apple Silicon）
  - `whisper` — 通过 `mlx-whisper` 运行 Whisper large-v3-turbo（Apple Silicon）
  - `faster_whisper` — CTranslate2（Windows/Linux 有 CUDA 时用 GPU，否则 CPU）；
    Apple Silicon 之外的平台默认使用
  三种引擎都输出词级时间戳。模型在首次转写时按需加载，空闲后自动卸载（也可手动
  卸载），约释放 1.2–2 GB 内存。
- **混合出题**：spaCy 候选池（名词、数字、专有名词等）→ LLM 按词索引选空 →
  代码硬校验：答案必须是转写原文中逐字连续的一段、最多 3 个词、按原文顺序、相邻空
  至少间隔 5 个词、不能位于句首；引擎给出置信度时还会拒绝低置信度词。数量不足时
  由代码补齐。没有 LLM key 时回退到纯本地的 `nouns` 模式。
- **LLM 上下文纪律**：每次调用都是无状态的 `[system, user]` 单次请求，绝不携带
  跨材料历史。总上下文硬上限 256k tokens（262144）；超预算材料按句边界切分为
  相互独立的调用。
- **批量导入**：一次最多选择 50 个音频，逐文件显示进度，单项失败不影响其他文件。
  可选择导入时顺便出题，或先转写入库、之后再生成题集。
- **材料、时间戳与回放**：材料保存音频、原文和词级时间戳。原文每句开头显示时间戳
  （可隐藏）；点击时间戳从该句播放（支持 AB 循环），点击任意单词从该词播放并实时
  高亮。
- **转写对齐**：上传音频时同时粘贴官方原文，应用会把时间戳映射到官方文本
  （difflib 词级对齐，插入词插值）。事后编辑转写会重新锚定，并把旧题集标记为
  stale 保留历史，而不是删除。
- **练习与回顾**：题集、每次作答判分、全篇听写、跨材料错词本（带时间戳）以及
  总览统计全部持久化在 SQLite。
- **逐句翻译**：`POST /api/translate` 提供带缓存的英译中，按 gtx → MyMemory →
  LLM 顺序兜底。
- **中英双语界面**：内置中文和英文，顶栏可切换语言，支持浏览器语言检测；后端消息
  按请求的 `Accept-Language` 本地化。参见[添加语言](#添加语言)。
- **密钥只写不读**：LLM 密钥保存在本地 SQLite，API 只返回是否已配置和掩码提示，
  也可通过 `.env` 预置。

## 平台支持

Windows 与 macOS 均受支持。Intel Mac 和 Linux 可运行应用，并使用
`faster_whisper` 的 CPU 回退进行本地识别。

| 平台 | 可用 ASR 引擎 | 说明 |
|---|---|---|
| Apple Silicon Mac（M1/M2/M3/M4） | `parakeet`（默认）、`whisper`、`faster_whisper` | parakeet/whisper 使用 MLX/Metal |
| Windows 10/11 | `faster_whisper` | 有 CUDA 用 GPU，否则 CPU |
| Linux | `faster_whisper` | 有 CUDA 用 GPU，否则 CPU |
| Intel Mac | `faster_whisper` | CPU 回退 |

通用要求：

- **Python 3.10+**
- **ffmpeg** 在 `PATH` 中（所有 ASR 引擎解码音频都需要）
- **Node.js 20.19+（或 22.12+）**：从源码构建前端时需要（Vite 7 要求）；
  Release 附带的预构建包无需 Node.js 即可运行。

## 快速开始

### macOS

双击 **`启动应用.command`**。首次运行会自动：创建 `.venv`、安装依赖（含
`mlx-whisper` / `parakeet-mlx`）、尝试安装 spaCy 英文模型、写入默认 `.env`、
启动服务并打开 <http://127.0.0.1:8300>。双击 **`停止应用.command`** 停止服务，
识别模型与内存立即释放。

若 macOS 拦截脚本，右键选择 **打开**，或在终端执行一次
`chmod +x 启动应用.command 停止应用.command`。

### Windows

双击 **`启动应用.bat`**。首次运行会创建虚拟环境、安装依赖、配置 spaCy 模型、
写入默认 `.env`、启动服务并打开 <http://127.0.0.1:8300>。双击
**`停止应用.bat`** 停止服务并释放模型内存。

两个平台的启动脚本默认使用清华 PyPI 镜像安装依赖，并使用
`HF_ENDPOINT=https://hf-mirror.com` 下载模型。LLM 为可选项，没有 API key 也能
正常使用。

## 手动安装

在仓库根目录执行：

```bash
python -m venv .venv

# macOS / Linux
source .venv/bin/activate
# Windows（cmd/PowerShell）
.venv\Scripts\activate

pip install -r backend/requirements.txt -r backend/requirements-dev.txt

# 可选：提升候选词质量；未安装时使用启发式词表
python -m spacy download en_core_web_sm
```

启动后端：

```bash
cd backend
python -m app.main
# -> http://127.0.0.1:8300（API 文档在 /docs）
```

后端检测到 `frontend/dist` 会自动托管。前端开发：

```bash
cd frontend
npm install
npm run dev        # http://127.0.0.1:5173，/api 代理到 :8300
npm run build      # vue-tsc --noEmit && vite build -> frontend/dist
```

平台说明：

- `mlx-whisper` 与 `parakeet-mlx` 带 `sys_platform == "darwin"` 环境标记，
  Windows/Linux 会自动跳过。引擎模块延迟导入依赖，因此测试和 API 可在任意平台
  运行。
- Intel Mac 无法使用 MLX 包。若 pip 无法解析它们，可显式安装其余运行时依赖：
  `pip install fastapi uvicorn httpx python-multipart jsonschema spacy faster-whisper`，
  然后使用 `faster_whisper` 引擎。
- Windows：可用 `winget install Gyan.FFmpeg` 或从
  <https://www.gyan.dev/ffmpeg/builds/> 安装 ffmpeg，并确保在 `PATH` 中。
  macOS：`brew install ffmpeg`。Debian/Ubuntu：`sudo apt install ffmpeg`。

## 配置

复制 `.env.example` 为 `.env`（启动脚本首次运行会自动创建）。进程环境变量优先于
`.env`。设置页会把 LLM/ASR/出题配置持久化到 `data/app.db`，这些已保存的值会覆盖
对应配置段的文件默认值。

| 变量 | 默认值 | 作用 |
|---|---|---|
| `PORT` | `8300` | HTTP 端口（始终只绑定 `127.0.0.1`） |
| `DATA_DIR` | `<repo>/data` | SQLite 与音频存储目录 |
| `HF_HOME` | `<repo>/.models` | Hugging Face 模型缓存 |
| `HF_ENDPOINT` | `https://hf-mirror.com` | 模型下载镜像 |
| `PIP_INDEX_URL` | 清华镜像 | 注入给 pip 子进程 |
| `ASR_ENGINE` | Apple Silicon 为 `parakeet`，其他平台为 `faster_whisper` | 当前引擎 |
| `ASR_PARAKEET_MODEL` | `mlx-community/parakeet-tdt-0.6b-v3` | Parakeet 模型 |
| `ASR_WHISPER_MODEL` | `mlx-community/whisper-large-v3-turbo` | MLX Whisper 模型 |
| `ASR_FASTER_WHISPER_MODEL` | `large-v3-turbo` | CTranslate2 模型（别名：`FASTER_WHISPER_MODEL`） |
| `ASR_IDLE_UNLOAD_MIN` | `10` | 空闲多少分钟后卸载模型（`0`=常驻） |
| `LLM_PROVIDER` | `zhipu` | `zhipu`、`dashscope`、`deepseek` 或 `custom` |
| `LLM_BASE_URL` | 服务商预设 | OpenAI 兼容接口地址 |
| `LLM_MODEL` | 服务商预设 | 模型名 |
| `LLM_API_KEY` | 空 | 可选的密钥预置；通常直接在设置页填写 |
| `LLM_MAX_CONTEXT_TOKENS` | `262144` | 可调低，但绝不允许超过 256k |
| `GEN_BLANK_COUNT` | `10` | 设置页展示的挖空数配置（每次请求会显式携带数量） |

若在非 Apple Silicon 机器上的 `.env` 指定了 MLX 引擎，运行时会自动回退到
`faster_whisper`，而不是让每个任务失败。

### LLM 服务商

设置页内置以下 OpenAI 兼容服务商预设：

| 服务商 | 接口地址 | 默认模型 |
|---|---|---|
| `zhipu` | `https://open.bigmodel.cn/api/paas/v4` | `glm-4.7-flash` |
| `dashscope` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-flash` |
| `deepseek` | `https://api.deepseek.com/v1` | `deepseek-chat` |
| `custom` | 自定义 | 自定义 |

填写密钥后点 **保存并测试**：先落库，再用表单当前值发送一次真实请求。密钥只写
不读——API 只返回 `has_key` 和掩码提示。密钥输入框留空表示保留已存密钥。测试失败
会显示服务商返回的原始原因（HTTP 401、模型不存在等）。

常见失败原因：模型名不存在（DeepSeek 使用 `deepseek-chat` 或
`deepseek-reasoner`）、接口地址少了或多了 `/v1`、余额不足、代理/网络不通。只在
输入框敲了 key 但没保存时，后端读不到它——测试使用的是表单当前值。

没有密钥也能使用：出题自动使用本地 `nouns` 模式；有密钥时使用质量更高的 `llm`
混合模式。

## 模型与下载

- 模型权重缓存在 `HF_HOME`（默认 `.models/`）。下载经过 `HF_ENDPOINT`
  （默认 `hf-mirror.com`）；首次下载完成后可离线使用。
- Apple Silicon 上，`parakeet`（`mlx-community/parakeet-tdt-0.6b-v3`）和
  `whisper`（`mlx-community/whisper-large-v3-turbo`）首次转写时约下载
  1.2–1.6 GB。
- `faster_whisper` 使用 CTranslate2 的 `large-v3-turbo` 模型 —— 与 MLX 引擎同一份
  Whisper 权重，只是转换为 CTranslate2 格式。CUDA 下以 `float16` 运行，CPU 下以
  `int8` 运行；CUDA 运行库缺失时会自动回退 CPU，而不是让转写任务失败。
- **Hugging Face 访问不了？** `app/services/model_download.py` 会先探测 HF，在
  `huggingface.co` / `hf-mirror.com` 超时时自动改用 ModelScope 上相同的
  CTranslate2 文件。也可以把模型设置填成本地目录（包含 `config.json`、
  `model.bin`、`tokenizer.json`、`vocabulary.json`），实现完全离线使用。
- 在设置页切换引擎会立即卸载当前模型。空闲卸载（`ASR_IDLE_UNLOAD_MIN`，默认
  10 分钟）会自动释放内存；`POST /api/asr/unload` 可立即卸载。

## 添加语言

前端使用一个无依赖的小型 i18n 层（`frontend/src/i18n/index.ts`），包含响应式
`locale` ref、`t()`、`localStorage` 持久化和顶栏语言选择器。后端在
`backend/app/i18n.py` 中有独立的消息目录，并按请求的 `Accept-Language` 本地化
任务/错误消息（前端会发送当前 UI 语言）。

- 简要说明：[`CONTRIBUTING.md`](CONTRIBUTING.md#adding-a-ui-language)
- 带代码片段的详细步骤：
  [`docs/ADDING_A_LANGUAGE.md`](docs/ADDING_A_LANGUAGE.md)

两套测试都会断言目录键集合一致且值非空。LLM 提示词条目（`question_gen.*`、
`translate.*`）同样可以在后端目录中本地化。

## API 快览

完整契约见设计文档 §8，以及 `/docs` 的交互式文档。

```
GET  /api/health                      健康检查
GET  /api/asr/status | POST /api/asr/load | POST /api/asr/unload
GET|PUT /api/settings                 LLM/ASR/出题配置（密钥只写不读）
POST /api/settings/test-llm           用表单当前值测试 LLM 连通性
POST /api/materials                   新建材料（multipart）-> {job_id}
POST /api/materials/batch             批量导入音频 -> {batch_id, jobs[]}
GET  /api/batches[/{id}]              批次历史 / 逐文件进度
GET  /api/jobs/{id}                   任务进度（queued -> transcribing -> generating -> done|error）
GET  /api/materials[/{id}]            列表 / 详情
DELETE /api/materials/{id}
GET  /api/materials/{id}/audio        音频流（支持 HTTP Range）
PUT  /api/materials/{id}/transcript   编辑转写并重新锚定时间戳
POST /api/materials/{id}/sets         生成题集（llm | nouns | manual）
GET|DELETE /api/sets/{id}             题集详情（每空含 t_start/t_end/word_limit）
POST /api/sets/{id}/attempts          提交并判分
POST /api/materials/{id}/attempts     全篇听写
GET  /api/materials/{id}/attempts     材料的作答历史
GET  /api/review/wrong-words          跨材料错词本
GET  /api/stats                       总览统计
POST /api/translate                   英译中（带缓存与多级兜底）
```

## 验收清单（简版）

安装完成后确认：

1. 启动脚本启动服务并打开 <http://127.0.0.1:8300>；`GET /api/health` 返回
   `{"ok": true, ...}`。
2. `GET /api/asr/status` 返回 `unloaded`，空闲时内存占用较低。
3. 导入一个音频：任务依次进入 `transcribing` → `generating` → `done`（首次会
   下载模型），材料的 `words` 带 `s`/`e` 时间戳。
4. 打开材料：每句开头显示时间戳；点击单词从该词播放并高亮。
5. 批量导入 2–3 个音频：逐文件更新进度，单个失败不影响其他文件。
6. 保存 LLM key 并生成 `llm` 题集：每个答案都能在转写中逐字找到。没有 key 时
   `nouns` 模式仍可用。
7. 等待空闲超时（或调用 `POST /api/asr/unload`）：状态回到 `unloaded`，内存下降。
8. 在设置页切换引擎：当前模型卸载，下一个任务使用新引擎。
9. 重启应用：材料、题集、作答、错词本都保留在 `data/`。停止应用：8300 端口
   进程退出，内存释放。

## 测试

```bash
# 后端：所有 ASR 引擎、LLM 和网络访问均为 mock，
# 因此任意系统都能运行，无需下载模型。
python -m pytest backend/tests -q

# 前端：Vitest + jsdom
cd frontend
npm install
npm test

# 类型检查并构建由后端托管的前端
npm run build
```

## 目录结构

```
backend/app/            FastAPI 应用
  routers/              HTTP 路由
  services/             领域层（不依赖 FastAPI，便于移植）
  i18n.py               后端消息与 LLM 提示词目录
  config.py             .env / 环境变量配置
backend/tests/          pytest 套件（引擎/LLM/网络全部 mock）
frontend/src/           Vue 3 SPA
  i18n/                 无依赖 i18n 层与 zh/en 目录
  views/ components/    界面
  composables/ lib/     播放器、轮询、工具函数
frontend/dist/          构建产物，由后端托管（不入库；npm run build
                        或使用 Release 附带的预构建包）
data/                   运行时：app.db、audio/、incoming/（Git 忽略）
.models/                Hugging Face 模型缓存（Git 忽略）
docs/                   设计与实现文档（以中文为主）
docs/ADDING_A_LANGUAGE.md  本地化分步指南
启动应用.command / 停止应用.command              macOS 启动/停止
启动应用.bat / 停止应用.bat                      Windows 启动/停止
LICENSE                 MIT
SECURITY.md             漏洞报告与密钥处理
CONTRIBUTING.md         开发环境、约定与语言指南
README.zh-CN.md         本中文 README
```

## 旧版本

以下文件仅供留档，当前应用**不再使用**，其数据与新后端不兼容：

- `雅思听力挖空练习.html` — 最早的单文件版本。
- `asr_server.py` + `启动本地识别服务.command` / `启动本地识别服务.bat` — 旧版
  Qwen3-ASR 常驻服务（端口 8399）。

## 许可证

[MIT](LICENSE) © 2026 EchoPaper contributors。

欢迎贡献——请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。请勿提交 API 密钥、
`data/` 或受版权保护的音频（`test_sound/`）；安全相关说明见
[SECURITY.md](SECURITY.md)。
