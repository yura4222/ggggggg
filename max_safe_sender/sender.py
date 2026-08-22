"""Playwright sender restricted to an explicitly approved recipient tuple."""
from __future__ import annotations
import threading
from pathlib import Path
from typing import Callable
from max_chat_link_finder.automation import ChatSnapshot, DelayRange, MaxAutomation
from .campaign import Campaign, CampaignState, validate_campaign

MARK_COMPOSER_SCRIPT = r"""
() => {
  document.querySelectorAll('[data-max-sender-editor]').forEach(e => e.removeAttribute('data-max-sender-editor'));
  const candidates = [...document.querySelectorAll('[contenteditable], textarea, [role="textbox"]')]
    .filter(e => { const r=e.getBoundingClientRect(), s=getComputedStyle(e);
      return s.display!=='none' && s.visibility!=='hidden' && r.width>200 && r.height>20
        && r.top>innerHeight*.45 && r.bottom<=innerHeight+2; })
    .sort((a,b) => b.getBoundingClientRect().bottom-a.getBoundingClientRect().bottom);
  if (candidates[0]) candidates[0].setAttribute('data-max-sender-editor','true');
}
"""

class ApprovedSender:
    def __init__(self, browser: MaxAutomation, log: Callable[[str], None]) -> None:
        self.browser, self.log = browser, log

    def run(self, campaign: Campaign, scanned: list[ChatSnapshot], state_path: Path,
            stop: threading.Event, pause: threading.Event, delay: DelayRange,
            progress: Callable[[int, int], None]) -> CampaignState:
        validate_campaign(campaign, {x.name.casefold() for x in scanned})
        state = CampaignState.load(state_path)
        lookup = {x.name.casefold(): x for x in scanned}
        pending = [x for x in campaign.recipients if x not in state.completed]
        for index, name in enumerate(pending, 1):
            if stop.is_set(): break
            while pause.is_set() and not stop.wait(.2): pass
            if stop.is_set(): break
            try:
                row = self.browser._find_snapshotted_row(lookup[name.casefold()])
                row.click(timeout=10_000); delay.wait(stop)
                # MAX currently uses contenteditable="plaintext-only" in some
                # builds and a textarea/role=textbox in others. Mark only the
                # large, lower-page composer so the search input is never used.
                self.browser.page.evaluate(MARK_COMPOSER_SCRIPT)
                editor = self.browser.page.locator('[data-max-sender-editor="true"]')
                editor.wait_for(state="visible", timeout=10_000)
                if campaign.image:
                    chooser = self.browser.page.locator('input[type="file"]')
                    if not chooser.count():
                        attach = self.browser.page.locator(
                            'button[aria-label*="прикреп" i], [role="button"][aria-label*="прикреп" i], '
                            'button[title*="прикреп" i], button[aria-label*="attach" i]'
                        ).last
                        attach.click(timeout=5_000); delay.wait(stop)
                        chooser = self.browser.page.locator('input[type="file"]')
                    if not chooser.count(): raise RuntimeError("Кнопка прикрепления изображения не найдена")
                    chooser.last.set_input_files(campaign.image)
                    delay.wait(stop)
                    self.browser.page.evaluate(MARK_COMPOSER_SCRIPT)
                    editor = self.browser.page.locator('[data-max-sender-editor="true"]')
                    editor.wait_for(state="visible", timeout=10_000)
                editor.click()
                editor.press("Control+A")
                editor.insert_text(campaign.message)
                if campaign.dry_run:
                    self.log(f"Тест: подготовлено сообщение для {name}, отправки нет")
                else:
                    for _ in range(campaign.copies):
                        editor.press("Enter"); delay.wait(stop)
                state.completed.append(name); state.failed.pop(name, None)
            except Exception as error:
                state.failed[name] = str(error); self.log(f"Пропущен {name}: {error}")
            finally:
                self.browser._clear_chat_search(); state.save(state_path); progress(index, len(pending))
        return state
