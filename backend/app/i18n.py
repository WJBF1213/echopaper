"""Request-scoped message catalog for user-facing backend text.

The UI is localized in the frontend; the backend still produces messages that
surface in the UI (job progress, validation errors, engine/LLM failures).
Those go through :func:`t` so they follow the caller's ``Accept-Language``.

Adding a language
-----------------
1. Copy the ``"en"`` block in :data:`MESSAGES` and translate every value.
2. Keep the keys unchanged; a test asserts all catalogs share one key set.
3. Add the language code to :data:`SUPPORTED`.
4. If the language's prompts should differ, translate the ``translate.*``
   and prompt entries too — the LLM prompts live here as well.

Unknown keys fall back to the default locale and then to the key itself, so a
misspelled key is visible instead of silently empty.
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

DEFAULT_LOCALE = "zh"
SUPPORTED = ("zh", "en")

_locale: ContextVar[str] = ContextVar("app_locale", default=DEFAULT_LOCALE)


def normalize_locale(value: str | None) -> str:
    """Pick the best supported locale from an ``Accept-Language`` header."""
    if not value:
        return DEFAULT_LOCALE
    for part in value.lower().replace(";", ",").split(","):
        tag = part.strip()
        if not tag:
            continue
        primary = tag.split("-")[0]
        if primary in SUPPORTED:
            return primary
    return DEFAULT_LOCALE


def get_locale() -> str:
    return _locale.get()


def set_locale(locale: str) -> Token:
    return _locale.set(locale if locale in SUPPORTED else DEFAULT_LOCALE)


def reset_locale(token: Token) -> None:
    _locale.reset(token)


def t(key: str, **params: Any) -> str:
    """Translate ``key`` in the current request's locale."""
    locale = get_locale()
    catalog = MESSAGES.get(locale) or {}
    template = catalog.get(key)
    if template is None:
        template = MESSAGES[DEFAULT_LOCALE].get(key, key)
    if not params:
        return template
    try:
        return template.format(**params)
    except (KeyError, IndexError):
        return template


