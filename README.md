# 雅思听力挖空练习 · 后端服务（macOS 版）

上传英语听力音频 → 本地语音识别（词级时间戳）→ 混合出题（LLM 选空 + 代码锚定校验）→ 浏览器听音填空。全量记忆落盘（SQLite + 音频文件），支持材料/题目/成绩/错词回顾。

> **前端已交付**：`frontend/`（Vue 3 + Vite + TypeScript，构建产物 `frontend/dist` 已入库，Mac 免 Node）。后端检测到 `frontend/dist` 即自动托管；实现细节见 `docs/superpowers/specs/2026-10-21-前端实现说明.md`，出题方案调研见 `docs/superpowers/specs/2026-10-21-挖空出题方案调研.md`。

## 系统要求（仅此三项）

| 依赖 | 说明 |
|---|---|
| Apple Silicon Mac（M1/M2/M3/M4） | 识别引擎基于 MLX/Metal；Intel 与 Windows 仅能运行 API 与测试，不能本地识别 |
| Python 3.10+ | `brew install python@3.12` |
| ffmpeg | `brew install ffmpeg`（识别引擎解码音频需要） |

## 启动（双击即可）

双击 **`启动应用.command`**。首次运行自动完成：创建 `.venv` → 清华镜像安装依赖（macOS 会多装 mlx-whisper 与 parakeet-mlx）→ 安装 spaCy 英文小模型（失败仅降级选词，不影响使用）→ 写入默认 `.env` → 启动服务并打开浏览器 <http://127.0.0.1:8300>。

双击 **`停止应用.command`** 结束进程——识别模型与全部内存立即释放。

## 核心机制

- **双识别引擎（平等可切换）**：`parakeet-mlx`（NVIDIA Parakeet TDT，快约一个量级、英语 WER 更优）与 `mlx-whisper`（whisper-large-v3-turbo）都随 venv 安装；设置页 `PUT /api/settings` 随时切换，切换立即卸载当前引擎。首次转写时经 `HF_ENDPOINT=https://hf-mirror.com` 下载模型（~1.2-1.6GB，缓存 `.models/`，之后离线可用）。
- **按需加载 / 空闲卸载**：引擎对象仅在首个转写任务时加载（秒级）；空闲 `ASR_IDLE_UNLOAD_MIN`（默认 10 分钟，0=常驻）自动 `del + gc` 释放约 1.2-2GB；`POST /api/asr/unload` 可手动立即卸载。转写与切换/卸载经异步锁串行化。
- **混合出题**：spaCy 候选池（名词为主）→ LLM 单次调用按词索引选空（默认智谱 GLM-4.7-Flash 免费，支持 dashscope/deepseek/任意 OpenAI 兼容自定义）→ 代码硬校验（答案必须逐字锚定转写、间距≥5词、顺序、非句首）→ 不足时代码补齐。无 API key 时纯程序化名词档。
  - **LLM 上下文纪律**：单次调用总上下文硬上限 **256k tokens（262144）**，即使模型标称更大也不允许（防超长上下文性能衰减）；超预算按句分块独立调用；**每个听力材料 = 独立无状态会话**，绝不携带跨材料历史。
- **记忆与回顾**：材料（音频+转写+词级时间戳）、题集、每次作答、错词本全在 `data/app.db` + `data/audio/`；`GET /api/review/wrong-words` 跨材料聚合错词并带时间戳（点击即可回跳重听）。
- **批量转写与存储**：材料库「批量转写」可一次多选最多 50 个音频；后端把每个文件流式暂存到 `data/incoming/`，再逐文件排队做 ASR，完成后各自成为独立材料（音频落到 `data/audio/`、词级时间戳与原文写入 SQLite）。默认只转写入库，勾选「转写后顺便出题」才会逐材料生成题集。批次进度逐文件显示，失败互不影响；`GET /api/batches[/{id}]` 可查最近批次与每个文件的阶段。服务重启会把中断中的任务标为失败并清理未入库的暂存文件，避免批次永远停在“识别中”。
- **原文时间戳与直接回放**：材料详情与练习页的原文按句分行，**每句开头显示句首时间戳**（可隐藏）；点击时间戳从该句开头播放并 AB 循环，点击任意单词从该词播放，播放中的词实时高亮。练习时点题号仍会跳到答案词前 1.5 秒并循环整句；纯文本材料（无词级时间戳）不显示时间戳、不响应点击。
- **转写对齐**：上传音频同时粘贴官方原文时，原文为题目权威文本、时间戳从 ASR 词映射（difflib 词级对齐，插入词插值）；事后 `PUT /api/materials/{id}/transcript` 可编辑转写并重锚定（旧题集标 stale 保留历史）。

