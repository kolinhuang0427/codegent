"""ANSI terminal color helpers."""

from __future__ import annotations

import os
import sys


class ANSI:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    BRIGHT_BLACK = "\033[90m"


ROLE_COLORS = {
    "origin": ANSI.GREEN,
    "heir": ANSI.CYAN,
    "co-author": ANSI.MAGENTA,
    "renamed": ANSI.YELLOW,
    "descendant": ANSI.WHITE,
}


def supports_color(no_color: bool = False) -> bool:
    if no_color:
        return False
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("CLICOLOR") == "0":
        return False
    if os.environ.get("CLICOLOR_FORCE"):
        return True
    return sys.stdout.isatty()


def paint(text: str, color: str, enabled: bool = True, *, bold: bool = False) -> str:
    if not enabled:
        return text
    prefix = color
    if bold:
        prefix = ANSI.BOLD + prefix
    return f"{prefix}{text}{ANSI.RESET}"


def role(text: str, enabled: bool = True) -> str:
    return paint(text, ROLE_COLORS.get(text.lower(), ANSI.WHITE), enabled, bold=True)


def muted(text: str, enabled: bool = True) -> str:
    return paint(text, ANSI.BRIGHT_BLACK, enabled)


def heading(text: str, enabled: bool = True) -> str:
    return paint(text, ANSI.CYAN, enabled, bold=True)


def danger(text: str, enabled: bool = True) -> str:
    return paint(text, ANSI.RED, enabled, bold=True)
