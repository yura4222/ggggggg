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

# MAX uses a virtualized list and does not expose stable chat-row selectors.
MARK_VISIBLE_ROWS_SCRIPT = r"""
() => {
  document.querySelectorAll('[data-max-finder-row]').forEach(e => e.removeAttribute('data-max-finder-row'));
  const search = [...document.querySelectorAll('input')].find(e =>
    /^(найти|search)/i.test(e.placeholder || '') && e.getBoundingClientRect().width > 200);
  if (!search) return {count: 0, reason: 'search input not found'};
  const anchor = search.getBoundingClientRect();
  const candidates = [...document.querySelectorAll('body *')].filter(element => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    const text = (element.innerText || '').trim();
    return text && style.display !== 'none' && style.visibility !== 'hidden'
      && rect.top >= anchor.bottom - 2 && rect.bottom <= innerHeight + 2
      && rect.left <= anchor.left + 24 && rect.right >= anchor.right - 24
      && rect.height >= 58 && rect.height <= 135
      && (!!element.querySelector('img, [role="img"], svg') || text.split('\n').filter(Boolean).length >= 2);
  });
  // Keep the widest outer row when several nested elements describe one item.
  const rows = candidates.filter(element => !candidates.some(other =>
    other !== element && other.contains(element)
    && Math.abs(other.getBoundingClientRect().top - element.getBoundingClientRect().top) < 4
    && Math.abs(other.getBoundingClientRect().bottom - element.getBoundingClientRect().bottom) < 4));
  rows.forEach((row, index) => row.setAttribute('data-max-finder-row', String(index)));
  return {count: rows.length, reason: 'geometry below search input'};
}
"""

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


