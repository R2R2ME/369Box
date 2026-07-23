"""Main application window for 369box."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QFrame,
)

from box369.audit import AuditLog
from box369.case_meta import CaseMetadata
from box369.devices import StorageDevice, format_bytes, is_safe_evidence_device, list_removable_devices
from box369.gui.dialogs import CaseMetadataDialog, DeviceConfirmDialog
from box369.gui.styles import APP_STYLE
from box369.hashing import HashResult, compare_hashes, hash_device
from box369.writeprotect import (
    get_read_only_status,
    is_admin,
    set_write_protection,
)
from box369.eject import eject_drive


def _logo_path() -> Path:
    return Path(__file__).resolve().parent.parent / "assets" / "369box_logo.png"


class HashWorker(QThread):
    progress = pyqtSignal(int, int)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        device: StorageDevice,
        label: str,
        mode: str = "filesystem",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.device = device
        self.label = label
        self.mode = mode  # "filesystem" | "raw"
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            result = hash_device(
                self.device.physical_disk_index,
                self.device.size_bytes,
                self.device.primary_mount,
                label=self.label,
                mode=self.mode,
                progress=lambda r, t: self.progress.emit(r, t),
                should_cancel=lambda: self._cancel,
            )
            self.finished_ok.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("369box")
        self.resize(1100, 760)
        self.setStyleSheet(APP_STYLE)
        self.setWindowOpacity(0.93)
        logo = _logo_path()
        if logo.exists():
            self.setWindowIcon(QIcon(str(logo)))

        self.case_meta = CaseMetadata()
        self.audit = AuditLog()
        self.devices: list[StorageDevice] = []
        self.selected: StorageDevice | None = None
        self.baseline_hash: HashResult | None = None
        self.hash_history: list[dict[str, Any]] = []
        self.protection_history: list[str] = []
        self._known_serials: set[str] = set()
        self._hash_worker: HashWorker | None = None
        self._last_comparison: dict[str, bool] | None = None
        # Serial typed once per device per session; cleared on device change.
        self._armed_key: tuple[int, str] | None = None

        self._build_ui()
        self._prompt_case_metadata(initial=True)
        self.refresh_devices()

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_device_changes)
        self._poll_timer.start(4000)

        self.audit.append(
            "SESSION_START",
            "369box session started.",
            **self._case_fields(),
        )

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        banner = QWidget()
        banner.setObjectName("bannerBar")
        banner.setFixedHeight(78)
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(16, 8, 18, 8)
        banner_layout.setSpacing(14)

        logo_label = QLabel()
        logo_label.setStyleSheet("background: transparent;")
        logo_file = _logo_path()
        if logo_file.exists():
            pix = QPixmap(str(logo_file)).scaled(
                58,
                58,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            logo_label.setPixmap(pix)
            logo_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        else:
            logo_label.setText("◆")
            logo_label.setStyleSheet("background: transparent; font-size: 28px; color: #9b7fd4;")
        banner_layout.addWidget(logo_label)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("369box")
        title.setObjectName("bannerTitle")
        tagline = QLabel("USB write protection & hashing  ·  by Rana Almeshari")
        tagline.setObjectName("bannerTagline")
        title_col.addWidget(title)
        title_col.addWidget(tagline)
        banner_layout.addLayout(title_col)
        banner_layout.addStretch(1)
        self.bind_status = QLabel("No device bound")
        self.bind_status.setObjectName("subtitle")
        self.bind_status.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        banner_layout.addWidget(self.bind_status)
        root.addWidget(banner)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(14, 12, 14, 12)
        root.addWidget(body)

        # Case strip
        case_row = QHBoxLayout()
        self.case_summary = QLabel("Case metadata not set")
        self.case_summary.setObjectName("subtitle")
        case_row.addWidget(self.case_summary, stretch=1)
        edit_case_btn = QPushButton("Edit Case Metadata")
        edit_case_btn.setObjectName("secondaryButton")
        edit_case_btn.clicked.connect(lambda: self._prompt_case_metadata(initial=False))
        case_row.addWidget(edit_case_btn)
        body_layout.addLayout(case_row)

        admin_note = QLabel(
            "Administrator: YES — write protection available"
            if is_admin()
            else "Administrator: NO — run elevated to enable/disable write protection"
        )
        admin_note.setObjectName("subtitle")
        body_layout.addWidget(admin_note)

        # Vertical: work area (top) ↔ audit log (bottom) — drag to resize
        main_splitter = QSplitter(Qt.Orientation.Vertical)
        main_splitter.setChildrenCollapsible(False)
        main_splitter.setHandleWidth(6)
        body_layout.addWidget(main_splitter, stretch=1)

        # Horizontal: devices ↔ operations — drag to resize
        work_splitter = QSplitter(Qt.Orientation.Horizontal)
        work_splitter.setChildrenCollapsible(False)
        work_splitter.setHandleWidth(6)
        work_splitter.setMinimumHeight(320)
        main_splitter.addWidget(work_splitter)

        # Left: devices
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        device_box = QGroupBox("Removable / External Devices (system disk excluded)")
        device_layout = QVBoxLayout(device_box)
        self.device_tree = QTreeWidget()
        self.device_tree.setHeaderLabels(
            ["Drive", "Label", "Model", "Size", "Serial", "Interface", "FS"]
        )
        self.device_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.device_tree.setRootIsDecorated(False)
        self.device_tree.itemSelectionChanged.connect(self._on_selection_changed)
        device_layout.addWidget(self.device_tree)
        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("Refresh Devices")
        refresh_btn.setObjectName("secondaryButton")
        refresh_btn.clicked.connect(self.refresh_devices)
        btn_row.addWidget(refresh_btn)
        self.eject_btn = QPushButton("Safely Eject")
        self.eject_btn.setObjectName("secondaryButton")
        self.eject_btn.setToolTip(
            "Ask Windows to eject the selected USB (same idea as taskbar Safely Remove).\n"
            "Disable write protection first if you want the stick writable next time."
        )
        self.eject_btn.clicked.connect(self.safely_eject)
        btn_row.addWidget(self.eject_btn)
        btn_row.addStretch()
        device_layout.addLayout(btn_row)
        left_layout.addWidget(device_box)
        work_splitter.addWidget(left)

        # Right: actions + status (scrollable so Operations never collapses)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(10)

        self.protect_status = QLabel("WRITE PROTECTION: —")
        self.protect_status.setObjectName("statusUnknown")
        self.protect_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.protect_status.setMinimumHeight(48)
        right_layout.addWidget(self.protect_status)

        detail_box = QGroupBox("Selected Device")
        detail_box.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )
        detail_grid = QGridLayout(detail_box)
        self.detail_labels: dict[str, QLabel] = {}
        fields = [
            ("model", "Model"),
            ("serial", "Serial"),
            ("size", "Size"),
            ("letters", "Drive letter(s)"),
            ("interface", "Interface"),
            ("filesystem", "Filesystem"),
            ("disk", "Physical disk #"),
        ]
        for row, (key, title) in enumerate(fields):
            detail_grid.addWidget(QLabel(f"{title}:"), row, 0)
            val = QLabel("—")
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.detail_labels[key] = val
            detail_grid.addWidget(val, row, 1)
        right_layout.addWidget(detail_box)

        action_box = QGroupBox("Operations")
        action_box.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding
        )
        action_box.setMinimumHeight(260)
        action_layout = QVBoxLayout(action_box)

        protect_row = QHBoxLayout()
        self.enable_btn = QPushButton("Enable Write Protection")
        self.enable_btn.setObjectName("safeButton")
        self.enable_btn.clicked.connect(self.enable_write_protection)
        self.disable_btn = QPushButton("Disable Write Protection")
        self.disable_btn.setObjectName("dangerButton")
        self.disable_btn.clicked.connect(self.disable_write_protection)
        protect_row.addWidget(self.enable_btn)
        protect_row.addWidget(self.disable_btn)
        action_layout.addLayout(protect_row)

        hash_row = QHBoxLayout()
        self.hash_btn = QPushButton("Calculate Hash (files)")
        self.hash_btn.setToolTip(
            "Hashes all files on the volume (MD5/SHA-1/SHA-256).\n"
            "First scans the drive (progress may sit at 0%), then hashes.\n"
            "A full ~60GB USB can take many minutes."
        )
        self.hash_btn.clicked.connect(lambda: self.calculate_hash("filesystem"))
        self.hash_raw_btn = QPushButton("Raw Disk Hash")
        self.hash_raw_btn.setObjectName("secondaryButton")
        self.hash_raw_btn.setToolTip(
            "Slow: hashes every byte of the volume/disk. Needs Admin. "
            "A 32GB drive can take many minutes."
        )
        self.hash_raw_btn.clicked.connect(lambda: self.calculate_hash("raw"))
        self.cancel_hash_btn = QPushButton("Cancel Hash")
        self.cancel_hash_btn.setObjectName("secondaryButton")
        self.cancel_hash_btn.setEnabled(False)
        self.cancel_hash_btn.clicked.connect(self._cancel_hash)
        hash_row.addWidget(self.hash_btn)
        hash_row.addWidget(self.hash_raw_btn)
        hash_row.addWidget(self.cancel_hash_btn)
        action_layout.addLayout(hash_row)

        self.hash_progress = QProgressBar()
        self.hash_progress.setRange(0, 100)
        self.hash_progress.setValue(0)
        action_layout.addWidget(self.hash_progress)

        self.hash_result_label = QTextEdit()
        self.hash_result_label.setReadOnly(True)
        self.hash_result_label.setFont(QFont("Consolas", 10))
        self.hash_result_label.setPlainText("Hashes: (none yet)")
        self.hash_result_label.setMinimumHeight(120)
        self.hash_result_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        action_layout.addWidget(self.hash_result_label, stretch=1)

        self.match_label = QLabel("")
        self.match_label.setWordWrap(True)
        action_layout.addWidget(self.match_label)

        export_row = QHBoxLayout()
        export_btn = QPushButton("Export Report (.txt)")
        export_btn.setObjectName("secondaryButton")
        export_btn.clicked.connect(self.export_report)
        export_row.addWidget(export_btn)
        export_row.addStretch()
        action_layout.addLayout(export_row)

        right_layout.addWidget(action_box, stretch=1)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setWidget(right)
        right_scroll.setMinimumWidth(340)
        work_splitter.addWidget(right_scroll)
        work_splitter.setStretchFactor(0, 3)
        work_splitter.setStretchFactor(1, 2)
        work_splitter.setSizes([640, 440])

        # Audit log pane
        log_box = QGroupBox("Tamper-Evident Audit Log (append-only)")
        log_layout = QVBoxLayout(log_box)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 10))
        self.log_view.setMinimumHeight(80)
        log_layout.addWidget(self.log_view)
        chain = QLabel(f"Log file: {self.audit.log_path}")
        chain.setObjectName("subtitle")
        log_layout.addWidget(chain)
        main_splitter.addWidget(log_box)
        main_splitter.setStretchFactor(0, 3)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([520, 200])

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")
        self._set_actions_enabled(False)

    # ----------------------------------------------------------- case / log
    def _case_fields(self) -> dict[str, str]:
        return {
            "case_number": self.case_meta.case_number,
            "examiner_name": self.case_meta.examiner_name,
            "evidence_tag": self.case_meta.evidence_tag,
        }

    def _prompt_case_metadata(self, initial: bool) -> None:
        dlg = CaseMetadataDialog(self, self.case_meta)
        if dlg.exec():
            self.case_meta = dlg.metadata()
            self._update_case_summary()
            self._log(
                "CASE_METADATA",
                f"Case metadata set: case={self.case_meta.case_number}, "
                f"examiner={self.case_meta.examiner_name}, tag={self.case_meta.evidence_tag}",
            )
        elif initial and not self.case_meta.is_complete():
            QMessageBox.information(
                self,
                "Metadata recommended",
                "You can continue, but set case details before device operations.",
            )
            self._update_case_summary()

    def _update_case_summary(self) -> None:
        if self.case_meta.is_complete():
            self.case_summary.setText(
                f"Case {self.case_meta.case_number}  |  "
                f"Examiner: {self.case_meta.examiner_name}  |  "
                f"Tag: {self.case_meta.evidence_tag}  |  "
                f"{self.case_meta.started_at} ({self.case_meta.timezone_name})"
            )
        else:
            self.case_summary.setText("Case metadata incomplete — click Edit Case Metadata")

    def _log(self, action: str, detail: str, **extra: Any) -> None:
        serial = ""
        if self.selected:
            serial = self.selected.serial_number
        entry = self.audit.append(
            action,
            detail,
            device_serial=serial,
            extra=extra or None,
            **self._case_fields(),
        )
        self.log_view.append(f"[{entry.timestamp}] {entry.action}: {entry.detail}")

    # ----------------------------------------------------------- devices
    def refresh_devices(self) -> None:
        try:
            devices = list_removable_devices()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Device enumeration failed", str(exc))
            self._log("ERROR", f"Device enumeration failed: {exc}")
            return

        previous_serials = self._known_serials
        current_serials = {d.serial_number for d in devices}

        for serial in current_serials - previous_serials:
            match = next((d for d in devices if d.serial_number == serial), None)
            if match:
                self._log(
                    "DEVICE_CONNECTED",
                    f"Detected {match.display_name} serial={match.serial_number} "
                    f"size={match.size_human}",
                )
        for serial in previous_serials - current_serials:
            self._log("DEVICE_DISCONNECTED", f"Device serial={serial} no longer present")

        self._known_serials = current_serials
        self.devices = devices
        self._populate_tree()
        self.statusBar().showMessage(f"Found {len(devices)} removable/external device(s)")

    def _poll_device_changes(self) -> None:
        # Quiet refresh — avoid modal errors on transient WMI blips
        try:
            devices = list_removable_devices()
        except Exception:
            return
        serials = {d.serial_number for d in devices}
        if serials != self._known_serials:
            self.refresh_devices()
            return
        # Refresh protection status for selection
        if self.selected:
            still = next(
                (
                    d
                    for d in devices
                    if d.serial_number == self.selected.serial_number
                    and d.physical_disk_index == self.selected.physical_disk_index
                ),
                None,
            )
            if still:
                self.selected = still
                self._refresh_protection_indicator()

    def _populate_tree(self) -> None:
        selected_serial = self.selected.serial_number if self.selected else None
        self.device_tree.clear()
        reselect_item = None
        for device in self.devices:
            item = QTreeWidgetItem(
                [
                    ", ".join(device.drive_letters) or "—",
                    device.volume_label or "—",
                    device.model,
                    device.size_human,
                    device.serial_number,
                    device.interface_type,
                    device.filesystem or "—",
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, device.physical_disk_index)
            item.setData(1, Qt.ItemDataRole.UserRole, device.serial_number)
            self.device_tree.addTopLevelItem(item)
            if selected_serial and device.serial_number == selected_serial:
                reselect_item = item
        for i in range(self.device_tree.columnCount()):
            self.device_tree.resizeColumnToContents(i)
        if reselect_item:
            self.device_tree.setCurrentItem(reselect_item)
        else:
            # Selection lost (unplugged or empty list) — drop bind.
            self.selected = None
            self._armed_key = None
            self._clear_details()
            self._set_actions_enabled(False)
            self._update_bind_status()

    def _device_key(self, device: StorageDevice) -> tuple[int, str]:
        return (device.physical_disk_index, device.serial_number)

    def _is_armed(self, device: StorageDevice | None = None) -> bool:
        target = device or self.selected
        if not target or self._armed_key is None:
            return False
        return self._armed_key == self._device_key(target)

    def _set_armed(self, device: StorageDevice | None) -> None:
        self._armed_key = self._device_key(device) if device else None
        self._update_bind_status()

    def _update_bind_status(self) -> None:
        if self._is_armed(self.selected) and self.selected:
            self.bind_status.setText(
                f"Bound: {self.selected.serial_number}  ·  disk #{self.selected.physical_disk_index}"
            )
        elif self.selected:
            self.bind_status.setText("Selected — serial bind required on first action")
        else:
            self.bind_status.setText("No device bound")

    def _on_selection_changed(self) -> None:
        items = self.device_tree.selectedItems()
        if not items:
            self.selected = None
            self._clear_details()
            self._set_actions_enabled(False)
            self._update_bind_status()
            return
        item = items[0]
        index = item.data(0, Qt.ItemDataRole.UserRole)
        serial = item.data(1, Qt.ItemDataRole.UserRole)
        device = next(
            (
                d
                for d in self.devices
                if d.physical_disk_index == index and d.serial_number == serial
            ),
            None,
        )
        if not device:
            return
        ok, reason = is_safe_evidence_device(device)
        if not ok:
            QMessageBox.critical(self, "Blocked", reason)
            self.device_tree.clearSelection()
            return
        # Switching devices clears the prior bind.
        if self._armed_key is not None and self._armed_key != self._device_key(device):
            self._armed_key = None
        self.selected = device
        self._show_details(device)
        self._set_actions_enabled(True)
        self._refresh_protection_indicator()
        self._update_bind_status()

    def _show_details(self, device: StorageDevice) -> None:
        self.detail_labels["model"].setText(device.model)
        self.detail_labels["serial"].setText(device.serial_number)
        self.detail_labels["size"].setText(
            f"{device.size_human} ({device.size_bytes:,} bytes)"
        )
        self.detail_labels["letters"].setText(
            ", ".join(device.drive_letters) or "(none mounted)"
        )
        self.detail_labels["interface"].setText(device.interface_type)
        self.detail_labels["filesystem"].setText(device.filesystem or "Unknown")
        self.detail_labels["disk"].setText(str(device.physical_disk_index))

    def _clear_details(self) -> None:
        for label in self.detail_labels.values():
            label.setText("—")
        self.protect_status.setText("WRITE PROTECTION: —")
        self.protect_status.setObjectName("statusUnknown")
        self.protect_status.setStyle(self.protect_status.style())

    def _set_actions_enabled(self, enabled: bool) -> None:
        self.enable_btn.setEnabled(enabled)
        self.disable_btn.setEnabled(enabled)
        self.eject_btn.setEnabled(enabled)
        hashing = self._hash_worker is None
        self.hash_btn.setEnabled(enabled and hashing)
        self.hash_raw_btn.setEnabled(enabled and hashing)

    def _refresh_protection_indicator(self) -> None:
        if not self.selected:
            self._clear_details()
            return
        status = get_read_only_status(self.selected.physical_disk_index)
        self.selected.write_protected = status
        if status is True:
            self.protect_status.setText("WRITE PROTECTION: ON (READ-ONLY)")
            self.protect_status.setObjectName("statusProtected")
        elif status is False:
            self.protect_status.setText("WRITE PROTECTION: OFF (WRITABLE)")
            self.protect_status.setObjectName("statusUnprotected")
        else:
            self.protect_status.setText("WRITE PROTECTION: UNKNOWN (check admin rights)")
            self.protect_status.setObjectName("statusUnknown")
        # Force style refresh for dynamic objectName changes
        self.protect_status.style().unpolish(self.protect_status)
        self.protect_status.style().polish(self.protect_status)

    # ----------------------------------------------------------- confirm
    def _ensure_case(self) -> bool:
        if self.case_meta.is_complete():
            return True
        self._prompt_case_metadata(initial=False)
        return self.case_meta.is_complete()

    def _confirm_device(self, operation: str, *, require_serial: bool = False) -> bool:
        if not self.selected:
            return False
        ok, reason = is_safe_evidence_device(self.selected)
        if not ok:
            QMessageBox.critical(self, "Safety block", reason)
            return False
        # Serial once to bind; again only for high-risk ops (e.g. disable WP).
        need_serial = require_serial or not self._is_armed()
        mode = "serial" if need_serial else "ack"
        dlg = DeviceConfirmDialog(self, self.selected, operation, mode=mode)
        if not dlg.exec():
            return False
        if mode == "serial":
            self._set_armed(self.selected)
            self._log(
                "DEVICE_BOUND",
                f"Bound disk #{self.selected.physical_disk_index} "
                f"serial={self.selected.serial_number} for session operations",
            )
        return True

    # ----------------------------------------------------------- protect
    def enable_write_protection(self) -> None:
        if not self._ensure_case() or not self.selected:
            return
        if not self._confirm_device("ENABLE write protection (read-only)"):
            return
        if not is_admin():
            QMessageBox.critical(
                self,
                "Administrator required",
                "Write protection requires Administrator rights.\n"
                "Close 369box and run it as administrator (UAC).",
            )
            return
        result = set_write_protection(
            self.selected.physical_disk_index,
            True,
            drive_letters=self.selected.drive_letters,
        )
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        hist = f"[{stamp}] ENABLE — success={result.success} via {result.method}: {result.message}"
        self.protection_history.append(hist)
        self._log(
            "WRITE_PROTECT_ENABLE",
            result.message,
            method=result.method,
            success=result.success,
            write_blocked=result.write_blocked,
        )
        # Drive letter may briefly disappear during remount
        self.refresh_devices()
        self._refresh_protection_indicator()
        if result.success and result.write_blocked:
            QMessageBox.information(
                self,
                "Write protection ON",
                "Write protection enabled and verified — a test write was blocked.\n\n"
                "Close any File Explorer windows open to that drive if deletes still work.",
            )
        elif result.success:
            QMessageBox.information(
                self,
                "Write protection set",
                "Read-only attributes were set.\n\n" + result.message[:800],
            )
        else:
            QMessageBox.warning(self, "Write protection failed", result.message[:1200])

    def disable_write_protection(self) -> None:
        if not self._ensure_case() or not self.selected:
            return
        if not self._confirm_device(
            "DISABLE write protection (make writable)",
            require_serial=True,
        ):
            return
        if not is_admin():
            QMessageBox.critical(
                self,
                "Administrator required",
                "Disabling write protection requires Administrator rights.",
            )
            return
        result = set_write_protection(
            self.selected.physical_disk_index,
            False,
            drive_letters=self.selected.drive_letters,
        )
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        hist = f"[{stamp}] DISABLE — success={result.success} via {result.method}: {result.message}"
        self.protection_history.append(hist)
        self._log(
            "WRITE_PROTECT_DISABLE",
            result.message,
            method=result.method,
            success=result.success,
        )
        self.refresh_devices()
        self._refresh_protection_indicator()
        if not result.success:
            QMessageBox.warning(self, "Disable failed", result.message[:1200])
        else:
            QMessageBox.information(
                self,
                "Write protection OFF",
                "Write protection cleared. The device should be writable again.",
            )

    def safely_eject(self) -> None:
        if not self.selected:
            return
        if self._hash_worker is not None:
            QMessageBox.warning(
                self,
                "Hash in progress",
                "Cancel the hash before ejecting the drive.",
            )
            return
        if not self.selected.drive_letters:
            QMessageBox.warning(
                self,
                "No drive letter",
                "This device has no mount letter to eject.",
            )
            return

        letter = self.selected.drive_letters[0]
        wp_on = self.selected.write_protected is True
        if wp_on:
            choice = QMessageBox.question(
                self,
                "Write protection still ON",
                f"Write protection is still ON for {letter}.\n\n"
                "If you eject now, the stick may stay read-only next time you plug it in.\n"
                "Recommended: Disable Write Protection first, then eject.\n\n"
                "Eject anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if choice != QMessageBox.StandardButton.Yes:
                return
        else:
            if not self._confirm_device(f"Safely eject drive {letter}"):
                return

        result = eject_drive(letter)
        self._log(
            "DEVICE_EJECT",
            result.message,
            method=result.method,
            success=result.success,
            drive=letter,
        )
        if result.success:
            self._armed_key = None
            self.selected = None
            self._clear_details()
            self._set_actions_enabled(False)
            self._update_bind_status()
            self.refresh_devices()
            QMessageBox.information(
                self,
                "Eject",
                f"{result.message}\n\nYou can unplug the USB when Windows says it’s safe "
                "(or when the drive disappears from the list).",
            )
            self.statusBar().showMessage(f"Ejected {letter}")
        else:
            QMessageBox.warning(
                self,
                "Eject failed",
                result.message
                + "\n\nClose File Explorer windows for that drive and try again.",
            )

    # ----------------------------------------------------------- hashing
    def calculate_hash(self, mode: str = "filesystem") -> None:
        if not self._ensure_case() or not self.selected:
            return
        op = (
            "Calculate filesystem content hashes"
            if mode == "filesystem"
            else "Calculate RAW full-media hashes (slow)"
        )
        if not self._confirm_device(op):
            return
        if mode == "raw":
            gb = self.selected.size_bytes / (1024**3)
            if gb >= 4:
                proceed = QMessageBox.question(
                    self,
                    "Raw hash is slow",
                    f"This device is about {gb:.1f} GB.\n"
                    "A raw disk hash can take a long time and usually needs Admin.\n\n"
                    "Prefer “Calculate Hash (files)” for a quicker content hash.\n\n"
                    "Continue with raw hash anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if proceed != QMessageBox.StandardButton.Yes:
                    return

        label = "original" if self.baseline_hash is None else "verification"

        self.hash_btn.setEnabled(False)
        self.hash_raw_btn.setEnabled(False)
        self.cancel_hash_btn.setEnabled(True)
        self.hash_progress.setValue(0)
        self.match_label.setText("")
        self.statusBar().showMessage(f"Hashing ({mode})…")

        worker = HashWorker(self.selected, label, mode=mode, parent=self)
        self._hash_worker = worker
        worker.progress.connect(self._on_hash_progress)
        worker.finished_ok.connect(self._on_hash_done)
        worker.failed.connect(self._on_hash_failed)
        worker.start()
        self._log(
            "HASH_START",
            f"Started {label} {mode} hash of disk #{self.selected.physical_disk_index}",
        )

    def _cancel_hash(self) -> None:
        if self._hash_worker:
            self._hash_worker.cancel()
            self.statusBar().showMessage("Cancelling hash…")

    def _on_hash_progress(self, read: int, total: int) -> None:
        if total > 0:
            pct = min(100, int(read * 100 / total))
            self.hash_progress.setRange(0, 100)
            self.hash_progress.setValue(pct)
            self.statusBar().showMessage(
                f"Hashing… {format_bytes(read)} / {format_bytes(total)} ({pct}%)"
            )
        else:
            # Scanning / sizing files before byte progress is known
            self.hash_progress.setRange(0, 0)
            if read > 0:
                self.statusBar().showMessage(f"Scanning drive… {read:,} files found")
            else:
                self.statusBar().showMessage("Scanning drive for files…")

    def _on_hash_done(self, result: object) -> None:
        assert isinstance(result, HashResult)
        self.hash_progress.setRange(0, 100)
        self.hash_progress.setValue(100)
        self.cancel_hash_btn.setEnabled(False)
        self._hash_worker = None
        self._set_actions_enabled(self.selected is not None)

        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        record = {
            "timestamp": stamp,
            "label": result.label if self.baseline_hash else "original/baseline",
            "md5": result.md5,
            "sha1": result.sha1,
            "sha256": result.sha256,
            "bytes_hashed": result.bytes_hashed,
            "source": result.source,
            "mode": getattr(result, "mode", "raw"),
        }
        self.hash_history.append(record)

        display_label = record["label"]
        mode = getattr(result, "mode", "raw")
        source = str(result.source)
        if mode == "raw":
            mode_note = "raw device"
        elif "fallback after raw error" in source:
            mode_note = (
                "filesystem content (raw access failed — run as Admin for full-disk hash)"
            )
        else:
            mode_note = "filesystem content"
        self.hash_result_label.setPlainText(
            f"Hashes ({display_label}) — {mode_note}:\n"
            f"MD5:     {result.md5}\n"
            f"SHA-1:   {result.sha1}\n"
            f"SHA-256: {result.sha256}\n"
            f"Bytes:   {result.bytes_hashed:,}\n"
            f"Source:  {result.source}"
        )

        log_label = "original/baseline" if self.baseline_hash is None else "verification"
        self._log(
            "HASH_CALCULATED",
            f"{log_label} MD5={result.md5} SHA1={result.sha1} SHA256={result.sha256}",
            **record,
        )

        if self.baseline_hash is None:
            self.baseline_hash = result
            self.match_label.setText("Baseline (original) hash stored for this session.")
            self.match_label.setObjectName("")
        else:
            comparison = compare_hashes(self.baseline_hash, result)
            self._last_comparison = comparison
            if comparison["all"]:
                self.match_label.setText("✅ MATCH — all hashes identical to baseline")
                self.match_label.setObjectName("matchOk")
            else:
                parts = [
                    f"{k.upper()}: {'✅' if v else '❌'}"
                    for k, v in comparison.items()
                    if k != "all"
                ]
                self.match_label.setText("❌ MISMATCH — " + "  ".join(parts))
                self.match_label.setObjectName("matchBad")
            self.match_label.style().unpolish(self.match_label)
            self.match_label.style().polish(self.match_label)
            self._log(
                "HASH_COMPARE",
                "MATCH" if comparison["all"] else "MISMATCH",
                comparison=comparison,
            )

        self.statusBar().showMessage("Hash complete")

    def _on_hash_failed(self, message: str) -> None:
        self.hash_progress.setRange(0, 100)
        self.hash_progress.setValue(0)
        self.cancel_hash_btn.setEnabled(False)
        self._hash_worker = None
        self._set_actions_enabled(self.selected is not None)
        self._log("HASH_ERROR", message)
        self.statusBar().showMessage("Hash failed")
        QMessageBox.critical(self, "Hash failed", message)

    # ----------------------------------------------------------- report
    def export_report(self) -> None:
        if not self._ensure_case():
            return
        default_name = (
            f"369box_report_{self.case_meta.case_number}_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export forensic report",
            str(Path.home() / "Documents" / "369box" / default_name),
            "Text reports (*.txt)",
        )
        if not path:
            return
        device_info = self.selected.to_dict() if self.selected else None
        out = self.audit.export_report(
            Path(path),
            case_meta=self.case_meta.to_dict(),
            device_info=device_info,
            hashes=self.hash_history,
            protection_history=self.protection_history,
            hash_comparison=self._last_comparison,
        )
        self._log("REPORT_EXPORTED", f"Report written to {out}")
        QMessageBox.information(
            self,
            "Report exported",
            f"Report saved to:\n{out}\n\nSHA-256 sidecar: {out}.sha256",
        )

    def closeEvent(self, event) -> None:  # noqa: N802
        self._log("SESSION_END", "369box session closed.")
        if self._hash_worker and self._hash_worker.isRunning():
            self._hash_worker.cancel()
            self._hash_worker.wait(2000)
        super().closeEvent(event)
