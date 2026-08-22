import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from max_chat_link_finder.finder import extract_max_links, load_source, read_text_file


class ExtractLinksTests(unittest.TestCase):
    def test_extracts_supported_links(self):
        text = "Канал https://max.ru/news и чат max://join/abc"
        self.assertEqual(extract_max_links(text), ["https://max.ru/news", "max://join/abc"])

    def test_removes_punctuation_and_duplicates(self):
        text = "(https://max.ru/chat), HTTPS://MAX.RU/CHAT!"
        self.assertEqual(extract_max_links(text), ["https://max.ru/chat"])

    def test_ignores_similar_domains(self):
        self.assertEqual(extract_max_links("https://notmax.ru/a https://max.ru.example/a"), [])


class SourceTests(unittest.TestCase):
    def test_reads_windows_1251_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "links.txt"
            path.write_bytes("Привет https://max.ru/test".encode("cp1251"))
            self.assertIn("Привет", read_text_file(path))

    def test_plain_text_is_unchanged(self):
        self.assertEqual(load_source("some text"), "some text")

    def test_long_text_is_not_treated_as_path(self):
        text = "x" * 10_000
        self.assertEqual(load_source(text), text)

    @patch("max_chat_link_finder.finder.fetch_page", return_value="page")
    def test_url_is_downloaded(self, fetch_page):
        self.assertEqual(load_source(" https://example.org/a "), "page")
        fetch_page.assert_called_once_with("https://example.org/a")


if __name__ == "__main__":
    unittest.main()
