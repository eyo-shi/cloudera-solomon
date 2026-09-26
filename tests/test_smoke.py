"""パッケージが import できることだけを確認するスモークテスト。"""
from __future__ import annotations


def test_import_gandalf() -> None:
    import gandalf

    assert gandalf.__version__


def test_import_subpackages() -> None:
    import gandalf.analytics  # noqa: F401
    import gandalf.api  # noqa: F401
    import gandalf.demo  # noqa: F401
    import gandalf.ingestion  # noqa: F401
    import gandalf.router  # noqa: F401
    import gandalf.semantic  # noqa: F401
    import gandalf.session  # noqa: F401
    import gandalf.tools  # noqa: F401
    import gandalf.transport  # noqa: F401
