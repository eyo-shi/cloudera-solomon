"""パッケージが import できることだけを確認するスモークテスト。"""
from __future__ import annotations


def test_import_solomon() -> None:
    import solomon

    assert solomon.__version__


def test_import_subpackages() -> None:
    import solomon.analytics  # noqa: F401
    import solomon.api  # noqa: F401
    import solomon.ingestion  # noqa: F401
    import solomon.router  # noqa: F401
    import solomon.semantic  # noqa: F401
    import solomon.session  # noqa: F401
    import solomon.tools  # noqa: F401
    import solomon.transport  # noqa: F401
