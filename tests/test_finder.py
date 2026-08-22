import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from max_chat_link_finder.automation import DelayRange, classify_dialog
from max_chat_link_finder.finder import extract_max_links, normalize_invite
from max_chat_link_finder.storage import Invitation, save_reports


class InviteValidationTests(unittest.TestCase):
    def test_accepts_only_join_urls(self):
        self.assertEqual(normalize_invite("https://max.ru/join/Abc_-12?from=web"), "https://max.ru/join/Abc_-12")
        for url in ("https://max.ru/u/name", "https://t.me/a", "https://vk.me/a", "http://max.ru/join/x", "https://max.ru/join/"):
            self.assertIsNone(normalize_invite(url))

    def test_extracts_only_invites_and_deduplicates(self):
        text = "https://max.ru/join/one https://max.ru/u/a https://max.ru/join/one"
        self.assertEqual(extract_max_links(text), ["https://max.ru/join/one"])


class StorageTests(unittest.TestCase):
    def test_writes_equivalent_json_csv_and_sqlite(self):
        item = Invitation("Тестовая группа", "https://max.ru/join/token", "2026-01-01T00:00:00+00:00")
        with tempfile.TemporaryDirectory() as directory:
            paths = save_reports(directory, [item])
            self.assertEqual(json.loads(paths["json"].read_text(encoding="utf-8"))[0]["url"], item.url)
            with paths["csv"].open(encoding="utf-8-sig") as stream:
                self.assertEqual(next(csv.DictReader(stream))["chat_name"], item.chat_name)
            db = sqlite3.connect(paths["sqlite"])
            try:
                self.assertEqual(db.execute("SELECT url FROM invitations").fetchone()[0], item.url)
            finally:
                db.close()
            # Windows must be able to remove the report immediately; this also
            # guards against relying on implementation-specific garbage collection.
            paths["sqlite"].unlink()
            self.assertFalse(paths["sqlite"].exists())


class SafetyTests(unittest.TestCase):
    def test_accepts_group_from_react_model(self):
        accepted, reason = classify_dialog({"memoizedProps.chat.type": ["CHAT"]})
        self.assertTrue(accepted)
        self.assertIn("chat", reason)

    def test_rejects_direct_channel_system_and_unknown_rows(self):
        unsafe = (
            {"props.peerType": ["DIRECT"]},
            {"props.isChannel": ["true"], "props.type": ["CHAT"]},
            {"props.entityType": ["SYSTEM"]},
            {"dom.data-testid": ["chat-item"]},
        )
        for evidence in unsafe:
            with self.subTest(evidence=evidence):
                self.assertFalse(classify_dialog(evidence)[0])

    def test_negative_marker_wins_over_group_marker(self):
        accepted, _ = classify_dialog({"props.type": ["CHAT"], "props.isChannel": ["true"]})
        self.assertFalse(accepted)

    def test_delay_range_can_be_interrupted(self):
        import threading
        stop = threading.Event(); stop.set()
        DelayRange(10, 10).wait(stop)


if __name__ == "__main__": unittest.main()
