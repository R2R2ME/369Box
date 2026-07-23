"""Case / examiner metadata for forensic sessions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def _local_now_iso() -> str:
    local = datetime.now().astimezone()
    return local.isoformat(timespec="seconds")


@dataclass
class CaseMetadata:
    examiner_name: str = ""
    case_number: str = ""
    evidence_tag: str = ""
    description: str = ""
    started_at: str = field(default_factory=_local_now_iso)
    timezone_name: str = field(
        default_factory=lambda: datetime.now().astimezone().tzname() or "local"
    )

    def is_complete(self) -> bool:
        return bool(
            self.examiner_name.strip()
            and self.case_number.strip()
            and self.evidence_tag.strip()
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def refresh_timestamp(self) -> None:
        self.started_at = _local_now_iso()
        self.timezone_name = datetime.now().astimezone().tzname() or "local"
