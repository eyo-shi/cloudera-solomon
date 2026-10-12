"""Graph Cypher チャットリンクのエンコード。"""

from __future__ import annotations

from urllib.parse import parse_qs, unquote_plus

from solomon.graph.chat_links import graph_cypher_markdown_link


def test_graph_cypher_markdown_link_encodes_params() -> None:
    cypher = "MATCH (v:VbMachine {id: $vb_id}) RETURN v"
    md = graph_cypher_markdown_link(cypher, {"vb_id": "166890"})
    assert md.startswith("[参照 Cypher][solomon-graph-cypher-")
    ref_line = [ln for ln in md.splitlines() if ln.startswith("[solomon-graph-cypher-")][0]
    assert "solomon://graph-cypher?" in ref_line
    query = ref_line.split("?", 1)[1]
    parsed = parse_qs(query)
    assert unquote_plus(parsed["cypher"][0]) == cypher
    assert '"vb_id":"166890"' in unquote_plus(parsed["params"][0])
