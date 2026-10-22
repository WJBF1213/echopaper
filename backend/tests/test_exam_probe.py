"""Smoke tests for the dev probe tool (design §十二: --type KEY:COUNT args)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_probe_cli_help_lists_type_args():
    """The probe imports cleanly (no preset/Part leftovers) and exposes the
    repeatable --type KEY:COUNT interface."""
    proc = subprocess.run(
        [sys.executable, "-m", "tools.exam_probe", "--help"],
        cwd=BACKEND, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "--type" in proc.stdout
    assert "mcq_single" in proc.stdout or "KEY:COUNT" in proc.stdout


def test_probe_rejects_bad_type_arg():
    proc = subprocess.run(
        [sys.executable, "-m", "tools.exam_probe", "m1", "--type", "bogus:3"],
        cwd=BACKEND, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode != 0
    assert "bogus" in (proc.stderr + proc.stdout)
