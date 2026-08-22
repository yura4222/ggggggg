"""Atomic JSON/CSV/SQLite report output."""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Invitation:
    chat_name: str
    url: str
    found_at: str

    @classmethod
    def create(cls, chat_name: str, url: str) -> "Invitation":
        return cls(chat_name, url, datetime.now(timezone.utc).isoformat())


def save_reports(folder: str | Path, invitations: list[Invitation]) -> dict[str, Path]:
    target = Path(folder).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    paths = {suffix: target / f"max_invites_{stamp}.{suffix}" for suffix in ("json", "csv", "sqlite")}
    # A virtualized Links pane may render the same card more than once while it
    # scrolls. Keep one row per chat+URL in every output format.
    unique: list[Invitation] = []
    identities: set[tuple[str, str]] = set()
    for item in invitations:
        identity = (item.chat_name.casefold(), item.url.casefold())
        if identity not in identities:
            identities.add(identity)
            unique.append(item)
    paths["json"].write_text(json.dumps([asdict(item) for item in unique], ensure_ascii=False, indent=2), encoding="utf-8")
    with paths["csv"].open("w", newline="", encoding="utf-8-sig") as stream:
        # Russian Excel uses semicolon as the list separator. Comma-separated
        # output was displayed as one cell instead of three columns.
        writer = csv.DictWriter(stream, fieldnames=["chat_name", "url", "found_at"], delimiter=";")
        writer.writeheader()
        writer.writerows(asdict(item) for item in unique)
    # sqlite3.Connection.__exit__ commits or rolls back the transaction, but it
    # does not close the connection.  An explicit close is required on Windows,
    # where an open SQLite handle prevents report folders from being removed.
    database = sqlite3.connect(paths["sqlite"])
    try:
        with database:
            database.execute("CREATE TABLE invitations (chat_name TEXT NOT NULL, url TEXT NOT NULL, found_at TEXT NOT NULL)")
            database.executemany("INSERT INTO invitations VALUES (?, ?, ?)", [(x.chat_name, x.url, x.found_at) for x in unique])
    finally:
        database.close()
    return paths
