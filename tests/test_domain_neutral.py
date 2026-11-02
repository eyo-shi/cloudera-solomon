"""Domain-neutral guard for core packages."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_domain_neutral_script() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "check_domain_neutral.py"
    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=str(script.parents[1]),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
