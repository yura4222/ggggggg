"""Playwright automation for the official MAX web client."""

from __future__ import annotations

import json
import os
import random
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .finder import normalize_invite
from .storage import Invitation

MAX_URL = "https://web.max.ru/"

# MAX uses virtualized lists and does not currently expose data-chat-type on its
# visible rows. We inspect DOM attributes *and* the row's React model, but still
# require positive group evidence before clicking anything.
DIALOG_ROW_SELECTOR = ", ".join((
    '[data-chat-type]', '[data-conversation-type]', '[data-dialog-type]',
    '[data-testid*="chat-item"]', '[data-testid*="dialog-item"]',
    'a[href*="/chat/"]', 'a[href*="/chats/"]', '[role="listitem"]',
    '[class*="ChatItem"]', '[class*="chatItem"]',
    '[class*="DialogItem"]', '[class*="dialogItem"]',
))

MODEL_EVIDENCE_SCRIPT = r"""
(element) => {
  const evidence = {};
  const inspectedNodes = [element, ...element.querySelectorAll('*')];
  const put = (key, value) => {
    if (value === null || value === undefined) return;
    const normalized = String(value).slice(0, 200);
    (evidence[key] ||= []).push(normalized);
  };
  for (const node of inspectedNodes) {
    for (const attr of node.attributes || []) {
      if (/(chat|dialog|conversation|group|channel|peer|type|member)/i.test(attr.name))
        put('dom.' + attr.name, attr.value);
    }
  }
  const roots = [];
  for (const node of inspectedNodes) {
    for (const key of Object.getOwnPropertyNames(node)) {
      if (key.startsWith('__reactProps$') || key.startsWith('__reactFiber$')) roots.push(node[key]);
    }
  }
  const seen = new WeakSet(); let visited = 0;
  const walk = (value, path, depth) => {
    if (!value || typeof value !== 'object' || depth > 7 || visited++ > 3000 || seen.has(value)) return;
    seen.add(value);
    for (const [key, child] of Object.entries(value)) {
      const next = path ? path + '.' + key : key;
      if (/(chatType|dialogType|conversationType|peerType|entityType|isGroup|isChannel|isDirect|isPrivate|isSystem|membersCount|participantsCount|type)$/i.test(key)
          && (typeof child === 'string' || typeof child === 'number' || typeof child === 'boolean')) put(next, child);
      if (depth < 7 && (key === 'memoizedProps' || key === 'pendingProps' || key === 'child' || key === 'props' || key === 'data' || key === 'chat' || key === 'dialog' || key === 'conversation' || Array.isArray(child)))
        walk(child, next, depth + 1);
    }
  };
  roots.forEach(root => walk(root, '', 0));
  return {
    evidence,
    text: (element.innerText || '').trim().slice(0, 500),
    href: element.href || element.closest('a')?.href || element.querySelector('a[href]')?.href || '',
    id: element.getAttribute('data-chat-id') || element.getAttribute('data-dialog-id') || element.getAttribute('data-conversation-id') || ''
  };
}
"""


@dataclass(frozen=True)
class DelayRange:
    minimum: float
    maximum: float

    def wait(self, stop: threading.Event) -> None:
        stop.wait(random.uniform(self.minimum, self.maximum))


def classify_dialog(evidence: dict[str, list[str]]) -> tuple[bool, str]:
    """Accept only an explicit group/chat model and reject unsafe entity types."""
    pairs = [(key.casefold(), value.casefold()) for key, values in evidence.items() for value in values]
    negative_words = ("channel", "direct", "private", "dialog", "user", "bot", "system", "official")
    for key, value in pairs:
        if any(word in value for word in negative_words) and ("type" in key or key.endswith(("ischannel", "isdirect", "isprivate", "issystem"))):
            return False, f"исключающий признак {key}={value}"
        if key.endswith(("ischannel", "isdirect", "isprivate", "issystem")) and value == "true":
            return False, f"исключающий признак {key}=true"
    for key, value in pairs:
        if key.endswith("isgroup") and value == "true":
            return True, f"{key}=true"
        if "type" in key and value.replace("_", "-") in {"group", "group-chat", "groupchat", "supergroup", "chat"}:
            return True, f"{key}={value}"
    return False, "нет явного признака группы в DOM/React-модели"


