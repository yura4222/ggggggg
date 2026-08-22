"""Safety constraints and resumable state for approved campaigns."""
from __future__ import annotations
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

MAX_RECIPIENTS = 20

@dataclass(frozen=True)
class Campaign:
    recipients: tuple[str, ...]
    message: str
    image: str = ""
    copies: int = 1
    dry_run: bool = True

@dataclass
class CampaignState:
    completed: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "CampaignState":
        if not path.exists(): return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data.get("completed", []), data.get("failed", {}))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")


def validate_campaign(campaign: Campaign, scanned: set[str]) -> None:
    unique = {x.casefold() for x in campaign.recipients}
    if not unique: raise ValueError("Выберите хотя бы один согласованный чат")
    if len(unique) > MAX_RECIPIENTS: raise ValueError(f"Не более {MAX_RECIPIENTS} получателей за запуск")
    if campaign.copies not in range(1, 4): raise ValueError("Допустимо от 1 до 3 сообщений")
    if not campaign.message.strip() and not campaign.image: raise ValueError("Введите текст или выберите изображение")
    missing = [x for x in campaign.recipients if x.casefold() not in scanned]
    if missing: raise ValueError("Получатели отсутствуют в зафиксированном списке: " + ", ".join(missing))
