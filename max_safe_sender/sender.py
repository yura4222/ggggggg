"""Playwright sender restricted to an explicitly approved recipient tuple."""
from __future__ import annotations
import threading
from pathlib import Path
from typing import Callable
from max_chat_link_finder.automation import ChatSnapshot, DelayRange, MaxAutomation
from .campaign import Campaign, CampaignState, validate_campaign

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
                editor = self.browser.page.locator('[contenteditable="true"]:visible').last
                editor.wait_for(state="visible", timeout=10_000)
                if campaign.image:
                    chooser = self.browser.page.locator('input[type="file"]')
                    if not chooser.count(): raise RuntimeError("Поле загрузки изображения не найдено")
                    chooser.last.set_input_files(campaign.image)
                editor.fill(campaign.message)
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
