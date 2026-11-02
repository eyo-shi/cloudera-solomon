"""LLM 文書生成（--docs llm）。キャッシュは cache/llm/。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def cache_path(cache_dir: Path, prompt: str) -> Path:
    key = hashlib.sha256(prompt.encode()).hexdigest()[:24]
    return cache_dir / f"{key}.json"


def cached_completion(cache_dir: Path, prompt: str, *, generate) -> str:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_path(cache_dir, prompt)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))["text"]
    text = generate(prompt)
    path.write_text(json.dumps({"text": text}, ensure_ascii=False), encoding="utf-8")
    return text
