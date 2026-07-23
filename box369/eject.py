"""Safely eject removable volumes (Windows Shell + storage IOCTL fallback)."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

# STORAGE base 0x2D
IOCTL_STORAGE_MEDIA_REMOVAL = 0x002D4804
IOCTL_STORAGE_EJECT_MEDIA = 0x002D4808

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
class EjectResult:
    success: bool
    message: str
    method: str = ""


def _normalize_letter(letter: str) -> str:
    cleaned = letter.strip().rstrip("\\/")
    if len(cleaned) >= 2 and cleaned[1] == ":":
        return cleaned[:2].upper()
    if len(cleaned) == 1 and cleaned.isalpha():
        return f"{cleaned.upper()}:"
    raise ValueError(f"Invalid drive letter: {letter!r}")


def _eject_via_shell(letter: str) -> EjectResult:
    """Ask Explorer to eject the drive (same as taskbar Safely Remove)."""
    try:
        import win32com.client  # type: ignore
    except ImportError:
        return EjectResult(False, "pywin32 (win32com) is not available.", "shell")

    drive = _normalize_letter(letter)
    try:
        shell = win32com.client.Dispatch("Shell.Application")
        computer = shell.NameSpace(17)  # This PC / My Computer
        if computer is None:
            return EjectResult(False, "Could not open This PC namespace.", "shell")
        item = computer.ParseName(drive)
        if item is None:
            return EjectResult(False, f"Drive {drive} not found in Explorer.", "shell")
        item.InvokeVerb("Eject")
        return EjectResult(True, f"Eject requested for {drive} via Explorer.", "shell")
    except Exception as exc:  # noqa: BLE001
        return EjectResult(False, f"Shell eject failed: {exc}", "shell")


def _eject_via_ioctl(letter: str) -> EjectResult:
    """Fallback: unlock media removal + eject IOCTL on \\\\.\\X:."""
    drive = _normalize_letter(letter)
    path = f"\\\\.\\{drive}"
    handle = kernel32.CreateFileW(
        path,
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle == INVALID_HANDLE_VALUE or handle is None:
        err = ctypes.get_last_error()
        return EjectResult(
            False,
            f"Could not open {path} for eject (WinError {err}). "
            "Close File Explorer windows for that drive and try again.",
            "ioctl",
        )

    returned = wintypes.DWORD(0)
    try:
        # FALSE = allow removal
        prevent = wintypes.BOOLEAN(0)
        kernel32.DeviceIoControl(
            handle,
            IOCTL_STORAGE_MEDIA_REMOVAL,
            ctypes.byref(prevent),
            ctypes.sizeof(prevent),
            None,
            0,
            ctypes.byref(returned),
            None,
        )
        ok = kernel32.DeviceIoControl(
            handle,
            IOCTL_STORAGE_EJECT_MEDIA,
            None,
            0,
            None,
            0,
            ctypes.byref(returned),
            None,
        )
        if not ok:
            err = ctypes.get_last_error()
            return EjectResult(
                False,
                f"IOCTL eject failed for {drive} (WinError {err}). "
                "A program may still be using the drive.",
                "ioctl",
            )
        return EjectResult(True, f"Eject issued for {drive} via storage IOCTL.", "ioctl")
    finally:
        kernel32.CloseHandle(handle)


def eject_drive(letter: str) -> EjectResult:
    """
    Safely eject a mounted volume.

    Tries Explorer's Eject verb first, then storage IOCTL.
    """
    drive = _normalize_letter(letter)
    shell = _eject_via_shell(drive)
    if shell.success:
        time.sleep(0.6)
        return shell

    ioctl = _eject_via_ioctl(drive)
    if ioctl.success:
        time.sleep(0.6)
        return ioctl

    return EjectResult(
        False,
        shell.message + "\n" + ioctl.message,
        "shell+ioctl",
    )
