"""demo/mfg_quality ジェネレータ（LLM 不使用）。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DEMO = REPO / "demo" / "mfg_quality"


@pytest.mark.skipif(not DEMO.is_dir(), reason="demo/mfg_quality not present")
def test_semantic_validate() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "solomon.semantic",
            "validate",
            "--root",
            str(DEMO / "semantic"),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(not DEMO.is_dir(), reason="demo/mfg_quality not present")
def test_generator_scale_deterministic(tmp_path: Path) -> None:
    env = {"PYTHONPATH": str(REPO)}
    out1 = tmp_path / "o1"
    out2 = tmp_path / "o2"
    cmd = [
        sys.executable,
        "-m",
        "demo.mfg_quality.generator",
        "--seed",
        "42",
        "--scale",
        "0.01",
        "--docs",
        "template",
    ]
    for out in (out1, out2):
        p = subprocess.run(
            [*cmd, "--out", str(out)],
            cwd=REPO,
            env={**__import__("os").environ, **env},
            capture_output=True,
            text=True,
        )
        assert p.returncode == 0, p.stdout + p.stderr

    m1 = json.loads((out1 / "manifest.json").read_text())
    m2 = json.loads((out2 / "manifest.json").read_text())
    assert m1["checks"]["ok"] is True
    assert m1["table_hashes"] == m2["table_hashes"]

    h1 = hashlib.sha256((out1 / "tables" / "unit_lots.parquet").read_bytes()).hexdigest()
    h2 = hashlib.sha256((out2 / "tables" / "unit_lots.parquet").read_bytes()).hexdigest()
    assert h1 == h2
