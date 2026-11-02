"""Agent level: POST /api/wish SSE scoring."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from demo.validate.model import CheckResult
from demo.validate.scenario import flatten_expected_keys, list_questions, load_scenario
from demo.validate.scoring import forbidden_violations, grade_symbol, key_hit_rate


SOURCE_CONFIGS: dict[str, list[str]] = {
    "table": ["table"],
    "table_graph": ["table", "graph"],
    "table_search": ["table", "search"],
    "all": ["table", "graph", "search"],
}


def parse_http_headers() -> dict[str, str]:
    raw = os.environ.get("DEMO_VALIDATE_HTTP_HEADERS") or os.environ.get("DEMO_VALIDATE_HEADERS")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except json.JSONDecodeError:
        pass
    return {}


def run_agent(
    domain_dir: Path,
    *,
    api_base: str,
    runs: int,
    question_ids: list[str] | None,
    configs: list[str],
    extra_headers: dict[str, str] | None = None,
) -> tuple[list[CheckResult], list[dict[str, Any]], str]:
    scenario = load_scenario(domain_dir)
    questions = list_questions(scenario)
    if question_ids:
        qset = set(question_ids)
        questions = [q for q in questions if q.get("id") in qset]
    if not questions:
        return (
            [CheckResult(name="agent", ok=False, detail="no questions in scenario", category="agent")],
            [],
            "",
        )

    headers = {**(extra_headers or {}), **parse_http_headers()}
    rows: list[dict[str, Any]] = []
    results: list[CheckResult] = []
    md_lines = [
        "| config | question | run | grade | key_rate | seconds | steps |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]

    for cfg_name in configs:
        sources = SOURCE_CONFIGS.get(cfg_name)
        if not sources:
            results.append(
                CheckResult(name=f"agent_config:{cfg_name}", ok=False, detail="unknown config", category="agent")
            )
            continue
        for q in questions:
            qid = str(q.get("id"))
            prompt = str(q.get("prompt"))
            keys, forbidden = flatten_expected_keys(scenario, qid)
            for run in range(1, runs + 1):
                session_id = str(uuid.uuid4())
                answer, steps, elapsed, err = _wish_stream(
                    api_base, prompt, session_id, sources, headers=headers, timeout=180.0
                )
                if err:
                    results.append(
                        CheckResult(
                            name=f"agent:{cfg_name}:{qid}:r{run}",
                            ok=False,
                            detail=err,
                            category="agent",
                        )
                    )
                    grade = "×"
                    rate = 0.0
                else:
                    stats = key_hit_rate(answer, keys)
                    rate = float(stats["rate"])
                    bad = forbidden_violations(answer, forbidden)
                    ok = rate >= 0.8 and not bad
                    grade = grade_symbol(rate)
                    if bad:
                        grade = "×"
                    detail = f"rate={rate:.0%} hits={len(stats['hits'])}/{stats['total_keys']}"
                    if bad:
                        detail += f" forbidden={bad}"
                    results.append(
                        CheckResult(
                            name=f"agent:{cfg_name}:{qid}:r{run}",
                            ok=ok,
                            detail=detail,
                            category="agent",
                        )
                    )
                rows.append(
                    {
                        "config": cfg_name,
                        "question_id": qid,
                        "run": run,
                        "grade": grade,
                        "key_rate": rate,
                        "seconds": elapsed,
                        "steps": steps,
                        "answer_preview": (answer or "")[:500],
                        "error": err or "",
                    }
                )
                md_lines.append(
                    f"| {cfg_name} | {qid} | {run} | {grade} | {rate:.0%} | {elapsed:.1f} | {steps} |"
                )

    failures_section = _failure_details(rows)
    return results, rows, "\n".join(md_lines) + "\n\n" + failures_section


def _failure_details(rows: list[dict[str, Any]]) -> str:
    lines = ["### Failed / low-score answers", ""]
    any_fail = False
    for r in rows:
        if r.get("grade") in ("×", "△") or r.get("error"):
            any_fail = True
            lines.append(f"**{r['config']} {r['question_id']} run {r['run']}** ({r.get('grade')})")
            if r.get("error"):
                lines.append(f"- error: {r['error']}")
            prev = r.get("answer_preview") or ""
            if prev:
                lines.append(f"- answer: {prev[:800]}")
            lines.append("")
    if not any_fail:
        return "_All runs scored ◎ or ○._"
    return "\n".join(lines)


def _wish_stream(
    api_base: str,
    prompt: str,
    session_id: str,
    sources: list[str],
    *,
    headers: dict[str, str],
    timeout: float,
) -> tuple[str, int, float, str | None]:
    url = api_base.rstrip("/") + "/api/wish"
    body = {"prompt": prompt, "session_id": session_id, "sources": sources}
    tokens: list[str] = []
    steps = 0
    start = time.monotonic()
    try:
        with httpx.Client(timeout=timeout) as client:
            with client.stream("POST", url, json=body, headers=headers) as resp:
                if resp.status_code != 200:
                    text = resp.read().decode(errors="replace")
                    return "", 0, time.monotonic() - start, f"HTTP {resp.status_code}: {text[:300]}"
                current_event: str | None = None
                for line in resp.iter_lines():
                    if line.startswith("event:"):
                        current_event = line[6:].strip()
                        continue
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload:
                        continue
                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if current_event == "token" and isinstance(data, dict) and "delta" in data:
                        tokens.append(str(data["delta"]))
                    elif current_event == "step":
                        steps += 1
                    elif isinstance(data, dict) and "delta" in data:
                        tokens.append(str(data["delta"]))
    except httpx.TimeoutException:
        return "".join(tokens), steps, time.monotonic() - start, "timeout 180s"
    except Exception as exc:  # noqa: BLE001
        return "".join(tokens), steps, time.monotonic() - start, str(exc)
    return "".join(tokens), steps, time.monotonic() - start, None


__all__ = ["run_agent", "SOURCE_CONFIGS", "parse_http_headers"]
