"""Removable / external storage detection with system-disk exclusion."""

from __future__ import annotations

import os
import string
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

import psutil

# DriveType constants from Win32_LogicalDisk
DRIVE_UNKNOWN = 0
DRIVE_NO_ROOT = 1
DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
DRIVE_CDROM = 5
DRIVE_RAMDISK = 6


@dataclass
class StorageDevice:
    """A selectable evidence storage device (never the system disk)."""

    physical_disk_index: int
    drive_letters: list[str] = field(default_factory=list)
    volume_label: str = ""
    model: str = ""
    size_bytes: int = 0
    serial_number: str = ""
    interface_type: str = "Unknown"
    filesystem: str = ""
    media_type: str = ""
    pnp_device_id: str = ""
    is_removable: bool = True
    write_protected: bool | None = None

    @property
    def display_name(self) -> str:
        letters = ", ".join(self.drive_letters) if self.drive_letters else "(no letter)"
        label = self.volume_label or "NO LABEL"
        return f"{letters} — {label} — {self.model}"

    @property
    def size_human(self) -> str:
        return format_bytes(self.size_bytes)

    @property
    def primary_mount(self) -> str | None:
        if not self.drive_letters:
            return None
        letter = self.drive_letters[0].rstrip(":\\/")
        return f"{letter}:\\"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["size_human"] = self.size_human
        data["display_name"] = self.display_name
        return data


def format_bytes(num: int) -> str:
    if num <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    value = float(num)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{num} B"


def _wmi():
    import win32com.client

    return win32com.client.GetObject("winmgmts:")


def get_system_drive_letter() -> str:
    drive = os.environ.get("SystemDrive", "C:")
    return drive[0].upper()


def get_system_physical_disk_indexes(wmi=None) -> set[int]:
    """Physical disk indexes that host the Windows system volume."""
    wmi = wmi or _wmi()
    system_letter = get_system_drive_letter()
    indexes: set[int] = set()

    for logical in wmi.InstancesOf("Win32_LogicalDisk"):
        device_id = (logical.DeviceID or "").upper()
        if not device_id.startswith(system_letter):
            continue
        for rel in wmi.AssociatorsOf(
            logical.Path_.Path,
            strAssocClass="Win32_LogicalDiskToPartition",
        ):
            for disk in wmi.AssociatorsOf(
                rel.Path_.Path,
                strAssocClass="Win32_DiskDriveToDiskPartition",
            ):
                try:
                    indexes.add(int(disk.Index))
                except (TypeError, ValueError, AttributeError):
                    continue

    # Fallback: disk 0 is almost always the boot disk on consumer PCs
    if not indexes:
        indexes.add(0)
    return indexes


def _interface_from_pnp(pnp_id: str, interface_type: str | None) -> str:
    pnp = (pnp_id or "").upper()
    iface = (interface_type or "").strip()
    if iface:
        return iface
    if "USBSTOR" in pnp or "\\USB\\" in pnp:
        return "USB"
    if "SCSI" in pnp and "SD" in pnp:
        return "SD"
    if "SD\\" in pnp or "SDBUS" in pnp:
        return "SD"
    return "Other"


def _is_external_candidate(
    *,
    interface: str,
    media_type: str,
    pnp_id: str,
    drive_types: Iterable[int],
) -> bool:
    """Return True if this physical disk looks like removable/external evidence media."""
    iface = interface.upper()
    media = (media_type or "").upper()
    pnp = (pnp_id or "").upper()
    types = set(drive_types)

    if DRIVE_REMOVABLE in types:
        return True
    if "USB" in iface or "USBSTOR" in pnp or "\\USB\\" in pnp:
        return True
    if "SD" in iface or "SDBUS" in pnp or "CARD" in media:
        return True
    if "REMOVABLE" in media or "EXTERNAL" in media:
        return True
    return False


def _logical_info_for_disk(wmi, disk_index: int) -> tuple[list[str], str, str, set[int]]:
    letters: list[str] = []
    label = ""
    filesystem = ""
    drive_types: set[int] = set()

    disk_path = None
    for disk in wmi.InstancesOf("Win32_DiskDrive"):
        try:
            if int(disk.Index) == disk_index:
                disk_path = disk.Path_.Path
                break
        except (TypeError, ValueError, AttributeError):
            continue
    if not disk_path:
        return letters, label, filesystem, drive_types

    partitions = list(
        wmi.AssociatorsOf(disk_path, strAssocClass="Win32_DiskDriveToDiskPartition")
    )
    for partition in partitions:
        logicals = list(
            wmi.AssociatorsOf(
                partition.Path_.Path,
                strAssocClass="Win32_LogicalDiskToPartition",
            )
        )
        for logical in logicals:
            device_id = (logical.DeviceID or "").upper()
            if device_id:
                letters.append(device_id if device_id.endswith(":") else f"{device_id}:")
            if not label:
                label = (logical.VolumeName or "") or ""
            if not filesystem:
                filesystem = (logical.FileSystem or "") or ""
            try:
                drive_types.add(int(logical.DriveType))
            except (TypeError, ValueError):
                pass

    # Stable order by letter
    letters = sorted(set(letters), key=lambda x: x[0])
    return letters, label, filesystem, drive_types


