"""demo.loader unit tests (no external services)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURE_DOMAIN = REPO / "tests" / "fixtures" / "demo_loader"
MFG = REPO / "demo" / "mfg_quality"


@pytest.fixture
def neutral_domain(tmp_path: Path) -> Path:
    domain = tmp_path / "demo_domain"
    sem = domain / "semantic" / "models"
    sem.mkdir(parents=True)
    src = FIXTURE_DOMAIN / "semantic" / "models" / "demo_neutral.yaml"
    (sem / "demo_neutral.yaml").write_text(src.read_text(encoding="utf-8"))
    (domain / "output").mkdir()
    return domain


def test_trino_type_mapping() -> None:
    from demo.loader.trino_types import create_table_ddl, trino_type
    from solomon.semantic.models import OssieField

    assert trino_type(OssieField(name="x", datatype="Integer")) == "bigint"
    assert trino_type(OssieField(name="d", datatype="Decimal")) == "decimal(18,4)"
    ddl = create_table_ddl(
        "iceberg.demo_schema.entities",
        [OssieField(name="entity_id", datatype="String")],
    )
    assert "varchar" in ddl
    assert "iceberg.demo_schema.entities" in ddl


def test_puppygraph_schema_from_ossie(neutral_domain: Path) -> None:
    from demo.loader.ossie_domain import load_domain
    from demo.loader.puppygraph_schema import build_puppygraph_schema

    domain = load_domain(neutral_domain, validate=False)
    schema = build_puppygraph_schema(domain, catalog_type="hms")
    assert len(schema["vertices"]) == 1
    assert schema["vertices"][0]["label"] == "Entity"
    assert len(schema["edges"]) == 1
    edge = schema["edges"][0]
    assert edge["fromLabel"] == "Entity"
    assert edge["toLabel"] == "Entity"
    assert edge["fromId"]["fields"] == ["from_id"]


def test_docs_mapping_from_ossie(neutral_domain: Path) -> None:
    from demo.loader.ossie_domain import load_domain
    from demo.loader.search_load import _doc_index_def
    from solomon.opensearch.docs_mapping import build_docs_mapping

    domain = load_domain(neutral_domain, validate=False)
    doc_def = _doc_index_def(domain)
    body = build_docs_mapping(doc_def, analyzer="cjk", embedding_dim=1024)
    props = body["mappings"]["properties"]
    assert "text" in props
    assert "embedding" in props


def test_dry_run_no_network(neutral_domain: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "demo.loader",
            "--domain-dir",
            str(neutral_domain),
            "--target",
            "all",
            "--dry-run",
        ],
        cwd=REPO,
        env={**__import__("os").environ, "PYTHONPATH": str(REPO)},
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "POST" in proc.stdout
    assert "Entity" in proc.stdout


@pytest.mark.skipif(not MFG.is_dir(), reason="demo/mfg_quality missing")
def test_mfg_semantic_validates() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "solomon.semantic",
            "validate",
            "--root",
            str(MFG / "semantic"),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(not MFG.is_dir(), reason="demo/mfg_quality missing")
def test_mfg_puppygraph_schema_has_consumed_by() -> None:
    from demo.loader.ossie_domain import load_domain
    from demo.loader.puppygraph_schema import build_puppygraph_schema

    domain = load_domain(MFG, validate=True)
    schema = build_puppygraph_schema(domain)
    labels = {e["label"] for e in schema["edges"]}
    assert "CONSUMED_BY" in labels


# ---------------- Iceberg 方式 B (INSERT) ---------------- #


def test_sql_literal_types() -> None:
    import datetime as dt

    import numpy as np
    import pandas as pd

    from demo.loader.iceberg_load import sql_literal

    assert sql_literal(dt.date(2026, 5, 14), "date") == "DATE '2026-05-14'"
    assert (
        sql_literal(pd.Timestamp("2026-05-14 08:00:00"), "timestamp(6)")
        == "TIMESTAMP '2026-05-14 08:00:00.000000'"
    )
    assert sql_literal(pd.NaT, "timestamp(6)") == "NULL"
    assert sql_literal(float("nan"), "varchar") == "NULL"
    assert sql_literal(None, "date") == "NULL"
    assert sql_literal("O'Neil", "varchar") == "'O''Neil'"
    assert sql_literal(np.array(["a", "b"], dtype=object), "array(varchar)") == "ARRAY['a', 'b']"
    assert sql_literal([], "array(varchar)") == "CAST(ARRAY[] AS array(varchar))"
    assert sql_literal(1e-05, "decimal(18,4)") == "0.00001"
    assert sql_literal(1200, "decimal(18,4)") == "1200"
    assert sql_literal(3.0, "bigint") == "3"
    assert sql_literal(True, "boolean") == "true"


def test_insert_statements_split_by_bytes() -> None:
    from demo.loader.iceberg_load import insert_statements
    from solomon.semantic.models import OssieField

    fields = [OssieField(name="id", datatype="String"), OssieField(name="n", datatype="Integer")]
    rows = [(f"id-{i:04d}", i) for i in range(200)]
    stmts = insert_statements("iceberg.s.t", fields, rows, max_bytes=2048)
    assert len(stmts) > 1
    assert all(len(s.encode()) <= 2048 for s in stmts)
    assert sum(s.count("('id-") for s in stmts) == 200
    assert stmts[0].startswith("INSERT INTO iceberg.s.t (id, n) VALUES ('id-0000', 0)")


def test_select_method_defaults_to_b_without_s3_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    from demo.loader.iceberg_load import select_method

    monkeypatch.delenv("DEMO_S3_PREFIX", raising=False)
    assert select_method(None, lambda _sql: [("hive",), ("iceberg",)]) == "b"
    monkeypatch.setenv("DEMO_S3_PREFIX", "s3://bucket/demo")
    assert select_method(None, lambda _sql: [("hive",), ("iceberg",)]) == "a"
    assert select_method(None, lambda _sql: [("iceberg",)]) == "b"
    assert select_method("b", lambda _sql: [("hive",)]) == "b"


def _domain_with_parquet(neutral_domain: Path) -> Path:
    import pandas as pd

    tables = neutral_domain / "output" / "tables"
    tables.mkdir(parents=True)
    pd.DataFrame({"entity_id": ["E1", "E2"], "name": ["a", None]}).to_parquet(
        tables / "entities.parquet"
    )
    pd.DataFrame({"link_id": ["L1"], "from_id": ["E1"], "to_id": ["E2"]}).to_parquet(
        tables / "links.parquet"
    )
    return neutral_domain


def test_load_iceberg_method_b_creates_schema_and_inserts(
    neutral_domain: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from demo.loader.iceberg_load import load_iceberg
    from demo.loader.ossie_domain import load_domain

    monkeypatch.delenv("DEMO_S3_PREFIX", raising=False)
    domain = load_domain(_domain_with_parquet(neutral_domain), validate=False)
    executed: list[str] = []

    def query_fn(sql: str):
        if sql == "SHOW CATALOGS":
            return [("hive",), ("iceberg",)]
        if "entities" in sql:
            return [(5,)]  # 途中失敗の残り → 作り直す
        raise RuntimeError("Table does not exist")

    def upload_fn(*_a):
        raise AssertionError("method B must not upload to S3")

    out = load_iceberg(
        domain,
        dry_run=False,
        recreate=False,
        method=None,
        execute_fn=executed.append,
        query_fn=query_fn,
        upload_fn=upload_fn,
    )
    assert out["method"] == "b"
    assert out["tables"] == {"entities": 2, "links": 1}
    assert executed[0] == "CREATE SCHEMA IF NOT EXISTS iceberg.demo_schema"
    assert "DROP TABLE IF EXISTS iceberg.demo_schema.entities" in executed
    assert "DROP TABLE IF EXISTS iceberg.demo_schema.links" not in executed
    inserts = [s for s in executed if s.startswith("INSERT INTO iceberg.demo_schema.entities")]
    assert inserts == [
        "INSERT INTO iceberg.demo_schema.entities (entity_id, name) VALUES ('E1', 'a'), ('E2', NULL)"
    ]


def test_trino_execute_fn_waits_for_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest import mock

    from demo.loader import trino_runtime

    conn = mock.MagicMock()
    monkeypatch.setattr(trino_runtime, "trino_connection_for_user", lambda _ctx: conn)
    execute_fn, _query_fn = trino_runtime.make_trino_callbacks(
        trino_runtime.UserContext(user_name="loader")
    )
    execute_fn("INSERT INTO t VALUES (1)")
    cur = conn.cursor.return_value
    cur.execute.assert_called_once_with("INSERT INTO t VALUES (1)")
    cur.fetchall.assert_called_once()
    cur.close.assert_called_once()


def test_loader_user_context_without_jwt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from demo.loader.trino_runtime import loader_user_context

    monkeypatch.setenv("SOLOMON_CML_JWT_PATH", str(tmp_path / "missing"))
    monkeypatch.setenv("HADOOP_USER_NAME", "loader-user")
    ctx = loader_user_context()
    assert ctx.user_name == "loader-user"
    assert ctx.knox_jwt is None


# ---------------- PuppyGraph (Trino カタログ, 1.15 形式) ---------------- #


def test_puppygraph_trino_schema(neutral_domain: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from demo.loader.ossie_domain import load_domain
    from demo.loader.puppygraph_schema import build_puppygraph_schema

    monkeypatch.delenv("PUPPYGRAPH_TRINO_CATALOG", raising=False)
    domain = load_domain(neutral_domain, validate=False)
    schema = build_puppygraph_schema(domain, catalog_type="trino")
    assert set(schema) == {"catalog", "node", "edge"}
    cat = schema["catalog"][0]
    assert cat["type"] == "trino"
    assert cat["jdbc"]["jdbcUri"] == "${PUPPYGRAPH_TRINO_JDBC_URI}"
    node = schema["node"][0]
    src = node["dataSourceGroup"]["externalDataSource"]
    assert (src["catalog"], src["schema"], src["table"]) == (cat["name"], "demo_schema", "entities")
    assert node["id"] == [{"name": "entity_id", "type": "STRING"}]
    assert node["attribute"] == [{"name": "name", "type": "STRING"}]
    edge = schema["edge"][0]
    assert (edge["fromNodeLabel"], edge["toNodeLabel"]) == ("Entity", "Entity")
    assert edge["id"] == [{"name": "link_id", "type": "STRING"}]
    assert edge["fromKey"] == [{"name": "from_id", "type": "STRING"}]
    mapped = [m["sourceFieldName"] for m in edge["dataSourceGroup"]["externalDataSource"]["mappedField"]]
    assert mapped == ["link_id", "from_id", "to_id"]


def test_resolve_schema_fills_from_trino_env(neutral_domain: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from demo.loader.graph_load import resolve_schema, trino_jdbc_defaults
    from demo.loader.ossie_domain import load_domain
    from demo.loader.puppygraph_schema import build_puppygraph_schema

    for key in ("PUPPYGRAPH_TRINO_JDBC_URI", "PUPPYGRAPH_TRINO_USER", "PUPPYGRAPH_TRINO_PASSWORD",
                "TRINO_HOST", "SOLOMON_TRINO_HOST", "TRINO_ENDPOINT", "SOLOMON_TRINO_ENDPOINT",
                "SOLOMON_TRINO_URL", "TRINO_PORT", "TRINO_SCHEME", "TRINO_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TRINO_URL", "https://trino.example:443")
    monkeypatch.setenv("TRINO_USER", "svc")
    domain = load_domain(neutral_domain, validate=False)
    schema = build_puppygraph_schema(domain, catalog_type="trino")
    body = resolve_schema(schema, trino_jdbc_defaults("iceberg"))
    jdbc = body["catalog"][0]["jdbc"]
    assert jdbc == {"username": "svc", "jdbcUri": "jdbc:trino://trino.example:443/iceberg?SSL=true"}

    monkeypatch.setenv("PUPPYGRAPH_TRINO_PASSWORD", "pw")
    monkeypatch.setenv("PUPPYGRAPH_TRINO_JDBC_URI", "jdbc:trino://other.example:443/iceberg?SSL=true")
    jdbc = resolve_schema(schema, trino_jdbc_defaults("iceberg"))["catalog"][0]["jdbc"]
    assert jdbc["password"] == "pw"
    assert jdbc["jdbcUri"].startswith("jdbc:trino://other.example")


def test_resolve_schema_rejects_unset_variables(neutral_domain: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from demo.loader.graph_load import GraphLoadError, resolve_schema
    from demo.loader.ossie_domain import load_domain
    from demo.loader.puppygraph_schema import build_puppygraph_schema

    monkeypatch.delenv("PUPPYGRAPH_TRINO_JDBC_URI", raising=False)
    monkeypatch.delenv("PUPPYGRAPH_TRINO_USER", raising=False)
    domain = load_domain(neutral_domain, validate=False)
    schema = build_puppygraph_schema(domain, catalog_type="trino")
    with pytest.raises(GraphLoadError, match="PUPPYGRAPH_TRINO_JDBC_URI"):
        resolve_schema(schema, {})


def test_load_graph_posts_trino_schema(neutral_domain: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from demo.loader import graph_load
    from demo.loader.ossie_domain import load_domain

    monkeypatch.delenv("DEMO_PUPPYGRAPH_CATALOG", raising=False)
    monkeypatch.setenv("PUPPYGRAPH_TRINO_JDBC_URI", "jdbc:trino://trino.example:443/iceberg?SSL=true")
    monkeypatch.setenv("PUPPYGRAPH_TRINO_USER", "svc")
    monkeypatch.setenv("PUPPYGRAPH_HTTP_URL", "http://pg.example:8081")
    monkeypatch.setattr(graph_load, "_verify_bolt", lambda *_a: None)
    posted: list[tuple[str, dict]] = []
    domain = load_domain(neutral_domain, validate=False)
    out = graph_load.load_graph(domain, dry_run=False, post_fn=lambda url, body: posted.append((url, body)))
    assert out == {"vertices": 1, "edges": 1}
    url, body = posted[0]
    assert url == "http://pg.example:8081/schema"
    assert body["catalog"][0]["jdbc"]["username"] == "svc"
    assert "${" not in __import__("json").dumps(body)


def test_default_catalog_type(monkeypatch: pytest.MonkeyPatch) -> None:
    from demo.loader.graph_load import default_catalog_type

    for key in ("DEMO_PUPPYGRAPH_CATALOG", "PUPPYGRAPH_TRINO_JDBC_URI", "HIVE_METASTORE_URI",
                "ICEBERG_REST_URI"):
        monkeypatch.delenv(key, raising=False)
    assert default_catalog_type() == "trino"
    monkeypatch.setenv("HIVE_METASTORE_URI", "thrift://hms.example:9083")
    assert default_catalog_type() == "hms"
    monkeypatch.setenv("PUPPYGRAPH_TRINO_JDBC_URI", "jdbc:trino://trino.example:443/iceberg")
    assert default_catalog_type() == "trino"
    monkeypatch.setenv("DEMO_PUPPYGRAPH_CATALOG", "rest")
    assert default_catalog_type() == "rest"


def test_load_graph_writes_resolved_schema_for_ui(
    neutral_domain: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import json
    import stat

    from demo.loader import graph_load
    from demo.loader.ossie_domain import load_domain

    monkeypatch.delenv("DEMO_PUPPYGRAPH_CATALOG", raising=False)
    monkeypatch.setenv("PUPPYGRAPH_TRINO_JDBC_URI", "jdbc:trino://trino.example:443/iceberg?SSL=true")
    monkeypatch.setenv("PUPPYGRAPH_TRINO_USER", "svc")
    monkeypatch.setenv("PUPPYGRAPH_TRINO_PASSWORD", "pw")

    def no_post(*_a):
        raise AssertionError("must not POST when schema_out is given")

    out = tmp_path / "schema_upload.json"
    domain = load_domain(neutral_domain, validate=False)
    graph_load.load_graph(domain, dry_run=False, post_fn=no_post, schema_out=out)
    body = json.loads(out.read_text())
    assert body["catalog"][0]["jdbc"] == {
        "username": "svc",
        "password": "pw",
        "jdbcUri": "jdbc:trino://trino.example:443/iceberg?SSL=true",
    }
    assert stat.S_IMODE(out.stat().st_mode) == 0o600


def test_post_schema_reports_unreachable_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from demo.loader import graph_load

    def boom(*_a, **_k):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx, "post", boom)
    monkeypatch.setenv("PUPPYGRAPH_HTTP_URL", "http://pg.example:8081")
    with pytest.raises(graph_load.GraphLoadError, match="--graph-schema-out"):
        graph_load.post_schema({"node": []}, dry_run=False)
