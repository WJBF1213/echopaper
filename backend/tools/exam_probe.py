"""Run the experimental exam generator against a real material (dev tool).

Usage:
    python -m tools.exam_probe <material_id> --part 1 [--preset p1_form]

Reads the material transcript from data/app.db, uses the effective LLM
settings, prints the generated paper as JSON, and writes it next to the
material for inspection.
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
from app.services.exam_presets import PRESETS, default_preset, presets_for_part  # noqa: E402

load_settings()  # inject HF env before any model import


def _llm_cfg() -> dict:
    conn = sqlite3.connect(ROOT / "data" / "app.db")
    conn.row_factory = sqlite3.Row
    stored = {}
    row = conn.execute("SELECT value_json FROM settings WHERE key='llm'").fetchone()
    if row:
        stored = json.loads(row["value_json"])
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


def load_material(material_id: str) -> tuple[str, list[dict], list[list[int]]]:
    conn = sqlite3.connect(ROOT / "data" / "app.db")
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT name, words_json, sentences_json FROM materials WHERE id=?",
        (material_id,),
    ).fetchone()
    if row is None:
        raise SystemExit(f"material not found: {material_id}")
    return (
        row["name"],
        json.loads(row["words_json"] or "[]"),
        json.loads(row["sentences_json"] or "[]"),
    )


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("material_id")
    ap.add_argument("--part", type=int, default=1)
    ap.add_argument("--preset", default=None)
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.part not in (1, 2, 3, 4):
        raise SystemExit("--part must be 1-4")
    preset = args.preset or default_preset(args.part)
    if preset not in PRESETS:
        raise SystemExit(
            f"unknown preset; available: {', '.join(PRESETS)}"
        )

    name, words, sentences = load_material(args.material_id)
    cfg = _llm_cfg()
    if not cfg.get("api_key"):
        raise SystemExit("no LLM api_key in settings")

    print(f"material: {name}")
    print(f"words: {len(words)} sentences: {len(sentences)}")
    print(
        f"presets for part {args.part}: "
        + ", ".join(p.key for p in presets_for_part(args.part))
    )
    print(f"preset: {preset}  model: {cfg['model']}")

    paper = await exam_gen.generate_paper(
        words,
        sentences,
        part=args.part,
        preset=preset,
        llm_cfg=cfg,
        material_id=args.material_id,
        lang=args.lang,
    )
    data = paper.to_dict()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\ntotal items: {paper.total_items}")
    print(f"warnings: {len(paper.warnings)}")
    for w in paper.warnings[:20]:
        print(f"  - {w}")

    out = Path(args.out) if args.out else (
        ROOT / "data" / f"probe_{args.material_id}_p{args.part}.json"
    )
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwritten: {out}")


if __name__ == "__main__":
    asyncio.run(main())
