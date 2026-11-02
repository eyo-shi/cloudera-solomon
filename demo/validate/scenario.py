"""Load ``demo/<domain>/scenario.yaml`` and question definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_scenario(domain_dir: Path) -> dict[str, Any]:
    path = domain_dir / "scenario.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"missing {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("scenario.yaml must be a mapping")
    return data


def list_questions(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    """Return ``[{id, prompt, ...}, ...]`` from scenario."""
    raw = scenario.get("questions")
    if isinstance(raw, list) and raw:
        out: list[dict[str, Any]] = []
        for item in raw:
            if isinstance(item, dict) and item.get("id") and item.get("prompt"):
                out.append(dict(item))
        if out:
            return out
    exp = scenario.get("expected_answers") or {}
    prompts = scenario.get("question_prompts") or {}
    out = []
    for qid in sorted(exp.keys(), key=lambda x: (len(x), x)):
        prompt = prompts.get(qid)
        if prompt:
            out.append({"id": qid, "prompt": str(prompt).strip()})
    return out


def flatten_expected_keys(scenario: dict[str, Any], qid: str) -> tuple[list[str], list[str]]:
    """Flatten ``expected_answers[qid]`` into must-contain strings + forbidden terms."""
    exp = (scenario.get("expected_answers") or {}).get(qid)
    qrow = next((x for x in list_questions(scenario) if x.get("id") == qid), None)
    if exp is None and qrow:
        exp = qrow.get("expected")
    keys: list[str] = []
    forbidden: list[str] = []

    def walk(obj: Any) -> None:
        if obj is None:
            return
        if isinstance(obj, bool):
            keys.append("true" if obj else "false")
            return
        if isinstance(obj, (int, float)):
            keys.append(str(obj))
            return
        if isinstance(obj, str):
            s = obj.strip()
            if s:
                keys.append(s)
            return
        if isinstance(obj, list):
            for x in obj:
                walk(x)
            return
        if isinstance(obj, dict):
            if obj.get("use_containment_block"):
                cont = scenario.get("containment") or {}
                for v in cont.values():
                    walk(v)
                return
            for v in obj.values():
                walk(v)

    if exp is not None:
        walk(exp)
    extra = (scenario.get("question_expectations") or {}).get(qid) or {}
    if qrow:
        extra = {**extra, **(qrow.get("expectations") or {})}
    for s in extra.get("must_contain") or []:
        keys.append(str(s))
    forbidden.extend(str(x) for x in extra.get("must_not_contain") or [])
    planted = scenario.get("forbidden_terms_planted_docs") or []
    if qid in ("Q3", "Q4", "Q5"):
        forbidden.extend(str(x) for x in planted)
    # dedupe preserve order
    seen: set[str] = set()
    uniq_keys: list[str] = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            uniq_keys.append(k)
    return uniq_keys, forbidden


def search_check_defs(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    raw = scenario.get("search_checks") or []
    return [dict(x) for x in raw if isinstance(x, dict)]


__all__ = [
    "load_scenario",
    "list_questions",
    "flatten_expected_keys",
    "search_check_defs",
]
