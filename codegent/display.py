"""Keep repository-controlled strings inert in terminal output."""
from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
from functools import wraps
from contextvars import ContextVar
import unicodedata
import re
from typing import Any


def character_width(char: str) -> int:
    if unicodedata.combining(char) or unicodedata.category(char) in {"Mn", "Me", "Cf"}:
        return 0
    return 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1


def _emoji(char: str) -> bool:
    return 0x1F000 <= ord(char) <= 0x1FAFF or 0x2600 <= ord(char) <= 0x27BF


def _clusters(text: str):
    """Keep common terminal emoji/combining sequences intact without dependencies."""
    cluster = ""
    for char in text:
        regional_pair = (len(cluster) == 1 and 0x1F1E6 <= ord(cluster) <= 0x1F1FF
                         and 0x1F1E6 <= ord(char) <= 0x1F1FF)
        extend = (unicodedata.category(char) in {"Mn", "Me"} or char == "\u200d"
                  or 0x1F3FB <= ord(char) <= 0x1F3FF or regional_pair
                  or (cluster.endswith("\u200d") and _emoji(char) and any(_emoji(c) for c in cluster)))
        if cluster and not extend:
            yield cluster
            cluster = ""
        cluster += char
    if cluster:
        yield cluster


def _cluster_width(cluster: str) -> int:
    if "\ufe0f" in cluster or "\u20e3" in cluster or (len(cluster) == 2 and all(0x1F1E6 <= ord(c) <= 0x1F1FF for c in cluster)):
        return 2
    return max((character_width(char) for char in cluster), default=0)


def display_width(text: str) -> int:
    plain = re.sub(r"\x1b\[[0-9;]*m", "", text)
    return sum(_cluster_width(cluster) for cluster in _clusters(plain))


def truncate_cells(text: str, limit: int) -> str:
    if display_width(text) <= limit:
        return text
    budget = max(0, limit - 3)
    result: list[str] = []
    used = 0
    for cluster in _clusters(text):
        width = _cluster_width(cluster)
        if used + width > budget:
            break
        result.append(cluster)
        used += width
    return "".join(result).rstrip() + "." * min(3, limit)


def escape_text(text: str) -> str:
    pieces: list[str] = []
    bidi_controls = {"LRE", "RLE", "PDF", "LRO", "RLO", "LRI", "RLI", "FSI", "PDI"}
    for char in text:
        if unicodedata.category(char) in {"Cc", "Cs"} or char in "\u200e\u200f\u061c" or unicodedata.bidirectional(char) in bidi_controls:
            escaped = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}.get(char)
            code = ord(char)
            pieces.append(escaped or (f"\\x{code:02x}" if code < 256 else f"\\u{code:04x}"))
        else:
            pieces.append(char)
    return "".join(pieces)


def display_value(value: Any) -> Any:
    if isinstance(value, str):
        return escape_text(value)
    if is_dataclass(value):
        return replace(value, **{field.name: ("\n".join(escape_text(line) for line in getattr(value, field.name).split("\n"))
                                             if field.name == "stat" and isinstance(getattr(value, field.name), str)
                                             else display_value(getattr(value, field.name))) for field in fields(value)})
    if isinstance(value, dict):
        return {key: display_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [display_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(display_value(item) for item in value)
    return value


def safe_display(renderer):
    @wraps(renderer)
    def wrapped(report, *args, **kwargs):
        return renderer(display_value(report), *args, **kwargs)
    return wrapped


def ascii_graphics(text: str) -> str:
    """Replace report drawing glyphs while retaining ordinary Unicode content."""
    replacements = {**dict.fromkeys("╭╮╰╯├└┬┴┤┼", "+"), "─": "-", "│": "|",
                    "▼": "v", "◆": "*", "◇": "o", "●": "*", "•": ".", "↷": ">"}
    return text.translate(str.maketrans(replacements))


ASCII_DRAWING = ContextVar("codegent_ascii_drawing", default=False)


def graphics(text: str) -> str:
    return ascii_graphics(text) if ASCII_DRAWING.get() else text
