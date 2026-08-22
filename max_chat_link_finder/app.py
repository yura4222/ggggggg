"""Tkinter desktop interface."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .finder import extract_max_links, load_source, read_text_file


class FinderApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("MAX Chat Link Finder")
        self.geometry("780x600")
        self.minsize(620, 480)
        self._build_ui()

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=18)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="MAX Chat Link Finder", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(root, text="Вставьте текст, путь к файлу или адрес веб-страницы").pack(anchor="w", pady=(2, 12))

        self.source = tk.Text(root, height=11, wrap="word", font=("Segoe UI", 10))
        self.source.pack(fill="both", expand=True)
        actions = ttk.Frame(root)
        actions.pack(fill="x", pady=10)
        ttk.Button(actions, text="Открыть файл…", command=self.open_file).pack(side="left")
        ttk.Button(actions, text="Найти ссылки", command=self.find_links).pack(side="left", padx=8)
        ttk.Button(actions, text="Очистить", command=self.clear).pack(side="left")

        self.status = tk.StringVar(value="Готово к поиску")
        ttk.Label(root, textvariable=self.status).pack(anchor="w", pady=(4, 5))
        self.results = tk.Listbox(root, height=9, font=("Segoe UI", 10), selectmode="extended")
        self.results.pack(fill="both", expand=True)
        result_actions = ttk.Frame(root)
        result_actions.pack(fill="x", pady=(10, 0))
        ttk.Button(result_actions, text="Копировать всё", command=self.copy_all).pack(side="left")
        ttk.Button(result_actions, text="Сохранить…", command=self.save).pack(side="left", padx=8)

    def open_file(self) -> None:
        filename = filedialog.askopenfilename(filetypes=[("Текстовые файлы", "*.txt *.html *.htm *.md"), ("Все файлы", "*.*")])
        if not filename:
            return
        try:
            text = read_text_file(filename)
        except (OSError, ValueError) as error:
            messagebox.showerror("Не удалось открыть файл", str(error))
            return
        self.source.delete("1.0", "end")
        self.source.insert("1.0", text)
        self.status.set(f"Открыт файл: {Path(filename).name}")

    def find_links(self) -> None:
        value = self.source.get("1.0", "end-1c")
        try:
            links = extract_max_links(load_source(value))
        except (OSError, ValueError) as error:
            messagebox.showerror("Ошибка поиска", str(error))
            return
        self.results.delete(0, "end")
        for link in links:
            self.results.insert("end", link)
        self.status.set(f"Найдено ссылок: {len(links)}")

    def copy_all(self) -> None:
        links = self.results.get(0, "end")
        if links:
            self.clipboard_clear()
            self.clipboard_append("\n".join(links))
            self.status.set("Ссылки скопированы")

    def save(self) -> None:
        links = self.results.get(0, "end")
        if not links:
            return
        filename = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Текстовый файл", "*.txt")])
        if filename:
            Path(filename).write_text("\n".join(links) + "\n", encoding="utf-8")
            self.status.set("Результат сохранён")

    def clear(self) -> None:
        self.source.delete("1.0", "end")
        self.results.delete(0, "end")
        self.status.set("Готово к поиску")


def main() -> None:
    FinderApp().mainloop()
