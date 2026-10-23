# EchoPaper

[English](README.md) | 中文

> 本文与英文 [README.md](README.md) 结构保持同步；若内容不一致，以英文版为准。

EchoPaper 是一款本地优先的雅思风格听力练习应用（Windows / macOS）：导入听力音频 →
本地语音识别（词级时间戳）→ 可选的 LLM 翻译 → 从转写生成整卷试卷（六种题型，
含 LLM 重建并以 SVG 渲染的地图场景）→ 服务端判分 → 逐题正确率与错词本回顾 →
中英双语精听。全部在本地运行；只有出卷与 LLM 翻译需要 API key。

```
上传音频 ──► 本地 ASR（词级时间戳）──► 可选 LLM 翻译
                                            │
        精听 ◄── 回顾 ◄── 服务端判分 ◄── 整卷生成（六种题型）
```

后端为 FastAPI；前端为 Vue 3 SPA，后端检测到构建产物 `frontend/dist/` 时自动托管。
该目录不入库——从源码运行需先执行一次 `npm run build`（见[手动安装](#手动安装)）。

## 功能

- **三种本地识别引擎，统一接口**
  - `parakeet` — 通过 `parakeet-mlx` 运行 NVIDIA Parakeet TDT（Apple Silicon）
  - `whisper` — 通过 `mlx-whisper` 运行 Whisper large-v3-turbo（Apple Silicon）
  - `faster_whisper` — CTranslate2（Windows/Linux 有 CUDA 时用 GPU，否则 CPU）；
    Apple Silicon 之外的平台默认使用
  三种引擎都输出词级时间戳。模型在首次转写时按需加载，空闲后自动卸载（也可手动
  卸载），约释放 1.2–2 GB 内存。
- **整卷生成**：在材料页勾选题型与数量——单选、多选（选两项）、匹配、填空
  （表单/表格/笔记/句子/摘要/流程图版式）、简答、地图标注——由 LLM 一次性写出一
  份完整试卷。代码是最终裁判：答案与证据必须是转写原文的逐字段跨度；原文撑不起的
  题型以「跳过 + 一行原因」返回，绝不硬凑题目。
- **地图场景**：地图标注题由 LLM 从空间描述中重建场景（节点、路径、编号空位），
  后端硬校验（画布边界、id 唯一、空位连续编号、节点间距），试卷中以可交互 SVG
  渲染。
- **服务端判分**：提交试卷后逐题在服务端判分，接受合理的答案变体（大小写、空格、
  数字形式、人工同义答案）。作答与逐题结果持久化在 SQLite——不存分数，只存逐题
  对错。
- **回顾**：按试卷分组的逐题正确率、跨试卷的按题型统计、按答案文本聚合的错词本，
  可一键跳回错题所在的试卷。
- **中英双语精听**：专门的精听页逐句列出原文与中文翻译（导入时由 LLM 生成；无
  LLM 时回退 gtx → MyMemory 渠道）：点击句子即播放，AB 循环单句（快捷键 `L`），
  可逐词定位。
- **提示词可编辑**：所有 LLM 提示词收入注册表，可在设置页（设置 → 提示词）编辑
  ——全局系统提示、任务框架、各题型规则、地图场景重建、批量翻译。保存空文本即
  恢复内置默认。编辑提示词会使相关 LLM 缓存条目失效。
- **LLM 缓存与前缀纪律**：请求按稳定消息前缀（system → 稳定框架 → 任务框架）
  组装、temperature 0，既吃得到服务商前缀缓存，也命中本地持久化的 `llm_cache`
  表。设置页提供「清空 LLM 缓存」按钮。总上下文硬上限 256k tokens（262144）。
- **批量导入**：一次最多选择 50 个音频，逐文件显示进度，单项失败不影响其他文件。
  试卷之后在材料页生成。
- **材料、时间戳与回放**：材料保存音频、原文和词级时间戳。原文每句开头显示时间戳
  （可隐藏）；点击时间戳从该句播放（支持 AB 循环），点击任意单词从该词播放并实时
  高亮。
- **转写对齐**：上传音频时同时粘贴官方原文，应用会把时间戳映射到官方文本
  （difflib 词级对齐，插入词插值）。事后编辑转写会重新锚定，并把旧试卷标记为
  stale 保留历史，而不是删除。
- **中英双语界面**：内置中文和英文，顶栏可切换语言，支持浏览器语言检测；后端消息
  按请求的 `Accept-Language` 本地化。参见[添加语言](#添加语言)。
- **密钥只写不读**：LLM 密钥保存在本地 SQLite，API 只返回是否已配置和掩码提示，
  也可通过 `.env` 预置。

没有 LLM key 时应用仍可导入、识别、对齐、回放材料；生成试卷需要 key（exam 接口
会返回 `400` 并附提示）。

## 平台支持

Windows 与 macOS 为受支持平台。Intel Mac 和 Linux 可运行应用，并使用
`faster_whisper` 的 CPU 回退进行本地识别（Linux 启动器在[路线图](#路线图)中）。

| 平台 | 可用 ASR 引擎 | 说明 |
|---|---|---|
| Apple Silicon Mac（M1/M2/M3/M4） | `parakeet`（默认）、`whisper`、`faster_whisper` | parakeet/whisper 使用 MLX/Metal |
| Windows 10/11 | `faster_whisper` | 有 CUDA 用 GPU，否则 CPU |
| Linux | `faster_whisper` | 有 CUDA 用 GPU，否则 CPU |
| Intel Mac | `faster_whisper` | CPU 回退 |

通用要求：

- **Python 3.10+**
- **ffmpeg** 在 `PATH` 中（所有 ASR 引擎解码音频都需要）
- **Node.js 24+（jsdom 30/undici 8 的 zstd 依赖所需）**：从源码构建前端时需要（Vite 7 要求）

## 快速开始

### Windows

双击 **`start-windows.bat`**。首次运行会创建虚拟环境、安装依赖、配置 spaCy 模型、
写入默认 `.env`、启动服务并打开 <http://127.0.0.1:8300>。双击
**`stop-windows.bat`** 停止服务并释放模型内存。

### macOS

双击 **`start-macos.command`**。首次运行会自动：创建 `.venv`、安装依赖（含
`mlx-whisper` / `parakeet-mlx`）、尝试安装 spaCy 英文模型、写入默认 `.env`、
启动服务并打开 <http://127.0.0.1:8300>。双击 **`stop-macos.command`** 停止服务，
识别模型与内存立即释放。

若 macOS 拦截脚本，右键选择 **打开**，或在终端执行一次
`chmod +x start-macos.command stop-macos.command`。

### 首次运行说明

- **首次转写会下载 ASR 模型**（约 1.2–1.6 GB，见[模型与下载](#模型与下载)）。
  进度显示在任务栏；请保持启动窗口开启。
- 两个平台的启动脚本默认使用清华 PyPI 镜像安装依赖，并使用
  `HF_ENDPOINT=https://hf-mirror.com` 下载模型。
- **LLM key 可稍后配置**：出卷与 LLM 翻译需要；本地识别无需 key。

## 手动安装

在仓库根目录执行：

```bash
python -m venv .venv

# macOS / Linux
source .venv/bin/activate
# Windows（cmd/PowerShell）
.venv\Scripts\activate

pip install -r backend/requirements.txt -r backend/requirements-dev.txt

# 可选：提升判分所需的词形/词性支持；未安装时使用启发式
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
  `pip install fastapi uvicorn httpx python-multipart spacy faster-whisper`，
  然后使用 `faster_whisper` 引擎。
- Windows：可用 `winget install Gyan.FFmpeg` 或从
  <https://www.gyan.dev/ffmpeg/builds/> 安装 ffmpeg，并确保在 `PATH` 中。
  macOS：`brew install ffmpeg`。Debian/Ubuntu：`sudo apt install ffmpeg`。

## 配置

复制 `.env.example` 为 `.env`（启动脚本首次运行会自动创建）。进程环境变量优先于
`.env`。设置页会把 LLM/ASR 配置持久化到 `data/app.db`，这些已保存的值会覆盖
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

若在非 Apple Silicon 机器上的 `.env` 指定了 MLX 引擎，运行时会自动回退到
`faster_whisper`，而不是让每个任务失败。

### LLM 服务商与缓存

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
`deepseek-reasoner`）、接口地址少了或多了 `/v1`、余额不足、代理/网络不通。

**缓存行为**：LLM 请求按稳定消息前缀（system → 稳定框架 → 任务框架）组装、
temperature 0，服务商可复用前缀缓存；同时每个 JSON 响应额外缓存在本地
`llm_cache` 表——重新生成同一份试卷、或改天再打开，都不再花钱。编辑提示词会使
相关条目失效；设置页的 **清空 LLM 缓存** 按钮可一键清空。

### 编辑提示词

设置 → **提示词** 列出全部 LLM 提示词（全局系统提示、任务框架、各题型规则、
地图场景重建、批量翻译）及其变量。编辑后保存即可；按 **恢复默认**（即提交空文本）
可还原内置默认。请保留列出的每个 `{{变量}}`——缺少必需变量的提示词会被后端
拒绝。

> 从 0.1.0 之前的实验版升级、且自定义过 **地图标注规则** 提示词？请在
> 设置 → 提示词 中重置一次该覆盖——v0.1.0 新增了旧覆盖里没有的空位编号规则。

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

两套测试都会断言目录键集合一致且值非空。`translate.*` 兜底提示词可在后端目录中
本地化；出卷提示词位于提示词注册表（`backend/app/services/prompts.py`），在设置页
编辑，与目录无关。

## API 快览

交互式文档 `/docs` 为准。v0.1.0 接口面：

```
GET  /api/health                      健康检查 + 应用版本
GET  /api/asr/status | POST /api/asr/load | POST /api/asr/unload
GET|PUT /api/settings                 LLM/ASR 配置（密钥只写不读）
POST /api/settings/test-llm           用表单当前值测试 LLM 连通性
GET|PUT /api/prompts                  提示词注册表 / 保存或重置一条
DELETE /api/llm-cache                 清空本地 LLM 缓存

POST /api/materials                   新建材料（multipart）-> {job_id}
POST /api/materials/batch             批量导入音频 -> {batch_id, jobs[]}
GET  /api/batches | /api/batches/{id} 批次历史 / 逐文件进度
GET  /api/jobs/{id}                   任务进度（queued -> downloading ->
                                      transcribing -> translating -> done|error）
GET  /api/materials[/{id}]            列表 / 详情（词与句子跨度）
DELETE /api/materials/{id}
GET  /api/materials/{id}/audio        音频流（支持 HTTP Range）
PUT  /api/materials/{id}/transcript   编辑转写并重新锚定时间戳
GET  /api/materials/{id}/translations 句子翻译快照（精听页）

GET  /api/exam/types                  六种注册题型
POST /api/materials/{id}/exam         生成并持久化整卷
                                      -> {paper_id, skipped[]}
GET  /api/materials/{id}/papers       材料的试卷列表
GET|DELETE /api/papers/{id}           试卷详情（spec + 试卷 JSON）/ 删除
POST /api/papers/{id}/attempts        提交答案 -> 服务端逐题判分
                                      -> {attempt_id, items[]}
GET  /api/papers/{id}/attempts        作答历史（最新在前）
GET  /api/attempts/{id}               单次作答的逐题明细
GET  /api/papers/{id}/stats           单份试卷的逐题正确率
GET  /api/stats                       跨试卷的按题型统计

GET  /api/review/wrong-words          错词本（按答案聚合）
POST /api/translate                   英译中（带缓存与多级兜底）
```

## 验收清单（简版）

安装完成后确认：

1. 启动脚本启动服务并打开 <http://127.0.0.1:8300>；`GET /api/health` 返回
   `{"ok": true, "version": "0.1.0"}`。
2. `GET /api/asr/status` 返回 `unloaded`，空闲时内存占用较低。
3. 导入一个音频：任务依次进入 `transcribing` →（`translating`）→ `done`（首次会
   下载模型），材料的 `words` 带 `s`/`e` 时间戳。
4. 打开材料：每句开头显示时间戳；点击单词从该词播放并高亮。
5. 批量导入 2–3 个音频：逐文件更新进度，单个失败不影响其他文件。
6. 保存 LLM key，勾选题型并生成试卷：每个答案都能在转写中逐字找到；地图块渲染为
   SVG 场景，或带原因地跳过。
7. 提交答案：即时逐题判分；回顾页显示逐题正确率与错词本。
8. 等待空闲超时（或调用 `POST /api/asr/unload`）：状态回到 `unloaded`，内存下降。
9. 重启应用：材料、试卷、作答、错词本都保留在 `data/`。停止应用：8300 端口
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
    exam_gen.py         整卷生成（六种题型、拒绝处理）
    exam_scene.py       LLM 地图场景重建 + 硬校验
    exam_grade.py       服务端判分（答案等价类）
    prompts.py          提示词注册表 + 按键覆盖（设置页）
    llm.py              OpenAI 兼容客户端 + 持久化 llm_cache
    translate_svc.py    LLM 优先批量翻译，gtx/MyMemory 兜底
  i18n.py               后端消息目录（zh/en）
  config.py             .env / 环境变量配置
backend/tests/          pytest 套件（引擎/LLM/网络全部 mock）
frontend/src/           Vue 3 SPA
  i18n/                 无依赖 i18n 层与 zh/en 目录
  views/                材料库、材料、试卷、回顾、精听、设置
  components/           MapScene（SVG）、TranscriptView、PlayerBar 等
  composables/ lib/     播放器、轮询、工具函数
frontend/dist/          构建产物，后端检测到即托管（不入库；
                        npm run build 生成）
data/                   运行时：app.db（schema v3）、audio/（Git 忽略）
.models/                Hugging Face 模型缓存（Git 忽略）
docs/                   设计与参考文档（以中文为主）
start-windows.bat / stop-windows.bat             Windows 启动/停止
start-macos.command / stop-macos.command         macOS 启动/停止
LICENSE                 MIT
```

## 文档索引

- [`README.zh-CN.md`](README.zh-CN.md) —— 本中文 README
- [`CONTRIBUTING.md`](CONTRIBUTING.md) —— 开发环境、约定与 PR 清单
- [`SECURITY.md`](SECURITY.md) —— 漏洞报告与密钥处理
- [`docs/ADDING_A_LANGUAGE.md`](docs/ADDING_A_LANGUAGE.md) —— 本地化分步指南
- [`docs/reference/ielts-listening-rules.md`](docs/reference/ielts-listening-rules.md) ——
  官方雅思 Part/题型参考（备用参考，暂未接入 LLM）

## 路线图

- **Linux 部署** —— 一等公民的 Linux 启动器与打包发行。
- **多用户服务器版** —— 带认证与按用户隔离数据的部署模式，替代单用户本地应用。
- **Batch API 预生成** —— 通过批量（异步）LLM 接口离线预生成试卷，进一步降低成本。
- **Anthropic 显式缓存参数** —— 在现有稳定前缀策略之上传递显式 prompt 缓存参数。
- **官方 Part 组合快捷预设** —— 一键生成贴合真实雅思 Part 结构的试卷预设
  （如 Part 1 表单 + Part 2 地图 + Part 3 匹配）。

## 许可证

[MIT](LICENSE) © 2026 EchoPaper contributors。

欢迎贡献——请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。请勿提交 API 密钥、
`data/` 或受版权保护的音频（`test_sound/`）；安全相关说明见
[SECURITY.md](SECURITY.md)。