def list_removable_devices() -> list[StorageDevice]:
    """
    Enumerate removable/external storage devices.

    Permanently excludes the system/boot physical disk and any disk that
    mounts the system drive letter. Only removable/external candidates are returned.
    """
    wmi = _wmi()
    system_indexes = get_system_physical_disk_indexes(wmi)
    system_letter = get_system_drive_letter()
    devices: list[StorageDevice] = []

    for disk in wmi.InstancesOf("Win32_DiskDrive"):
        try:
            index = int(disk.Index)
        except (TypeError, ValueError, AttributeError):
            continue

        # Layer 1: never expose system/boot physical disks
        if index in system_indexes:
            continue

        size_bytes = int(getattr(disk, "Size", 0) or 0)
        model = (getattr(disk, "Model", None) or "Unknown Disk").strip()
        serial = (getattr(disk, "SerialNumber", None) or "").strip() or "UNKNOWN"
        media_type = (getattr(disk, "MediaType", None) or "").strip()
        pnp_id = (getattr(disk, "PNPDeviceID", None) or "").strip()
        interface = _interface_from_pnp(
            pnp_id, getattr(disk, "InterfaceType", None)
        )

        letters, label, filesystem, drive_types = _logical_info_for_disk(wmi, index)

        # Layer 2: exclude anything that mounts the system letter
        if any(letter.upper().startswith(system_letter) for letter in letters):
            continue

        # Layer 3: only removable / external interface candidates
        if not _is_external_candidate(
            interface=interface,
            media_type=media_type,
            pnp_id=pnp_id,
            drive_types=drive_types,
        ):
            continue

        # Layer 4: skip empty / optical-only noise
        if DRIVE_CDROM in drive_types and DRIVE_REMOVABLE not in drive_types:
            if "USB" not in interface.upper():
                continue

        devices.append(
            StorageDevice(
                physical_disk_index=index,
                drive_letters=letters,
                volume_label=label,
                model=model,
                size_bytes=size_bytes,
                serial_number=serial,
                interface_type=interface,
                filesystem=filesystem or _probe_filesystem(letters),
                media_type=media_type,
                pnp_device_id=pnp_id,
                is_removable=DRIVE_REMOVABLE in drive_types or "USB" in interface.upper(),
            )
        )

    devices.sort(key=lambda d: (d.drive_letters[:1], d.physical_disk_index))
    return devices


def _probe_filesystem(letters: list[str]) -> str:
    for letter in letters:
        root = f"{letter.rstrip(':')}:\\"
        try:
            usage = psutil.disk_usage(root)
            # psutil doesn't give FS type; try WinAPI via ctypes fallback below
            _ = usage
        except Exception:
            continue
        try:
            import ctypes

            buf = ctypes.create_unicode_buffer(32)
            root_path = root if root.endswith("\\") else root + "\\"
            ok = ctypes.windll.kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(root_path),
                None,
                0,
                None,
                None,
                None,
                buf,
                len(buf),
            )
            if ok and buf.value:
                return buf.value
        except Exception:
            continue
    return ""


def is_safe_evidence_device(device: StorageDevice) -> tuple[bool, str]:
    """Second-line safety check before any operation."""
    system_letter = get_system_drive_letter()
    if device.physical_disk_index in get_system_physical_disk_indexes():
        return False, "Device is the system/boot disk and cannot be used."
    if any(l.upper().startswith(system_letter) for l in device.drive_letters):
        return False, "Device mounts the system drive letter and cannot be used."
    if device.physical_disk_index < 0:
        return False, "Invalid physical disk index."
    return True, "OK"


def connected_drive_letters() -> set[str]:
    """Currently present drive letters (A–Z)."""
    present: set[str] = set()
    bitmask = ctypes_get_drives()
    for i, letter in enumerate(string.ascii_uppercase):
        if bitmask & (1 << i):
            present.add(f"{letter}:")
    return present


def ctypes_get_drives() -> int:
    import ctypes

    return int(ctypes.windll.kernel32.GetLogicalDrives())
