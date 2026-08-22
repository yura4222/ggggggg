"""Core link extraction and source-loading functions."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024
_LINK_RE = re.compile(
    r"(?<![\w@])(?:https?://(?:www\.)?max\.ru(?=/)|max://)[^\s<>\"']+",
    re.IGNORECASE,
)
_TRAILING = ".,;:!?)]}>»”’"


def extract_max_links(text: str) -> list[str]:
    """Return unique MAX links in their first-seen order."""
    found: list[str] = []
    seen: set[str] = set()
    for match in _LINK_RE.finditer(text):
        link = match.group(0).rstrip(_TRAILING)
        key = link.casefold()
        if link and key not in seen:
            seen.add(key)
            found.append(link)
    return found


def read_text_file(path: str | Path) -> str:
    """Read a reasonably sized text file using common Windows encodings."""
    file_path = Path(path)
    if file_path.stat().st_size > MAX_DOWNLOAD_BYTES:
        raise ValueError("Файл больше 5 МБ")
    data = file_path.read_bytes()
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Не удалось определить кодировку текстового файла")


def fetch_page(url: str, timeout: float = 10) -> str:
    """Download a small HTTP(S) page and decode its body."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Введите корректный адрес http:// или https://")
    request = Request(url, headers={"User-Agent": "MAX-Chat-Link-Finder/1.0"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        data = response.read(MAX_DOWNLOAD_BYTES + 1)
        if len(data) > MAX_DOWNLOAD_BYTES:
            raise ValueError("Веб-страница больше 5 МБ")
        charset = response.headers.get_content_charset() or "utf-8"
    return data.decode(charset, errors="replace")


def load_source(value: str) -> str:
    """Load a URL or local file, or return the supplied text unchanged."""
    stripped = value.strip()
    if stripped.lower().startswith(("http://", "https://")):
        return fetch_page(stripped)
    if stripped and "\n" not in stripped and "\r" not in stripped:
        try:
            path = Path(stripped)
            if path.is_file():
                return read_text_file(path)
        except OSError:
            # Long pasted text is a source value, not a usable file name.
            pass
    return value
