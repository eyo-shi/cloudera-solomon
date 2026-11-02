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


def test_search_document_markdown_link_doc_id() -> None:
    md = search_document_markdown_link(
        "Memo",
        {"doc_id": "doc-1", "chunk_id": "ch-9", "index": "support_notes"},
    )
    assert md.startswith("[Memo](solomon://search-document?")
    assert "doc_id=doc-1" in md
    assert "chunk_id=ch-9" in md
    assert "object_key" not in md
