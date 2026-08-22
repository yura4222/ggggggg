"""Desktop control panel for Playwright MAX automation."""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .automation import DelayRange, MaxAutomation
from .storage import save_reports

APP_HOME = Path.home() / ".max-chat-link-finder"


class FinderApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("MAX Chat Link Finder")
        self.geometry("920x700")
        self.minsize(780, 620)
        self.stop_event, self.commands, self.events = threading.Event(), queue.Queue(), queue.Queue()
        self.report_dir = tk.StringVar(value=str(Path.home() / "Documents" / "MAX Reports"))
        self.progress_text, self.found_text = tk.StringVar(value="Группы: 0 / 0"), tk.StringVar(value="Найдено приглашений: 0")
        self.click_min, self.click_max = tk.DoubleVar(value=0.8), tk.DoubleVar(value=1.8)
        self.chat_min, self.chat_max = tk.DoubleVar(value=2.0), tk.DoubleVar(value=4.0)
        self.diagnostic = tk.BooleanVar(value=True)
        self._build_ui()
        threading.Thread(target=self._automation_worker, daemon=True).start()
        self.after(100, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=20); root.pack(fill="both", expand=True)
        ttk.Label(root, text="MAX Chat Link Finder", font=("Segoe UI", 22, "bold")).pack(anchor="w")
        ttk.Label(root, text="Безопасная проверка приглашений через официальный веб-клиент", foreground="#555").pack(anchor="w", pady=(2, 16))
        buttons = ttk.Frame(root); buttons.pack(fill="x")
        self.open_button = ttk.Button(buttons, text="Открыть MAX и войти", command=lambda: self.commands.put(("open", self.diagnostic.get())))
        self.open_button.pack(side="left")
        self.start_button = ttk.Button(buttons, text="Запустить проверку", command=self._start); self.start_button.pack(side="left", padx=8)
        ttk.Button(buttons, text="Остановить", command=self._stop).pack(side="left")
        ttk.Button(buttons, text="Открыть результаты", command=self._open_results).pack(side="right")

        status = ttk.LabelFrame(root, text="Ход проверки", padding=12); status.pack(fill="x", pady=14)
        ttk.Label(status, textvariable=self.progress_text).pack(anchor="w")
        self.progress = ttk.Progressbar(status, mode="determinate"); self.progress.pack(fill="x", pady=6)
        ttk.Label(status, textvariable=self.found_text, font=("Segoe UI", 11, "bold")).pack(anchor="w")

        settings = ttk.LabelFrame(root, text="Настройки", padding=12); settings.pack(fill="x")
        folder = ttk.Frame(settings); folder.pack(fill="x", pady=(0, 10))
        ttk.Label(folder, text="Папка отчётов:").pack(side="left")
        ttk.Entry(folder, textvariable=self.report_dir).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(folder, text="Выбрать…", command=self._choose_folder).pack(side="left")
        delays = ttk.Frame(settings); delays.pack(fill="x")
        self._range(delays, "Случайная задержка кликов, сек.", self.click_min, self.click_max, 0)
        self._range(delays, "Пауза между чатами, сек.", self.chat_min, self.chat_max, 1)
        ttk.Checkbutton(settings, text="Диагностический режим (trace и скриншоты ошибок)", variable=self.diagnostic).pack(anchor="w", pady=(10, 0))

        journal = ttk.LabelFrame(root, text="Журнал", padding=8); journal.pack(fill="both", expand=True, pady=(14, 0))
        self.log_view = tk.Text(journal, state="disabled", height=12, wrap="word", font=("Consolas", 9))
        scroll = ttk.Scrollbar(journal, command=self.log_view.yview); self.log_view.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y"); self.log_view.pack(fill="both", expand=True)
        self._log("Готово. Откройте MAX и выполните вход вручную.")

    def _range(self, parent, label, minimum, maximum, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Spinbox(parent, from_=0.1, to=60, increment=0.1, textvariable=minimum, width=8).grid(row=row, column=1, padx=(14, 4))
        ttk.Label(parent, text="—").grid(row=row, column=2)
        ttk.Spinbox(parent, from_=0.1, to=60, increment=0.1, textvariable=maximum, width=8).grid(row=row, column=3, padx=4)

    def _start(self):
        try:
            values = (float(self.click_min.get()), float(self.click_max.get()), float(self.chat_min.get()), float(self.chat_max.get()))
            if min(values) < 0.1 or values[0] > values[1] or values[2] > values[3]:
                raise ValueError
        except (ValueError, tk.TclError):
            messagebox.showerror("Неверные настройки", "Проверьте диапазоны задержек."); return
        self.stop_event.clear(); self.start_button.configure(state="disabled")
        self.commands.put(("scan", *values, self.report_dir.get()))

    def _stop(self):
        self.stop_event.set(); self._log("Запрошена остановка…")

    def _automation_worker(self):
        automation = MaxAutomation(APP_HOME / "browser-profile", APP_HOME / "diagnostics", lambda x: self.events.put(("log", x)))
        while True:
            command = self.commands.get()
            try:
                if command[0] == "close": automation.close(); return
                if command[0] == "open": automation.open_for_login(command[1])
                elif command[0] == "scan":
                    _, cmin, cmax, gmin, gmax, folder = command
                    invites = automation.scan(self.stop_event, DelayRange(cmin, cmax), DelayRange(gmin, gmax),
                        lambda n, total: self.events.put(("progress", n, total)), lambda n: self.events.put(("found", n)))
                    paths = save_reports(folder, invites)
                    self.events.put(("done", len(invites), paths))
            except Exception as error:
                self.events.put(("error", str(error)))

    def _poll_events(self):
        while True:
            try: event = self.events.get_nowait()
            except queue.Empty: break
            if event[0] == "log": self._log(event[1])
            elif event[0] == "progress":
                _, current, total = event; self.progress.configure(maximum=max(total, 1), value=current); self.progress_text.set(f"Группы: {current} / {total}")
            elif event[0] == "found": self.found_text.set(f"Найдено приглашений: {event[1]}")
            elif event[0] == "done": self._log(f"Готово. Сохранено приглашений: {event[1]}"); self.start_button.configure(state="normal")
            elif event[0] == "error": self._log("Ошибка: " + event[1]); self.start_button.configure(state="normal"); messagebox.showerror("Ошибка", event[1])
        self.after(100, self._poll_events)

    def _log(self, message):
        self.log_view.configure(state="normal"); self.log_view.insert("end", message + "\n"); self.log_view.see("end"); self.log_view.configure(state="disabled")

    def _choose_folder(self):
        selected = filedialog.askdirectory(initialdir=self.report_dir.get())
        if selected: self.report_dir.set(selected)

    def _open_results(self):
        folder = Path(self.report_dir.get()); folder.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt": os.startfile(folder)  # type: ignore[attr-defined]
            else: subprocess.Popen(["xdg-open", str(folder)])
        except OSError as error: messagebox.showerror("Не удалось открыть папку", str(error))

    def _close(self):
        self.stop_event.set(); self.commands.put(("close",)); self.destroy()


def main() -> None:
    FinderApp().mainloop()
