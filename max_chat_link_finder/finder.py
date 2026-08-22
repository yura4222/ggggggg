"""Validation helpers for MAX invitation URLs."""

from __future__ import annotations

import re

_INVITE_RE = re.compile(r"^https://max\.ru/join/[A-Za-z0-9_-]+/?(?:\?[^\s#]*)?$", re.IGNORECASE)


def normalize_invite(url: str) -> str | None:
    """Return a canonical MAX invitation URL, rejecting every other URL kind."""
    value = url.strip()
    if not _INVITE_RE.fullmatch(value):
        return None
    value = value.split("?", 1)[0].rstrip("/")
    return "https://max.ru/join/" + value.rsplit("/", 1)[-1]


def extract_max_links(text: str) -> list[str]:
    """Compatibility helper used only for validating browser-extracted href values."""
    result: list[str] = []
    seen: set[str] = set()
    for candidate in re.findall(r"https://[^\s<>\"']+", text, re.IGNORECASE):
        invite = normalize_invite(candidate.rstrip(".,;:!?)]}>»”’"))
        if invite and invite.casefold() not in seen:
            seen.add(invite.casefold())
            result.append(invite)
    return result
