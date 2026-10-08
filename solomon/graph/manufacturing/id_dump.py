"""J5 ID ファイル (メインID / 出検ID) の hex ダンプパース。

S10400 形式: ``0000(H),09,12,...`` — 16 バイト/行、1 バイト = 2 桁 hex。
"""
from __future__ import annotations

import re
from typing import Iterator

_HEX_DUMP_LINE_RE = re.compile(
    r"^([0-9A-Fa-f]{4})\(H\),([0-9A-Fa-f]{2}(?:,[0-9A-Fa-f]{2})*)$"
)


def parse_hex_dump_lines(text: str) -> dict[int, int]:
    """hex ダンプ行から アドレス → バイト値 の dict を構築する。"""
    memory: dict[int, int] = {}
    for line in text.splitlines():
        match = _HEX_DUMP_LINE_RE.match(line.strip())
        if not match:
            continue
        base = int(match.group(1), 16)
        for offset, token in enumerate(match.group(2).split(",")):
            memory[base + offset] = int(token, 16)
    return memory


def iter_hex_dump_lines(text: str) -> Iterator[tuple[int, list[int]]]:
    """(ベースアドレス, 16バイト列) を順に返す。"""
    for line in text.splitlines():
        match = _HEX_DUMP_LINE_RE.match(line.strip())
        if not match:
            continue
        base = int(match.group(1), 16)
        values = [int(token, 16) for token in match.group(2).split(",")]
        yield base, values


def read_bytes_at(memory: dict[int, int], start: int, length: int) -> list[int]:
    """連続アドレスのバイト列を返す (欠損は 0x00)。"""
    return [memory.get(start + index, 0) for index in range(length)]