MESSAGES: dict[str, dict[str, str]] = {
    "zh": {
        # --- generic -------------------------------------------------------
        "app.title": "雅思听力挖空练习",
        "common.untitled_material": "未命名材料",
        "common.material_not_found": "材料不存在",
        "common.paper_not_found": "试卷不存在",
        "common.attempt_not_found": "作答记录不存在",
        "common.batch_not_found": "批次不存在",
        "common.job_not_found": "任务不存在",
        "common.audio_missing": "该材料没有音频",
        "common.audio_file_missing": "音频文件缺失",
        "common.need_input": "需要提供音频文件、音频 URL 或转写文本之一",
        "common.need_one_audio": "请至少选择一个音频文件",
        "common.too_many_files": "单次最多 {limit} 个音频，请分批导入",
        "common.unsupported_audio": "不支持的音频格式：{name}",
        "common.batch_failed": "批量导入失败：{error}",
        "common.batch_default_name": "批量导入 {time}",
        "common.align_failed": "原文对齐失败（匹配率 {rate:.0%}），已改用识别文本",
        "common.align_failed_keep": "原文对齐失败（匹配率 {rate:.0%}），已保留原词表",
        "common.restart_interrupted": "服务重启，任务已中断，请重新导入",
        "common.frontend_hint": (
            "前端构建产物不存在（frontend/dist）。后端 API 正常运行："
            "/docs、/api/health。前端的构建方式见 README。"
        ),
        # --- pipeline ------------------------------------------------------
        "job.downloading": "下载音频",
        "job.transcribing": "本地识别中",
        "job.translating": "生成译文中",
        "job.no_input": "缺少音频或转写文本，无法创建材料",
        "job.audio_not_found": "音频文件不存在：{path}",
        # --- engines -------------------------------------------------------
        "engine.unknown": "未知引擎：{name}",
        "engine.unsupported": "当前系统不支持引擎 {name}；可用引擎：{available}",
        "engine.fallback": "当前系统不支持 {requested} 引擎，已自动使用 {fallback}",
        "engine.load_failed": "{engine} 引擎加载失败：{error}；请在设置页更换引擎或模型",
        "engine.busy_switch": "busy：转写进行中，禁止切换",
        "engine.busy_unload": "busy：转写进行中，禁止卸载",
        "engine.unloaded_retry": "引擎已被卸载，请重试",
        "engine.changed_wait": "引擎选择已变更，请等待当前转写完成",
        # --- LLM -----------------------------------------------------------
        "llm.incomplete": "LLM 配置不完整：provider={provider} 需要 base_url 与 model",
        "llm.truncated": "finish_reason={reason}（输出被截断）",
        "llm.invalid": "LLM 返回不符合要求（已重试一次）：{error}",
        "llm.probe_ok": "连接正常",
        "llm.no_key": "未配置 LLM API key：请填写密钥后点击「保存并测试」",
        "llm.retry_hint": (
            "{user}\n\n上一次返回不符合要求：{error}\n"
            "请严格返回符合要求的 JSON 对象，不要任何多余文本。"
        ),
        # --- audio ---------------------------------------------------------
        "audio.no_data": "缺少音频数据（data/url 二选一）",
        "audio.download_http": "下载失败：HTTP {status}",
        "audio.download_failed": "下载失败：{error}",
        # --- translation ---------------------------------------------------
        "translate.gtx_empty": "gtx 空结果",
        "translate.mymemory_empty": "MyMemory 无有效结果",
        "translate.all_failed": "全部翻译渠道失败（gtx / MyMemory / LLM）",
        "translate.system": "你是英译中翻译引擎，只返回 JSON。",
        "translate.user": "将下面的英文句子翻译成简体中文：\n{text}",
        # --- prompts registry (Task 6) -------------------------------------
        "prompts.not_found": "提示词不存在：{name}",
        "prompts.missing_placeholders": "提示词 {name} 缺少必需占位符：{missing}",
    },
    "en": {
        # --- generic -------------------------------------------------------
        "app.title": "IELTS Listening Cloze",
        "common.untitled_material": "Untitled material",
        "common.material_not_found": "Material not found",
        "common.paper_not_found": "Paper not found",
        "common.attempt_not_found": "Attempt not found",
        "common.batch_not_found": "Batch not found",
        "common.job_not_found": "Job not found",
        "common.audio_missing": "This material has no audio",
        "common.audio_file_missing": "Audio file is missing",
        "common.need_input": "Provide an audio file, an audio URL, or a transcript",
        "common.need_one_audio": "Select at least one audio file",
        "common.too_many_files": "At most {limit} files per batch; import in smaller batches",
        "common.unsupported_audio": "Unsupported audio format: {name}",
        "common.batch_failed": "Batch import failed: {error}",
        "common.batch_default_name": "Batch import {time}",
        "common.align_failed": (
            "Transcript alignment failed (match rate {rate:.0%}); using ASR text"
        ),
        "common.align_failed_keep": (
            "Transcript alignment failed (match rate {rate:.0%}); keeping the ASR word list"
        ),
        "common.restart_interrupted": "Service restarted; job interrupted. Please import again",
        "common.frontend_hint": (
            "No frontend build found (frontend/dist). The API is running: "
            "/docs, /api/health. See README for building the frontend."
        ),
        # --- pipeline ------------------------------------------------------
        "job.downloading": "Downloading audio",
        "job.transcribing": "Transcribing locally",
        "job.translating": "Translating",
        "job.no_input": "Audio or transcript is required to create a material",
        "job.audio_not_found": "Audio file not found: {path}",
        # --- engines -------------------------------------------------------
        "engine.unknown": "Unknown engine: {name}",
        "engine.unsupported": (
            "Engine {name} is not supported on this system; available: {available}"
        ),
        "engine.fallback": (
            "Engine {requested} is not supported here; using {fallback} instead"
        ),
        "engine.load_failed": (
            "Failed to load the {engine} engine: {error}. "
            "Pick another engine or model in Settings"
        ),
        "engine.busy_switch": "busy: transcription in progress, cannot switch engines",
        "engine.busy_unload": "busy: transcription in progress, cannot unload",
        "engine.unloaded_retry": "Engine was unloaded; please retry",
        "engine.changed_wait": "Engine selection changed; wait for the current transcription",
        # --- LLM -----------------------------------------------------------
        "llm.incomplete": "Incomplete LLM config: provider={provider} needs base_url and model",
        "llm.truncated": "finish_reason={reason} (output truncated)",
        "llm.invalid": "LLM response did not satisfy the schema (retried once): {error}",
        "llm.probe_ok": "Connection OK",
        "llm.no_key": "No LLM API key configured. Enter a key and click “Save & test”",
        "llm.retry_hint": (
            "{user}\n\nThe previous response did not satisfy the requirements: {error}\n"
            "Return only a compliant JSON object with no extra text."
        ),
        # --- audio ---------------------------------------------------------
        "audio.no_data": "No audio data (provide data or url)",
        "audio.download_http": "Download failed: HTTP {status}",
        "audio.download_failed": "Download failed: {error}",
        # --- translation ---------------------------------------------------
        "translate.gtx_empty": "gtx returned no result",
        "translate.mymemory_empty": "MyMemory returned no usable result",
        "translate.all_failed": "All translation channels failed (gtx / MyMemory / LLM)",
        "translate.system": "You are an English-to-Chinese translation engine. Return JSON only.",
        "translate.user": "Translate the following English sentence into Simplified Chinese:\n{text}",
        # --- prompts registry (Task 6) -------------------------------------
        "prompts.not_found": "Unknown prompt: {name}",
        "prompts.missing_placeholders": (
            "Prompt {name} is missing required placeholder(s): {missing}"
        ),
    },
}