class MaxAutomation:
    def __init__(self, profile: Path, diagnostics: Path, log: Callable[[str], None]) -> None:
        self.profile, self.diagnostics, self.log = profile, diagnostics, log
        self.context = self.page = self._playwright = None
        self.diagnostic = True

    def open_for_login(self, diagnostic: bool = True) -> None:
        if getattr(sys, "frozen", False):
            bundled = Path(sys.executable).parent / "browser"
            if bundled.exists(): os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled)
        from playwright.sync_api import sync_playwright
        self.profile.mkdir(parents=True, exist_ok=True); self.diagnostics.mkdir(parents=True, exist_ok=True)
        self.diagnostic = diagnostic
        if self.context:
            self.page.bring_to_front(); return
        self._playwright = sync_playwright().start()
        self.context = self._playwright.chromium.launch_persistent_context(str(self.profile), headless=False, viewport={"width": 1360, "height": 850})
        if diagnostic: self.context.tracing.start(screenshots=True, snapshots=True, sources=True)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.goto(MAX_URL, wait_until="domcontentloaded")
        self.log("Открыт официальный web.max.ru. Выполните вход самостоятельно.")

    def _confirmed_group_rows(self):
        rows = self.page.locator(DIALOG_ROW_SELECTOR).filter(visible=True)
        groups, rejected, seen = [], 0, set()
        for index in range(rows.count()):
            row = rows.nth(index)
            try:
                details = row.evaluate(MODEL_EVIDENCE_SCRIPT)
                key = details["id"] or details["href"] or details["text"]
                if not key or key in seen: continue
                seen.add(key)
                accepted, reason = classify_dialog(details["evidence"])
                name = details["text"].splitlines()[0] if details["text"] else key
                if accepted:
                    groups.append((row, name, reason)); self.log(f"Группа подтверждена: {name} ({reason})")
                else:
                    rejected += 1
            except Exception as error:
                self.log(f"Не удалось классифицировать строку {index + 1}: {error}")
        self.log(f"Проверено видимых строк: {len(seen)}; подтверждено групп: {len(groups)}; безопасно пропущено: {rejected}")
        return groups

    def scan(self, stop: threading.Event, click_delay: DelayRange, chat_delay: DelayRange,
             progress: Callable[[int, int], None], found: Callable[[int], None]) -> list[Invitation]:
        if not self.page: raise RuntimeError("Сначала нажмите «Открыть MAX и войти»")
        self.page.wait_for_load_state("domcontentloaded")
        groups = self._confirmed_group_rows()
        if not groups:
            self._capture_discovery_diagnostics()
            self.log("Группы не распознаны. Диагностика DOM сохранена; личные чаты не открывались.")
        invitations, seen = [], set(); total = len(groups)
        for index, (row, name, reason) in enumerate(groups, 1):
            if stop.is_set(): break
            try:
                self.log(f"Открываю группу {index}/{total}: {name}")
                row.scroll_into_view_if_needed(); row.click(); click_delay.wait(stop)
                header = self.page.locator(
                    '[data-testid="chat-header-title"], [data-testid*="chat-header"] [data-testid*="avatar"], '
                    'main header h1, main header h2, main header img'
                ).first
                header.click(); click_delay.wait(stop)
                links = self.page.get_by_text("Ссылки", exact=True).or_(self.page.get_by_text("Links", exact=True)).first
                links.click(); click_delay.wait(stop)
                panel = self.page.locator('[role="tabpanel"]:visible, [data-testid*="links"]:visible, [role="dialog"]:visible').last
                previous = -1
                for _ in range(60):
                    for href in panel.locator('a[href]').evaluate_all("els => els.map(e => e.href)"):
                        invite = normalize_invite(href)
                        if invite and invite.casefold() not in seen:
                            seen.add(invite.casefold()); invitations.append(Invitation.create(name, invite)); found(len(invitations))
                    height = panel.evaluate("el => el.scrollHeight")
                    panel.evaluate("el => el.scrollTop = el.scrollHeight")
                    if height == previous: break
                    previous = height; click_delay.wait(stop)
                self.page.keyboard.press("Escape")
            except Exception as error:
                self._capture_error(index, error)
            progress(index, total); chat_delay.wait(stop)
        return invitations

    def _capture_discovery_diagnostics(self) -> None:
        if not self.diagnostic: return
        stamp = int(time.time())
        self.page.screenshot(path=str(self.diagnostics / f"discovery_{stamp}.png"), full_page=True)
        (self.diagnostics / f"discovery_{stamp}.html").write_text(self.page.content(), encoding="utf-8")
        inventory = self.page.locator('[data-testid], [role], a[href]').evaluate_all(
            "els => els.map(e => ({tag:e.tagName, testid:e.dataset.testid||'', role:e.getAttribute('role')||'', href:e.href||'', text:(e.innerText||'').trim().slice(0,120)}))")
        (self.diagnostics / f"discovery_{stamp}.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")

    def _capture_error(self, index: int, error: Exception) -> None:
        self.log(f"Ошибка в группе {index}: {error}")
        if self.page: self.page.screenshot(path=str(self.diagnostics / f"error_group_{index}_{int(time.time())}.png"), full_page=True)

    def close(self) -> None:
        if self.context:
            try:
                if self.diagnostic: self.context.tracing.stop(path=str(self.diagnostics / f"trace_{int(time.time())}.zip"))
            finally: self.context.close()
        if self._playwright: self._playwright.stop()
        self.context = self.page = self._playwright = None
