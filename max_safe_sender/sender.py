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

    def _send_current_message(self, editor) -> None:
        """Use MAX's send control, falling back to Enter only when absent."""
        send = self.browser.page.locator(
            'button[aria-label*="отправ" i]:visible, [role="button"][aria-label*="отправ" i]:visible, '
            'button[title*="отправ" i]:visible, button[aria-label*="send" i]:visible, '
            '[data-testid*="send" i]:visible'
        ).last
        if send.count():
            send.click(timeout=5_000)
        else:
            # Text-only MAX builds submit the composer with Enter and have no
            # labelled send button in the DOM.
            editor.press("Enter")

    @staticmethod
    def _type_message(editor, message: str) -> None:
        editor.click()
        editor.press("Control+A")
        editor.insert_text(message)

    def _attach_image(self, image: str, delay: DelayRange, stop: threading.Event):
        chooser = self.browser.page.locator('input[type="file"]')
        if not chooser.count():
            attach = self.browser.page.locator(
                'button[aria-label*="прикреп" i], [role="button"][aria-label*="прикреп" i], '
                'button[title*="прикреп" i], button[aria-label*="attach" i]'
            ).last
            attach.click(timeout=5_000); delay.wait(stop)
            chooser = self.browser.page.locator('input[type="file"]')
        if not chooser.count(): raise RuntimeError("Кнопка прикрепления изображения не найдена")
        chooser.last.set_input_files(image); delay.wait(stop)
        self.browser.page.evaluate(MARK_COMPOSER_SCRIPT)
        editor = self.browser.page.locator('[data-max-sender-editor="true"]')
        editor.wait_for(state="visible", timeout=10_000)
        return editor

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
                    editor = self._attach_image(campaign.image, delay, stop)
                self._type_message(editor, campaign.message)
                if campaign.dry_run:
                    self.log(f"Тест: подготовлено сообщение для {name}, отправки нет")
                else:
                    for copy_index in range(campaign.copies):
                        self._send_current_message(editor)
                        delay.wait(stop)
                        self.log(f"Отправлено в «{name}»: {copy_index + 1}/{campaign.copies}")
                        if copy_index + 1 < campaign.copies:
                            # Sending clears/re-renders the editor. Reacquire it
                            # and type the content again for each requested copy.
                            self.browser.page.evaluate(MARK_COMPOSER_SCRIPT)
                            editor = self.browser.page.locator('[data-max-sender-editor="true"]')
                            editor.wait_for(state="visible", timeout=10_000)
                            if campaign.image:
                                editor = self._attach_image(campaign.image, delay, stop)
                            self._type_message(editor, campaign.message)
                state.completed.append(name); state.failed.pop(name, None)
            except Exception as error:
                state.failed[name] = str(error); self.log(f"Пропущен {name}: {error}")
            finally:
                self.browser._clear_chat_search(); state.save(state_path); progress(index, len(pending))
        return state
