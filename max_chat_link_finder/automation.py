"""Conservative Playwright automation for the official MAX web client."""

from __future__ import annotations

import random
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .finder import normalize_invite
from .storage import Invitation

MAX_URL = "https://web.max.ru/"


@dataclass(frozen=True)
class DelayRange:
    minimum: float
    maximum: float

    def wait(self, stop: threading.Event) -> None:
        stop.wait(random.uniform(self.minimum, self.maximum))


class MaxAutomation:
    """Own a persistent Chromium session and inspect confirmed group rows only."""

    def __init__(self, profile: Path, diagnostics: Path, log: Callable[[str], None]) -> None:
        self.profile, self.diagnostics, self.log = profile, diagnostics, log
        self.context = self.page = None
        self._playwright = None

    def open_for_login(self, diagnostic: bool = True) -> None:
        if getattr(sys, "frozen", False):
            bundled_browsers = Path(sys.executable).parent / "browser"
            if bundled_browsers.exists():
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled_browsers)
        from playwright.sync_api import sync_playwright

        self.profile.mkdir(parents=True, exist_ok=True)
        self.diagnostics.mkdir(parents=True, exist_ok=True)
        if self.context:
            self.page.bring_to_front()
            return
        self._playwright = sync_playwright().start()
        self.context = self._playwright.chromium.launch_persistent_context(
            str(self.profile), headless=False, viewport={"width": 1360, "height": 850}
        )
        if diagnostic:
            self.context.tracing.start(screenshots=True, snapshots=True, sources=True)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.goto(MAX_URL, wait_until="domcontentloaded")
        self.log("Открыт официальный web.max.ru. Выполните вход самостоятельно.")

    def _confirmed_group_rows(self):
        # Deliberately conservative: only explicit machine-readable group markers.
        rows = self.page.locator(
            '[data-chat-type="group"], [data-conversation-type="group"], '
            '[data-testid*="group-chat"], [role="listitem"]:has([data-testid="group-badge"])'
        )
        return [rows.nth(i) for i in range(rows.count())]

    def scan(self, stop: threading.Event, click_delay: DelayRange, chat_delay: DelayRange,
             progress: Callable[[int, int], None], found: Callable[[int], None]) -> list[Invitation]:
        if not self.page:
            raise RuntimeError("Сначала нажмите «Открыть MAX и войти»")
        rows = self._confirmed_group_rows()
        total, invitations, seen = len(rows), [], set()
        self.log(f"Явно подтверждённых групп: {total}. Личные и неизвестные чаты не открываются.")
        for index, row in enumerate(rows, 1):
            if stop.is_set():
                break
            try:
                name = (row.get_attribute("aria-label") or row.inner_text()).strip().splitlines()[0]
                row.click(); click_delay.wait(stop)
                header = self.page.locator(
                    '[data-testid="chat-header"] [data-testid*="avatar"], '
                    '[data-testid="chat-header-title"], header [aria-haspopup="dialog"]'
                ).first
                header.click(); click_delay.wait(stop)
                links_tab = self.page.get_by_role("tab", name="Ссылки", exact=True).or_(
                    self.page.get_by_role("tab", name="Links", exact=True)
                ).first
                links_tab.click(); click_delay.wait(stop)
                panel = self.page.locator('[role="tabpanel"]:visible, [data-testid="links-list"]:visible').first
                previous = -1
                for _ in range(60):
                    hrefs = panel.locator('a[href]').evaluate_all("els => els.map(e => e.href)")
                    for href in hrefs:
                        invite = normalize_invite(href)
                        if invite and invite.casefold() not in seen:
                            seen.add(invite.casefold()); invitations.append(Invitation.create(name, invite)); found(len(invitations))
                    height = panel.evaluate("el => el.scrollHeight")
                    panel.evaluate("el => el.scrollTop = el.scrollHeight")
                    if height == previous:
                        break
                    previous = height; click_delay.wait(stop)
                self.page.keyboard.press("Escape")
            except Exception as error:
                self._capture_error(index, error)
            progress(index, total)
            chat_delay.wait(stop)
        return invitations

    def _capture_error(self, index: int, error: Exception) -> None:
        self.log(f"Ошибка в группе {index}: {error}")
        if self.page:
            self.page.screenshot(path=str(self.diagnostics / f"error_group_{index}_{int(time.time())}.png"), full_page=True)

    def close(self) -> None:
        if self.context:
            try:
                self.context.tracing.stop(path=str(self.diagnostics / f"trace_{int(time.time())}.zip"))
            finally:
                self.context.close()
        if self._playwright:
            self._playwright.stop()
        self.context = self.page = self._playwright = None
