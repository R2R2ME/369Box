"""Dialogs: case metadata entry and device operation confirmation."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
)

from box369.case_meta import CaseMetadata
from box369.devices import StorageDevice


class CaseMetadataDialog(QDialog):
    """Capture examiner / case metadata before operations."""

    def __init__(self, parent=None, existing: CaseMetadata | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Case / Examiner Metadata — 369box")
        self.setMinimumWidth(480)
        self._meta = existing or CaseMetadata()
        self._meta.refresh_timestamp()

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Optional session details for the log "
            "(attached to each audit entry)."
        )
        intro.setWordWrap(True)
        intro.setObjectName("subtitle")
        layout.addWidget(intro)

        form = QFormLayout()
        self.examiner = QLineEdit(self._meta.examiner_name)
        self.case_number = QLineEdit(self._meta.case_number)
        self.evidence_tag = QLineEdit(self._meta.evidence_tag)
        self.description = QTextEdit()
        self.description.setPlainText(self._meta.description)
        self.description.setFixedHeight(80)
        self.datetime_label = QLabel(
            f"{self._meta.started_at}  ({self._meta.timezone_name})"
        )

        form.addRow("Examiner name *", self.examiner)
        form.addRow("Case number *", self.case_number)
        form.addRow("Evidence tag *", self.evidence_tag)
        form.addRow("Description", self.description)
        form.addRow("Date / time", self.datetime_label)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        if not (
            self.examiner.text().strip()
            and self.case_number.text().strip()
            and self.evidence_tag.text().strip()
        ):
            QMessageBox.warning(
                self,
                "Incomplete metadata",
                "Examiner name, case number, and evidence tag are required.",
            )
            return
        self.accept()

    def metadata(self) -> CaseMetadata:
        self._meta.examiner_name = self.examiner.text().strip()
        self._meta.case_number = self.case_number.text().strip()
        self._meta.evidence_tag = self.evidence_tag.text().strip()
        self._meta.description = self.description.toPlainText().strip()
        return self._meta


class DeviceConfirmDialog(QDialog):
    """Confirm a device operation.

    Modes:
    - ``serial``: type serial to bind/confirm (first use or high-risk).
    - ``ack``: review details and proceed (device already bound this session).
    """

    def __init__(
        self,
        parent,
        device: StorageDevice,
        operation: str,
        *,
        mode: str = "ack",
    ) -> None:
        super().__init__(parent)
        self._mode = mode
        self._expected_serial = device.serial_number.strip()

        if mode == "serial":
            self.setWindowTitle("Bind device — 369box")
        else:
            self.setWindowTitle("Confirm — 369box")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)

        if mode == "serial":
            warn = QLabel(
                f"<b>Bind this device, then:</b> {operation}<br><br>"
                "Type the serial once for this session. "
                "Later actions on the same device only need a quick confirm. "
                "Disabling write protection always asks for the serial again."
            )
        else:
            warn = QLabel(
                f"<b>Proceed with:</b> {operation}<br><br>"
                "Device is already bound for this session. Verify the details below."
            )
        warn.setWordWrap(True)
        warn.setStyleSheet(
            "background:#3a2a18; color:#f0d9a8; border:1px solid #c4893a; "
            "padding:10px; border-radius:6px;"
        )
        layout.addWidget(warn)

        details = QLabel(
            f"<b>Model:</b> {device.model}<br>"
            f"<b>Serial number:</b> {device.serial_number}<br>"
            f"<b>Size:</b> {device.size_human} ({device.size_bytes:,} bytes)<br>"
            f"<b>Drive letter(s):</b> {', '.join(device.drive_letters) or '(none)'}<br>"
            f"<b>Physical disk:</b> #{device.physical_disk_index}<br>"
            f"<b>Interface:</b> {device.interface_type}<br>"
            f"<b>Filesystem:</b> {device.filesystem or 'Unknown'}"
        )
        details.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(details)

        self.serial_input: QLineEdit | None = None
        if mode == "serial":
            confirm_row = QHBoxLayout()
            confirm_row.addWidget(QLabel("Type serial to bind:"))
            self.serial_input = QLineEdit()
            self.serial_input.setPlaceholderText(device.serial_number)
            self.serial_input.returnPressed.connect(self._on_accept)
            confirm_row.addWidget(self.serial_input)
            layout.addLayout(confirm_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn:
            ok_btn.setText("Bind & Proceed" if mode == "serial" else "Proceed")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if self.serial_input is not None:
            self.serial_input.setFocus()

    def _on_accept(self) -> None:
        if self._mode == "serial":
            assert self.serial_input is not None
            typed = self.serial_input.text().strip()
            if typed.casefold() != self._expected_serial.casefold():
                QMessageBox.critical(
                    self,
                    "Serial mismatch",
                    "Serial number does not match. Operation cancelled.",
                )
                return
        self.accept()
