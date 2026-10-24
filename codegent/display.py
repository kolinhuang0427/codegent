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


# Unicode 17 Emoji_Modifier_Base; https://www.unicode.org/Public/17.0.0/ucd/emoji/emoji-data.txt
_MODIFIER_BASES = (
    (0x261D, 0x261D), (0x26F9, 0x26F9), (0x270A, 0x270D), (0x1F385, 0x1F385),
    (0x1F3C2, 0x1F3C4), (0x1F3C7, 0x1F3C7), (0x1F3CA, 0x1F3CC), (0x1F442, 0x1F443),
    (0x1F446, 0x1F450), (0x1F466, 0x1F478), (0x1F47C, 0x1F47C), (0x1F481, 0x1F483),
    (0x1F485, 0x1F487), (0x1F48F, 0x1F48F), (0x1F491, 0x1F491), (0x1F4AA, 0x1F4AA),
    (0x1F574, 0x1F575), (0x1F57A, 0x1F57A), (0x1F590, 0x1F590), (0x1F595, 0x1F596),
    (0x1F645, 0x1F647), (0x1F64B, 0x1F64F), (0x1F6A3, 0x1F6A3), (0x1F6B4, 0x1F6B6),
    (0x1F6C0, 0x1F6C0), (0x1F6CC, 0x1F6CC), (0x1F90C, 0x1F90C), (0x1F90F, 0x1F90F),
    (0x1F918, 0x1F91F), (0x1F926, 0x1F926), (0x1F930, 0x1F939), (0x1F93C, 0x1F93E),
    (0x1F977, 0x1F977), (0x1F9B5, 0x1F9B6), (0x1F9B8, 0x1F9B9), (0x1F9BB, 0x1F9BB),
    (0x1F9CD, 0x1F9CF), (0x1F9D1, 0x1F9DD), (0x1FAC3, 0x1FAC5), (0x1FAF0, 0x1FAF8),
)


def _modifier_base(cluster: str) -> bool:
    base = cluster.rstrip("\ufe0f")[-1:]
    return bool(base) and any(start <= ord(base) <= end for start, end in _MODIFIER_BASES)


def _clusters(text: str):
    """Keep common terminal emoji/combining sequences intact without dependencies."""
    cluster = ""
    for char in text:
        regional_pair = (len(cluster) == 1 and 0x1F1E6 <= ord(cluster) <= 0x1F1FF
                         and 0x1F1E6 <= ord(char) <= 0x1F1FF)
        extend = (unicodedata.category(char) in {"Mn", "Me"} or char == "\u200d"
                  or (0x1F3FB <= ord(char) <= 0x1F3FF and _modifier_base(cluster)) or regional_pair
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