def classify_dialog(evidence: dict[str, list[str]], name: str = "") -> tuple[bool, str]:
    """Accept chat rows, excluding channels and the official MAX conversation."""
    if "max" in name.casefold():
        return False, "название содержит MAX"
    pairs = [(key.casefold(), value.casefold()) for key, values in evidence.items() for value in values]
    for key, value in pairs:
        if "channel" in value and "type" in key:
            return False, f"признак канала {key}={value}"
        if key.endswith("ischannel") and value == "true":
            return False, f"признак канала {key}=true"
    for key, value in pairs:
        if key.endswith("isgroup") and value == "true":
            return True, f"группа: {key}=true"
        if "type" in key and value.replace("_", "-") in {"direct", "private", "dialog", "user"}:
            return True, f"личный чат: {key}={value}"
    return True, "обычная строка раздела «Чаты»"


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

    def _scannable_chat_rows(self, processed: set[str] | None = None):
        processed = processed or set()
        discovery = self.page.evaluate(MARK_VISIBLE_ROWS_SCRIPT)
        # Do not union this with generic role=listitem selectors: MAX uses those
        # for the left navigation (Все, Новые, Каналы) as well as chat content.
        rows = self.page.locator('[data-max-finder-row]').filter(visible=True)
        groups, rejected, seen = [], 0, set()
        for index in range(rows.count()):
            row = rows.nth(index)
            try:
                details = row.evaluate(MODEL_EVIDENCE_SCRIPT)
                key = details["id"] or details["href"] or details["text"]
                if not key or key in seen or key in processed: continue
                seen.add(key)
                name = details["text"].splitlines()[0] if details["text"] else key
                accepted, reason = classify_dialog(details["evidence"], name)
                if accepted:
                    groups.append((row, name, reason, key)); self.log(f"Чат добавлен: {name} ({reason})")
                else:
                    rejected += 1
            except Exception as error:
                self.log(f"Не удалось классифицировать строку {index + 1}: {error}")
        self.log(f"Геометрический поиск: {discovery['count']}; проверено строк: {len(seen)}; добавлено чатов: {len(groups)}; исключено: {rejected}")
        return groups

    def _scroll_chat_list(self) -> bool:
        return bool(self.page.evaluate(r"""
() => {
  const row = document.querySelector('[data-max-finder-row]');
  if (!row) return false;
  let scroller = row.parentElement;
  while (scroller) {
    const style = getComputedStyle(scroller);
    if (/(auto|scroll)/.test(style.overflowY) && scroller.scrollHeight > scroller.clientHeight + 10) break;
    scroller = scroller.parentElement;
  }
  if (!scroller) return false;
  const before = scroller.scrollTop;
  scroller.scrollTop = Math.min(scroller.scrollTop + scroller.clientHeight * 0.8, scroller.scrollHeight);
  return scroller.scrollTop > before + 1;
}
"""))

    def _open_chat_info(self, row, name: str, click_delay: DelayRange, stop: threading.Event) -> None:
        row.scroll_into_view_if_needed()
        row.click(timeout=10_000)
        click_delay.wait(stop)
        # The title is the reliable target in the live client; structural
        # header/test-id selectors are not present in the current MAX markup.
        title = self.page.get_by_text(name, exact=True).last
        title.wait_for(state="visible", timeout=10_000)
        title.click(timeout=10_000)
        click_delay.wait(stop)
        self.page.get_by_text("Инфо", exact=True).wait_for(state="visible", timeout=10_000)

    def _collect_info_invites(self, name: str, click_delay: DelayRange, stop: threading.Event,
                              invitations: list[Invitation], seen: set[str], found: Callable[[int], None]) -> None:
        links_tab = self.page.get_by_text("Ссылки", exact=True).or_(self.page.get_by_text("Links", exact=True)).last
        links_tab.click(timeout=10_000)
        click_delay.wait(stop)
        previous_count = -1
        for _ in range(80):
            hrefs = self.page.locator('a[href*="max.ru/join/"]').evaluate_all("els => els.map(e => e.href)")
            for href in hrefs:
                invite = normalize_invite(href)
                if invite and invite.casefold() not in seen:
                    seen.add(invite.casefold()); invitations.append(Invitation.create(name, invite)); found(len(invitations))
            # Info does not expose a role=tabpanel. Scroll the largest visible
            # scroll container, which is the actual Info panel in the MAX client.
            moved = self.page.evaluate(r"""
() => {
  const visible = [...document.querySelectorAll('body *')].filter(e => {
    const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 350 && r.height > 250 && r.bottom > 0 && r.top < innerHeight
      && /(auto|scroll)/.test(s.overflowY) && e.scrollHeight > e.clientHeight + 10;
  }).sort((a,b) => (b.scrollHeight-b.clientHeight) - (a.scrollHeight-a.clientHeight));
  const pane = visible[0]; if (!pane) return false;
  const before = pane.scrollTop; pane.scrollTop = Math.min(pane.scrollTop + pane.clientHeight * .8, pane.scrollHeight);
  return pane.scrollTop > before + 1;
}
""")
            if not moved and len(hrefs) == previous_count:
                break
            previous_count = len(hrefs); click_delay.wait(stop)

    def _close_info(self) -> None:
        closed = self.page.evaluate(r"""
() => {
  const info = [...document.querySelectorAll('body *')].find(e =>
    e.children.length === 0 && (e.textContent || '').trim() === 'Инфо');
  if (!info) return false;
  const ir = info.getBoundingClientRect(), cy = ir.top + ir.height / 2;
  const candidates = [...document.querySelectorAll('button, [role="button"]')].filter(e => {
    const r = e.getBoundingClientRect();
    return r.width > 15 && r.height > 15 && r.right < ir.left && Math.abs(r.top + r.height / 2 - cy) < 55;
  }).sort((a,b) => b.getBoundingClientRect().right - a.getBoundingClientRect().right);
  if (!candidates[0]) return false; candidates[0].click(); return true;
}
""")
        if not closed:
            self.page.keyboard.press("Escape")

    def scan(self, stop: threading.Event, click_delay: DelayRange, chat_delay: DelayRange,
             progress: Callable[[int, int], None], found: Callable[[int], None]) -> list[Invitation]:
        if not self.page: raise RuntimeError("Сначала нажмите «Открыть MAX и войти»")
        self.page.wait_for_load_state("domcontentloaded")
        invitations, seen, processed = [], set(), set()
        completed = 0
        for _ in range(500):
            chats = self._scannable_chat_rows(processed)
            if not chats and not processed:
                self._capture_discovery_diagnostics(); self.log("Строки чатов не распознаны. Диагностика DOM сохранена.")
                break
            if chats:
                # Process one locator then rediscover. A click makes React replace
                # row nodes, so retaining nth(…) locators caused the reported 30s
                # timeouts and shifted subsequent locators to navigation items.
                row, name, reason, key = chats[0]
                processed.add(key)
                try:
                    self.log(f"Открываю чат {completed + 1}: {name}")
                    self._open_chat_info(row, name, click_delay, stop)
                    self._collect_info_invites(name, click_delay, stop, invitations, seen, found)
                    self.log(f"Ссылки в чате «{name}» проверены")
                    self._close_info()
                except Exception as error:
                    self._capture_error(completed + 1, error)
                    self._close_info()
                completed += 1; progress(completed, completed + max(0, len(chats) - 1)); chat_delay.wait(stop)
                continue
            if stop.is_set() or not self._scroll_chat_list(): break
            click_delay.wait(stop)
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
        self.log(f"Ошибка в чате {index}: {error}")
        if self.page: self.page.screenshot(path=str(self.diagnostics / f"error_group_{index}_{int(time.time())}.png"), full_page=True)

    def close(self) -> None:
        if self.context:
            try:
                if self.diagnostic: self.context.tracing.stop(path=str(self.diagnostics / f"trace_{int(time.time())}.zip"))
            finally: self.context.close()
        if self._playwright: self._playwright.stop()
        self.context = self.page = self._playwright = None
