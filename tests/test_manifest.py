"""Agent Studio manifest 生成のテスト (LLM / crewai なし)。"""
from __future__ import annotations

from pathlib import Path

import pytest

import solomon.tools as tools_pkg
from solomon.manifest import (
    build_agents_manifest,
    build_crews_manifest,
    build_tools_manifest,
    dump_manifest_yaml,
    write_manifests,
)
from solomon.manifest.cli import main as cli_main
from solomon.manifest.writer import AGENTS_FILE, CREWS_FILE, TOOLS_FILE


def test_all_public_tools_appear_in_tools_manifest() -> None:
    m = build_tools_manifest()
    names = {t["name"] for t in m["tools"]}
    expected: set[str] = set()
    for cls_name in tools_pkg.__all__:
        cls = getattr(tools_pkg, cls_name)
        expected.add(cls().name)
    assert names == expected
    assert m["version"] == 1


def test_tools_have_json_schema_args() -> None:
    m = build_tools_manifest()
    for t in m["tools"]:
        schema = t["args_schema"]
        assert schema.get("type") == "object", t["name"]
        assert "properties" in schema, t["name"]


def test_router_agents_present() -> None:
    m = build_agents_manifest()
    names = [a["name"] for a in m["agents"] if a["crew"] == "router"]
    assert "intent_classifier" in names
    assert "dispatcher" in names


def test_analytics_summary_crew_has_tasks() -> None:
    m = build_crews_manifest()
    crew = next(c for c in m["crews"] if c["name"] == "analytics_summary")
    assert crew["implemented"] is True
    assert len(crew["tasks"]) >= 1


def test_all_registered_crews_are_implemented() -> None:
    m = build_crews_manifest()
    names = {c["name"] for c in m["crews"]}
    assert names == {
        "router",
        "analytics_summary",
        "analytics_dashboard",
    }
    for entry in m["crews"]:
        assert entry["implemented"] is True, entry["name"]


def test_write_manifests_produces_three_files(tmp_path: Path) -> None:
    tools = build_tools_manifest()
    agents = build_agents_manifest()
    crews = build_crews_manifest()
    write_manifests(tmp_path, tools=tools, agents=agents, crews=crews)
    assert (tmp_path / TOOLS_FILE).exists()
    assert (tmp_path / AGENTS_FILE).exists()
    assert (tmp_path / CREWS_FILE).exists()


def test_cli_check_detects_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_dir = tmp_path / "manifest"
    manifest_dir.mkdir()
    write_manifests(
        manifest_dir,
        tools=build_tools_manifest(),
        agents=build_agents_manifest(),
        crews=build_crews_manifest(),
    )
    tools_path = manifest_dir / TOOLS_FILE
    tools_path.write_text(tools_path.read_text() + "\n# drift\n", encoding="utf-8")
    monkeypatch.setattr(
        "solomon.manifest.cli.DEFAULT_OUT_DIR",
        manifest_dir,
    )
    assert cli_main(["--check"]) == 1

