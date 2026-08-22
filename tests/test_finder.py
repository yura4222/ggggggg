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
                row = next(csv.DictReader(stream, delimiter=";"))
                self.assertEqual(row["chat_name"], item.chat_name)
                self.assertEqual(row["url"], item.url)
                self.assertEqual(row["found_at"], item.found_at)
            db = sqlite3.connect(paths["sqlite"])
            try:
                self.assertEqual(db.execute("SELECT url FROM invitations").fetchone()[0], item.url)
            finally:
                db.close()
            # Windows must be able to remove the report immediately; this also
            # guards against relying on implementation-specific garbage collection.
            paths["sqlite"].unlink()
            self.assertFalse(paths["sqlite"].exists())

    def test_deduplicates_same_chat_and_url(self):
        first = Invitation("Группа", "https://max.ru/join/token", "2026-01-01T00:00:00+00:00")
        duplicate = Invitation("ГРУППА", "https://max.ru/join/TOKEN", "2026-01-02T00:00:00+00:00")
        with tempfile.TemporaryDirectory() as directory:
            paths = save_reports(directory, [first, duplicate])
            self.assertEqual(len(json.loads(paths["json"].read_text(encoding="utf-8"))), 1)


class SafetyTests(unittest.TestCase):
    def test_accepts_group_from_react_model(self):
        accepted, reason = classify_dialog({"memoizedProps.chat.type": ["CHAT"]})
        self.assertTrue(accepted)
        self.assertIn("обычная", reason)

    def test_accepts_direct_and_unknown_chat_rows(self):
        self.assertTrue(classify_dialog({"props.peerType": ["DIRECT"]}, "Кира")[0])
        self.assertTrue(classify_dialog({"dom.data-testid": ["chat-item"]}, "Барахолка")[0])

    def test_channel_marker_wins_over_group_marker(self):
        accepted, _ = classify_dialog({"props.type": ["CHAT"], "props.isChannel": ["true"]})
        self.assertFalse(accepted)

    def test_official_max_title_is_rejected(self):
        self.assertFalse(classify_dialog({}, "MAX ✓")[0])
        self.assertFalse(classify_dialog({}, "Новости MAX")[0])

    def test_delay_range_can_be_interrupted(self):
        import threading
        stop = threading.Event(); stop.set()
        DelayRange(10, 10).wait(stop)


if __name__ == "__main__": unittest.main()

class CampaignSafetyTests(unittest.TestCase):
    def test_requires_explicit_scanned_recipients_and_limit(self):
        from max_safe_sender.campaign import Campaign, validate_campaign
        validate_campaign(Campaign(("Группа",), "Текст"), {"группа"})
        with self.assertRaises(ValueError):
            validate_campaign(Campaign(tuple(f"Чат {i}" for i in range(21)), "Текст"), {f"чат {i}" for i in range(21)})
        with self.assertRaises(ValueError):
            validate_campaign(Campaign(("Неизвестный",), "Текст"), {"группа"})
