"""Diagnostic inventory of the virtualized MAX 'All' chat list."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict
from pathlib import Path

from max_chat_link_finder.automation import MAX_URL, MaxAutomation


def main() -> None:
    root = Path.home() / ".max-chat-link-finder-diagnostic"
    automation = MaxAutomation(root / "browser-profile", root / "diagnostics", print)
    try:
        automation.open_for_login(diagnostic=True)
        input("Войдите в MAX, откройте раздел «Все» и нажмите Enter здесь...")
        snapshots = automation.snapshot_all_chats(threading.Event())
        output = Path.cwd() / "max_all_chats_snapshot.json"
        output.write_text(
            json.dumps([asdict(item) for item in snapshots], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Найдено строк: {len(snapshots)}")
        print(f"Снимок сохранён: {output}")
    finally:
        automation.close()


if __name__ == "__main__":
    main()
