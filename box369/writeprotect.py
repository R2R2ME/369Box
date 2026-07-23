"""OS-level disk/volume write protection via IOCTL + DiskPart + remount."""

from __future__ import annotations

import ctypes
import os
import subprocess
import tempfile
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Optional

# Win32 constants
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_FLAG_NO_BUFFERING = 0x20000000
FILE_FLAG_RANDOM_ACCESS = 0x10000000

IOCTL_DISK_BASE = 0x00000007
METHOD_BUFFERED = 0
FILE_ANY_ACCESS = 0
FILE_READ_ACCESS = 0x0001
FILE_WRITE_ACCESS = 0x0002

DISK_ATTRIBUTE_OFFLINE = 0x0000000000000001
DISK_ATTRIBUTE_READ_ONLY = 0x0000000000000002


def _ctl_code(device_type: int, function: int, method: int, access: int) -> int:
    return (device_type << 16) | (access << 14) | (function << 2) | method


IOCTL_DISK_GET_DISK_ATTRIBUTES = _ctl_code(
    IOCTL_DISK_BASE, 0x003C, METHOD_BUFFERED, FILE_ANY_ACCESS
)
IOCTL_DISK_SET_DISK_ATTRIBUTES = _ctl_code(
    IOCTL_DISK_BASE, 0x003D, METHOD_BUFFERED, FILE_READ_ACCESS | FILE_WRITE_ACCESS
)
IOCTL_DISK_UPDATE_PROPERTIES = _ctl_code(
    IOCTL_DISK_BASE, 0x0050, METHOD_BUFFERED, FILE_ANY_ACCESS
)

# FSCTL codes for volume lock/dismount
FILE_DEVICE_FILE_SYSTEM = 0x00000009
FSCTL_LOCK_VOLUME = _ctl_code(FILE_DEVICE_FILE_SYSTEM, 6, METHOD_BUFFERED, FILE_ANY_ACCESS)
FSCTL_UNLOCK_VOLUME = _ctl_code(FILE_DEVICE_FILE_SYSTEM, 7, METHOD_BUFFERED, FILE_ANY_ACCESS)
FSCTL_DISMOUNT_VOLUME = _ctl_code(FILE_DEVICE_FILE_SYSTEM, 8, METHOD_BUFFERED, FILE_ANY_ACCESS)


class GET_DISK_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Version", wintypes.DWORD),
        ("Reserved1", wintypes.DWORD),
        ("Attributes", ctypes.c_uint64),
    ]


class SET_DISK_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Version", wintypes.DWORD),
        ("Persist", wintypes.BOOLEAN),
        ("Reserved1", ctypes.c_ubyte * 3),
        ("Attributes", ctypes.c_uint64),
        ("AttributesMask", ctypes.c_uint64),
        ("Reserved2", wintypes.DWORD * 4),
    ]


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
]
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.DeviceIoControl.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    wintypes.LPVOID,
]
kernel32.DeviceIoControl.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


@dataclass
class WriteProtectResult:
    success: bool
    method: str
    message: str
    read_only: bool | None = None
    write_blocked: bool | None = None


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def request_elevation(script_path: str) -> bool:
    """Relaunch this script elevated via UAC. Returns True if launch was attempted."""
    try:
        params = f'"{script_path}"'
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys_executable(), params, None, 1
        )
        return rc > 32
    except Exception:
        return False


def sys_executable() -> str:
    import sys

    return sys.executable