## API 快览（完整契约见设计文档 §8）

```
GET  /api/health                      健康检查
GET  /api/asr/status | POST load/unload    引擎状态/手动加载/立即卸载
GET|PUT /api/settings                 LLM(provider/key/model) 与 ASR 配置（key 只写不读）
POST /api/settings/test-llm           LLM 连通性测试
POST /api/materials                   新建材料（multipart）→ {job_id}
POST /api/materials/batch             批量导入音频（multipart 字段 audios，可多个）→ {batch_id, jobs[]}
GET  /api/batches[/{id}]              批次历史 / 批次总进度 + 逐文件状态
GET  /api/jobs/{id}                   任务进度（queued→downloading→transcribing→generating→done|error）
GET|DELETE /api/materials[/{id}]      列表/详情/删除；/audio 支持 Range 拖动
PUT  /api/materials/{id}/transcript   事后编辑转写→重对齐
POST /api/materials/{id}/sets         生成题集（llm|nouns|manual）
GET|DELETE /api/sets/{id}             题集详情（含每空 t_start/t_end/word_limit）
POST /api/sets/{id}/attempts          提交作答→服务端判分存档
POST /api/materials/{id}/attempts     全篇听写（虚拟题集）判分
GET  /api/review/wrong-words | /api/stats   错词本 / 总览统计
POST /api/translate                   逐句中译（gtx→MyMemory→LLM 兜底，库内缓存）
```

## 开发（Windows/macOS 通用）

```bash
python -m venv .venv && .venv/Scripts/pip install -r backend/requirements.txt -r backend/requirements-dev.txt   # macOS 用 .venv/bin/pip
.venv/Scripts/python -m pytest backend/tests -q        # 139 个测试，全部 mock 引擎/LLM/网络，无需 macOS
cd backend && ../.venv/Scripts/python -m app.main      # 本机起服务（127.0.0.1:8300）

cd frontend && npm install && npm test && npm run build   # 43 个 Vitest；产物 dist/ 入库
cd frontend && npm run dev                             # 前端热更新（:5173，/api 代理到 :8300）
```

macOS-only 依赖（mlx-whisper/parakeet-mlx）带 `sys_platform == "darwin"` 环境标记，Windows 开发机自动跳过；引擎模块延迟 import，测试在任意平台可跑。

## Mac 验收清单（部署后逐项确认）

1. 双击 `启动应用.command`：首次建 venv/装依赖（2-5 分钟）→ 浏览器自动打开 `http://127.0.0.1:8300`（或返回 JSON 提示=前端未部署，正常）。
2. `GET /api/asr/status` 返回 `unloaded`；活动监视器中 Python 进程内存 < 300MB（模型未加载）。
3. `POST /api/materials`（带 mp3）→ job 进入 `transcribing`：首次可见模型下载进度（终端窗口），此后秒级加载。
4. 转写完成：`GET /api/materials/{id}` 的 `words` 带词级 `s/e` 时间戳。
5. 批量导入 2-3 个音频：批次进度逐文件更新；全部完成后材料库出现同名材料；`data/audio/` 数量与材料数一致。
6. 打开材料详情：原文每句前有 `m:ss` 时间戳，点击单词能从该词播放并高亮；练习页同样可见句首时间戳。
7. 配置 LLM key（智谱免费）→ 生成 llm 题集：blanks 的 answer 均可在 transcript 中逐字找到；无 key 走 nouns 档。
8. 转写后空闲 10 分钟：活动监视器确认 Python 内存回落（模型已卸载）；`/api/asr/status` 回到 `unloaded`。
9. 设置页切引擎 parakeet↔whisper：切换后 status 立即 `unloaded`，下次转写用新引擎。
10. 重启电脑/重跑启动脚本：材料、题集、成绩、错词本全部还在（`data/` 目录）。
11. 双击 `停止应用.command`：8300 进程结束，内存全部释放。

## 旧版本

`雅思听力挖空练习.html`（单文件版）、`asr_server.py` + `启动本地识别服务.command`（Qwen3-ASR 常驻服务）为 legacy，保留未动；新旧数据不互通。

## 目录

```
backend/app/          FastAPI 应用（routers/ + services/，services 不依赖 fastapi 便于移植）
backend/tests/        139 个 pytest（引擎/LLM/网络全 mock）
frontend/src/         Vue 3 SPA（views/ components/ composables/ lib/）
frontend/dist/        构建产物（入库，后端静态托管）
data/                 运行时生成：app.db + audio/
.models/              HF 模型缓存（hf-mirror 下载）
启动应用.command / 停止应用.command
docs/superpowers/     设计文档（§8=前后端契约）、实施计划、前端说明、出题调研
```
