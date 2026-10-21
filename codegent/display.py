"""Keep repository-controlled strings inert in terminal output."""
from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
from functools import wraps
import unicodedata
from typing import Any


def escape_text(text: str) -> str:
    pieces: list[str] = []
    bidi_controls = {"LRE", "RLE", "PDF", "LRO", "RLO", "LRI", "RLI", "FSI", "PDI"}
    for char in text:
        if unicodedata.category(char) in {"Cc", "Cs"} or unicodedata.bidirectional(char) in bidi_controls:
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
        return replace(value, **{field.name: display_value(getattr(value, field.name)) for field in fields(value)})
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