def _open_physical_drive(disk_index: int, write_access: bool) -> wintypes.HANDLE:
    path = f"\\\\.\\PhysicalDrive{disk_index}"
    access = GENERIC_READ | (GENERIC_WRITE if write_access else 0)
    handle = kernel32.CreateFileW(
        path,
        access,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if handle == INVALID_HANDLE_VALUE or handle is None:
        err = ctypes.get_last_error()
        raise OSError(err, f"CreateFileW failed for {path} (WinError {err})")
    return handle


def get_read_only_status(disk_index: int) -> Optional[bool]:
    """Return True if disk is read-only, False if writable, None if unknown."""
    handle = None
    try:
        handle = _open_physical_drive(disk_index, write_access=False)
        attrs = GET_DISK_ATTRIBUTES()
        attrs.Version = ctypes.sizeof(GET_DISK_ATTRIBUTES)
        returned = wintypes.DWORD(0)
        ok = kernel32.DeviceIoControl(
            handle,
            IOCTL_DISK_GET_DISK_ATTRIBUTES,
            None,
            0,
            ctypes.byref(attrs),
            ctypes.sizeof(attrs),
            ctypes.byref(returned),
            None,
        )
        if not ok:
            return None
        return bool(attrs.Attributes & DISK_ATTRIBUTE_READ_ONLY)
    except OSError:
        return None
    finally:
        if handle not in (None, INVALID_HANDLE_VALUE):
            kernel32.CloseHandle(handle)


def _set_read_only_ioctl(disk_index: int, enable: bool, persist: bool = True) -> None:
    handle = None
    try:
        handle = _open_physical_drive(disk_index, write_access=True)
        req = SET_DISK_ATTRIBUTES()
        req.Version = ctypes.sizeof(SET_DISK_ATTRIBUTES)
        req.Persist = 1 if persist else 0
        req.AttributesMask = DISK_ATTRIBUTE_READ_ONLY
        req.Attributes = DISK_ATTRIBUTE_READ_ONLY if enable else 0
        returned = wintypes.DWORD(0)
        ok = kernel32.DeviceIoControl(
            handle,
            IOCTL_DISK_SET_DISK_ATTRIBUTES,
            ctypes.byref(req),
            ctypes.sizeof(req),
            None,
            0,
            ctypes.byref(returned),
            None,
        )
        if not ok:
            err = ctypes.get_last_error()
            raise OSError(err, f"SET_DISK_ATTRIBUTES failed (WinError {err})")

        # Nudge the partition manager to re-read attributes
        kernel32.DeviceIoControl(
            handle,
            IOCTL_DISK_UPDATE_PROPERTIES,
            None,
            0,
            None,
            0,
            ctypes.byref(returned),
            None,
        )
    finally:
        if handle not in (None, INVALID_HANDLE_VALUE):
            kernel32.CloseHandle(handle)


def _run_diskpart(script_body: str) -> tuple[bool, str]:
    fd, path = tempfile.mkstemp(prefix="369box_diskpart_", suffix=".txt", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\r\n") as fh:
            fh.write(script_body)
            if not script_body.endswith("\n"):
                fh.write("\n")
        proc = subprocess.run(
            ["diskpart", "/s", path],
            capture_output=True,
            text=True,
            timeout=90,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        output = ((proc.stdout or "") + (proc.stderr or "")).strip()
        lowered = output.lower()
        # DiskPart often exits 0 even when a command failed — parse output.
        failed = (
            proc.returncode != 0
            or "has encountered an error" in lowered
            or "access is denied" in lowered
            or "invalid" in lowered
            and "selected" not in lowered
        )
        # Soft-fail heuristics: look for clear denial
        if "access is denied" in lowered or "access denied" in lowered:
            failed = True
        return (not failed), output
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _diskpart_set_disk_readonly(disk_index: int, enable: bool) -> tuple[bool, str]:
    action = "set readonly" if enable else "clear readonly"
    script = (
        f"select disk {disk_index}\n"
        f"attributes disk {action}\n"
        f"detail disk\n"
    )
    return _run_diskpart(script)


def _diskpart_set_volumes_readonly(
    disk_index: int, drive_letters: list[str], enable: bool
) -> tuple[bool, str]:
    """Set/clear readonly on volumes belonging to the disk (by drive letter)."""
    action = "set readonly" if enable else "clear readonly"
    parts = [f"select disk {disk_index}", "detail disk"]
    # DiskPart can't always map letter→volume in one shot; select by letter via volume list.
    # Using: select volume D
    for letter in drive_letters:
        vol = letter.rstrip(":\\/").upper()
        if not vol:
            continue
        parts.append(f"select volume {vol}")
        parts.append(f"attributes volume {action}")
        parts.append("detail volume")
    ok, output = _run_diskpart("\n".join(parts) + "\n")
    return ok, output


def _dismount_volume(letter: str) -> tuple[bool, str]:
    """
    Lock + dismount a volume so the filesystem remounts and picks up new
    read-only disk/volume attributes. Critical — without this, Explorer can
    keep writing even after attributes disk set readonly.
    """
    root = letter.rstrip(":\\/")
    if not root:
        return False, "empty letter"
    path = f"\\\\.\\{root}:"
    handle = kernel32.CreateFileW(
        path,
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if handle == INVALID_HANDLE_VALUE or handle is None:
        err = ctypes.get_last_error()
        return False, f"open {path} failed WinError {err}"

    try:
        returned = wintypes.DWORD(0)
        # Best-effort lock (may fail if files open — still try dismount)
        kernel32.DeviceIoControl(
            handle, FSCTL_LOCK_VOLUME, None, 0, None, 0, ctypes.byref(returned), None
        )
        ok = kernel32.DeviceIoControl(
            handle, FSCTL_DISMOUNT_VOLUME, None, 0, None, 0, ctypes.byref(returned), None
        )
        if not ok:
            err = ctypes.get_last_error()
            return False, f"dismount {path} failed WinError {err}"
        kernel32.DeviceIoControl(
            handle, FSCTL_UNLOCK_VOLUME, None, 0, None, 0, ctypes.byref(returned), None
        )
        return True, f"dismounted {path}"
    finally:
        kernel32.CloseHandle(handle)


def test_write_blocked(mount_path: str) -> tuple[bool, str]:
    """
    Attempt a tiny write on the mounted volume.
    Returns (blocked, detail). blocked=True means the write failed (protection working).
    """
    if not mount_path:
        return False, "No mount path available for write test."

    root = mount_path if mount_path.endswith("\\") else mount_path + "\\"
    # Give remount a moment after dismount
    time.sleep(0.4)
    if not os.path.exists(root):
        time.sleep(1.0)
    if not os.path.exists(root):
        # Volume not visible — treat as blocked from Explorer's perspective
        return True, f"Volume {root} not accessible after protect (likely dismounted/blocked)."

    test_name = os.path.join(root, ".__369box_write_test__.tmp")
    try:
        with open(test_name, "wb") as fh:
            fh.write(b"369box-write-test")
        try:
            os.remove(test_name)
        except OSError:
            pass
        return False, f"Test write SUCCEEDED at {test_name} — device is NOT write-blocked."
    except OSError as exc:
        return True, f"Test write FAILED as expected ({exc}) — write protection appears active."
    except Exception as exc:  # noqa: BLE001
        return True, f"Test write raised {type(exc).__name__}: {exc}"


def set_write_protection(
    disk_index: int,
    enable: bool,
    drive_letters: list[str] | None = None,
) -> WriteProtectResult:
    """
    Enable or disable OS-level read-only on a physical disk and its volumes.

    Sequence (enable):
      1. IOCTL_DISK_SET_DISK_ATTRIBUTES (read-only)
      2. DiskPart: attributes disk set readonly
      3. DiskPart: attributes volume set readonly (each letter)
      4. Dismount volumes so the FS remounts with new attributes
      5. Verify with a real write test when enabling
    """
    if not is_admin():
        return WriteProtectResult(
            success=False,
            method="none",
            message=(
                "Administrator privileges are required. "
                "Close 369box and relaunch via 'Run as administrator'."
            ),
            read_only=None,
            write_blocked=None,
        )

    letters = [L for L in (drive_letters or []) if L]
    notes: list[str] = []
    methods: list[str] = []

    # 1) IOCTL
    try:
        _set_read_only_ioctl(disk_index, enable)
        methods.append("IOCTL")
        notes.append("IOCTL disk read-only attribute set.")
    except OSError as exc:
        notes.append(f"IOCTL failed: {exc}")

    # 2) DiskPart disk attribute
    ok_disk, out_disk = _diskpart_set_disk_readonly(disk_index, enable)
    methods.append("diskpart-disk")
    notes.append(f"DiskPart disk: {'OK' if ok_disk else 'FAIL'}\n{out_disk}")

    # 3) DiskPart volume attribute
    if letters:
        ok_vol, out_vol = _diskpart_set_volumes_readonly(disk_index, letters, enable)
        methods.append("diskpart-volume")
        notes.append(f"DiskPart volume: {'OK' if ok_vol else 'FAIL'}\n{out_vol}")

    # 4) Force remount so Explorer honors the new flags
    if letters:
        for letter in letters:
            ok_dm, msg_dm = _dismount_volume(letter)
            notes.append(f"Remount {letter}: {'OK' if ok_dm else 'FAIL'} — {msg_dm}")
            methods.append("dismount")
        time.sleep(0.8)

    status = get_read_only_status(disk_index)
    write_blocked: bool | None = None

    if enable and letters:
        mount = letters[0]
        root = mount if mount.endswith("\\") else (mount.rstrip(":\\/") + ":\\")
        write_blocked, test_detail = test_write_blocked(root)
        notes.append(test_detail)
        if not write_blocked:
            return WriteProtectResult(
                success=False,
                method="+".join(methods) or "unknown",
                message=(
                    "Read-only flags were set, but a test write still SUCCEEDED. "
                    "Windows is still allowing deletes/writes on the mounted volume.\n\n"
                    "Try: close File Explorer windows for that drive, then Enable again.\n"
                    "Software write-blocking is not 100% reliable — use a hardware blocker for real evidence.\n\n"
                    + "\n".join(notes)
                ),
                read_only=status,
                write_blocked=False,
            )

    # Consider success if diskpart disk OK, or IOCTL OK, or (when enabling) write actually blocked
    attr_ok = ok_disk or ("IOCTL" in methods and status is True)
    if enable:
        success = bool(write_blocked) or (attr_ok and status is True)
        # If we couldn't test (no letters) but attributes say RO, soft-success
        if not letters and status is True:
            success = True
        if write_blocked:
            success = True
    else:
        success = attr_ok or status is False

    action = "ENABLED" if enable else "DISABLED"
    return WriteProtectResult(
        success=success,
        method="+".join(dict.fromkeys(methods)) or "unknown",
        message=f"Write protection {action}.\n" + "\n".join(notes),
        read_only=status if status is not None else enable,
        write_blocked=write_blocked,
    )
