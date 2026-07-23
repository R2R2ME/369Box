"""Append-only tamper-evident audit logging and report export."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class AuditEntry:
    timestamp: str
    action: str
    detail: str
    case_number: str = ""
    examiner_name: str = ""
    evidence_tag: str = ""
    device_serial: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AuditLog:
    """
    Append-only session log. The in-app API never edits or deletes entries.
    A running SHA-256 chain links each entry for basic tamper evidence.
    """

    def __init__(self, log_dir: Path | None = None) -> None:
        base = log_dir or Path.home() / "Documents" / "369box" / "logs"
        base.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = base / f"audit_{stamp}.jsonl"
        self.entries: list[AuditEntry] = []
        self._chain = "0" * 64
        self._write_header()

    def _write_header(self) -> None:
        header = {
            "type": "header",
            "app": "369box",
            "created": _now_iso(),
            "note": "Append-only audit log. Do not edit.",
        }
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(header, ensure_ascii=False) + "\n")

    def append(
        self,
        action: str,
        detail: str,
        *,
        case_number: str = "",
        examiner_name: str = "",
        evidence_tag: str = "",
        device_serial: str = "",
        extra: dict[str, Any] | None = None,
    ) -> AuditEntry:
        entry = AuditEntry(
            timestamp=_now_iso(),
            action=action,
            detail=detail,
            case_number=case_number,
            examiner_name=examiner_name,
            evidence_tag=evidence_tag,
            device_serial=device_serial,
            extra=extra or {},
        )
        payload = json.dumps(entry.to_dict(), sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256((self._chain + payload).encode("utf-8")).hexdigest()
        self._chain = digest
        record = {"type": "entry", "entry": entry.to_dict(), "chain_sha256": digest}
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.entries.append(entry)
        return entry

    @property
    def chain_head(self) -> str:
        return self._chain

    def export_report(
        self,
        destination: Path,
        *,
        case_meta: dict[str, Any],
        device_info: dict[str, Any] | None,
        hashes: list[dict[str, Any]],
        protection_history: list[str],
        hash_comparison: dict[str, Any] | None = None,
    ) -> Path:
        destination = Path(destination)
        lines: list[str] = []
        lines.append("=" * 72)
        lines.append("369box FORENSIC WRITE-BLOCKER — SESSION REPORT")
        lines.append("=" * 72)
        lines.append(f"Generated: {_now_iso()}")
        lines.append(f"Audit log file: {self.log_path}")
        lines.append(f"Log chain head (SHA-256): {self._chain}")
        lines.append("")
        lines.append("-" * 72)
        lines.append("CASE / EXAMINER METADATA")
        lines.append("-" * 72)
        for key, value in case_meta.items():
            lines.append(f"  {key}: {value}")
        lines.append("")
        lines.append("-" * 72)
        lines.append("DEVICE INFORMATION")
        lines.append("-" * 72)
        if device_info:
            for key, value in device_info.items():
                lines.append(f"  {key}: {value}")
        else:
            lines.append("  (no device selected)")
        lines.append("")
        lines.append("-" * 72)
        lines.append("HASH VALUES")
        lines.append("-" * 72)
        if hashes:
            for i, h in enumerate(hashes, 1):
                lines.append(f"  [{i}] label={h.get('label')}  at={h.get('timestamp', '')}")
                lines.append(f"      MD5:     {h.get('md5', '')}")
                lines.append(f"      SHA-1:   {h.get('sha1', '')}")
                lines.append(f"      SHA-256: {h.get('sha256', '')}")
                lines.append(f"      bytes:   {h.get('bytes_hashed', '')}")
        else:
            lines.append("  (no hashes calculated)")
        if hash_comparison:
            lines.append("")
            lines.append("  Comparison vs baseline:")
            for algo, matched in hash_comparison.items():
                mark = "MATCH" if matched else "MISMATCH"
                lines.append(f"    {algo}: {mark}")
        lines.append("")
        lines.append("-" * 72)
        lines.append("WRITE-PROTECTION STATUS HISTORY")
        lines.append("-" * 72)
        if protection_history:
            for item in protection_history:
                lines.append(f"  • {item}")
        else:
            lines.append("  (no protection events)")
        lines.append("")
        lines.append("-" * 72)
        lines.append("FULL TIMESTAMPED AUDIT LOG")
        lines.append("-" * 72)
        for entry in self.entries:
            lines.append(
                f"[{entry.timestamp}] {entry.action}: {entry.detail}"
            )
            if entry.device_serial:
                lines.append(f"    device_serial={entry.device_serial}")
        lines.append("")
        lines.append("=" * 72)
        lines.append("END OF REPORT — append-only log; verify chain head if integrity matters.")
        lines.append("=" * 72)
        lines.append("")

        text = "\n".join(lines)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")

        # Sidecar integrity hash of the report itself
        report_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        sidecar = destination.with_suffix(destination.suffix + ".sha256")
        sidecar.write_text(
            f"{report_hash}  {destination.name}\n", encoding="utf-8"
        )
        return destination
