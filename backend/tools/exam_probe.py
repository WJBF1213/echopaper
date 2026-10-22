"""Run the blocks-based paper generator against a real material (dev tool).

Usage:
    python -m tools.exam_probe <material_id> --type mcq_single:5 \
        --type completion:5 [--layout notes] [--regenerate] [--lang zh]

Reads the material transcript from data/app.db, uses the effective LLM
settings, prints the generated paper as JSON, and writes it next to the
material for inspection. ``--type KEY:COUNT`` is repeatable; the block
order is the paper's zone order (design §4.4).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from app.config import load_settings  # noqa: E402
from app.services import exam_gen  # noqa: E402
from app.services.exam_presets import QUESTION_TYPES  # noqa: E402

load_settings()  # inject HF env before any model import


def _llm_cfg() -> dict:
    conn = sqlite3.connect(ROOT / "data" / "app.db")
    conn.row_factory = sqlite3.Row
    stored = {}
    row = conn.execute("SELECT value_json FROM settings WHERE key='llm'").fetchone()
    if row:
        stored = json.loads(row["value_json"])
    conn.close()
    s = load_settings()
    cfg = {
        "provider": s.llm.provider,
        "base_url": s.llm.base_url,
        "model": s.llm.model,
        "api_key": s.llm.api_key,
        "max_context_tokens": s.llm.max_context_tokens,
    }
    cfg.update({k: v for k, v in stored.items() if v is not None})
    return cfg


def load_material(material_id: str) -> dict:
    conn = sqlite3.connect(ROOT / "data" / "app.db")
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id, name, words_json, sentences_json FROM materials WHERE id=?",
        (material_id,),
    ).fetchone()
    conn.close()
    if row is None:
        raise SystemExit(f"material not found: {material_id}")
    return dict(row)


def _parse_blocks(raw_args: list[str]) -> list[dict]:
    blocks: list[dict] = []
    for raw in raw_args:
        key, sep, count_text = raw.partition(":")
        if not sep or not key.strip():
            raise SystemExit(
                f"--type expects KEY:COUNT (e.g. mcq_single:5), got {raw!r}"
            )
        key = key.strip()
        qtype = QUESTION_TYPES.get(key)
        if qtype is None:
            raise SystemExit(
                f"unknown type {key!r}; available: "
                + ", ".join(QUESTION_TYPES)
            )
        try:
            count = int(count_text)
        except ValueError:
            raise SystemExit(
                f"--type expects KEY:COUNT with an integer count, got {raw!r}"
            ) from None
        if not (1 <= count <= qtype.max_count):
            raise SystemExit(
                f"count for {key} must be 1-{qtype.max_count}, got {count}"
            )
        blocks.append({"type": key, "count": count})
    return blocks


async def main() -> None:
    ap = argparse.ArgumentParser(
        description="Generate a blocks-based paper for one material.",
        epilog=(
            "type keys: "
            + ", ".join(
                f"{k} (max {q.max_count})"
                for k, q in QUESTION_TYPES.items()
            )
        ),
    )
    ap.add_argument("material_id")
    ap.add_argument(
        "--type",
        dest="types",
        action="append",
        default=[],
        metavar="KEY:COUNT",
        help="question block, repeatable (e.g. --type mcq_single:5 "
        "--type completion:5); block order = zone order",
    )
    ap.add_argument("--layout", default=None, help="force completion layout")
    ap.add_argument("--regenerate", action="store_true",
                    help="append the variation marker to bust the LLM cache")
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if not args.types:
        raise SystemExit("at least one --type KEY:COUNT is required")
    blocks = _parse_blocks(args.types)

    material = load_material(args.material_id)
    cfg = _llm_cfg()
    if not cfg.get("api_key"):
        raise SystemExit("no LLM api_key in settings")

    words = json.loads(material["words_json"] or "[]")
    sentences = json.loads(material["sentences_json"] or "[]")
    print(f"material: {material['name']}")
    print(f"words: {len(words)} sentences: {len(sentences)}")
    print(
        f"blocks: {', '.join(b['type'] + ':' + str(b['count']) for b in blocks)}"
        f"  model: {cfg['model']}"
    )

    # conn feeds the prompt registry (render_prompt + overrides) and the
    # llm_cache table.
    conn = sqlite3.connect(ROOT / "data" / "app.db")
    conn.row_factory = sqlite3.Row
    try:
        result = await exam_gen.generate_paper(
            conn,
            material,
            blocks,
            cfg,
            lang=args.lang,
            layout_hint=args.layout,
            regenerate=args.regenerate,
        )
    finally:
        conn.close()

    print(json.dumps(result.paper, ensure_ascii=False, indent=2))
    print(f"\ntotal items: {result.paper['total_items']}")
    print(f"skipped blocks: {len(result.skipped)}")
    for s in result.skipped:
        print(f"  - {s['type']}: {s['reason']}")
    print("usage:")
    for u in result.usage:
        print(
            f"  - {u['task']}: prompt={u['prompt_tokens']} "
            f"completion={u['completion_tokens']} "
            f"cached={u['cached_tokens']} hit={u['cached_hit']}"
        )
    warnings = result.paper["warnings"]
    print(f"warnings: {len(warnings)}")
    for w in warnings[:20]:
        print(f"  - {w}")

    out = Path(args.out) if args.out else (
        ROOT / "data" / f"probe_{args.material_id}.json"
    )
    out.write_text(
        json.dumps(result.paper, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nwritten: {out}")


if __name__ == "__main__":
    asyncio.run(main())
