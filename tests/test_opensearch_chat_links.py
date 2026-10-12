"""Chat 内 Search ドキュメントリンク。"""

from __future__ import annotations

from solomon.opensearch.chat_links import search_document_markdown_link


def test_search_document_markdown_link() -> None:
    md = search_document_markdown_link(
        "foo.txt",
        {
            "object_key": "j5_main_id/foo.txt",
            "format": "j5_main_id",
            "trace_id": "26G3V05354",
        },
    )
    assert md.startswith("[foo.txt](solomon://search-document?")
    assert "\n" not in md
    assert "object_key=j5_main_id%2Ffoo.txt" in md or "object_key=j5_main_id/foo.txt" in md


def test_search_document_markdown_link_no_key() -> None:
    assert search_document_markdown_link("x", {}) == "x"
