"""Single-pass multi-algorithm hashing of storage devices."""

from __future__ import annotations

import ctypes
import hashlib
import os
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable

ProgressCallback = Callable[[int, int], None]  # bytes_read, total_bytes
CancelCallback = Callable[[], bool]

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000

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
kernel32.ReadFile.argtypes = [
    wintypes.HANDLE,
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    wintypes.LPVOID,
]
kernel32.ReadFile.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.GetFileSizeEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_int64)]
kernel32.GetFileSizeEx.restype = wintypes.BOOL


@dataclass
class HashResult:
    md5: str
    sha1: str
    sha256: str
    bytes_hashed: int
    source: str
    label: str  # "original" / "baseline" / "verification"
    mode: str = "raw"  # "raw" or "filesystem"


class DeviceFile:
    """Thin ReadFile wrapper around a Win32 device handle."""

    def __init__(self, handle: wintypes.HANDLE, path: str) -> None:
        self.handle = handle
        self.path = path

    def read(self, size: int) -> bytes:
        buf = (ctypes.c_char * size)()
        read = wintypes.DWORD(0)
        ok = kernel32.ReadFile(self.handle, buf, size, ctypes.byref(read), None)
        if not ok:
            err = ctypes.get_last_error()
            # ERROR_SECTOR_NOT_FOUND / end-ish conditions
            if err in (38, 87, 21, 1117):  # EOF, invalid param, not ready, CRC
                return b""
            raise OSError(err, f"ReadFile failed on {self.path} (WinError {err})")
        if read.value == 0:
            return b""
        return bytes(buf[: read.value])

    def close(self) -> None:
        if self.handle not in (None, INVALID_HANDLE_VALUE):
            kernel32.CloseHandle(self.handle)
            self.handle = INVALID_HANDLE_VALUE


def _open_device(path: str) -> DeviceFile:
    handle = kernel32.CreateFileW(
        path,
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    if handle == INVALID_HANDLE_VALUE or handle is None:
        err = ctypes.get_last_error()
        raise OSError(err, f"CreateFileW failed for {path} (WinError {err})")
    return DeviceFile(handle, path)


def _open_hash_source(physical_disk_index: int, mount_path: str | None) -> DeviceFile:
    """
    Prefer the mounted volume (\\\\.\\X:) — works more often while Explorer has
    the drive open. Fall back to \\\\.\\PhysicalDriveN (usually needs admin).
    """
    candidates: list[str] = []
    if mount_path:
        letter = mount_path.rstrip("\\/")
        if len(letter) >= 2 and letter[1] == ":":
            candidates.append(f"\\\\.\\{letter[:2]}")
    candidates.append(f"\\\\.\\PhysicalDrive{physical_disk_index}")

    errors: list[str] = []
    for path in candidates:
        try:
            return _open_device(path)
        except OSError as exc:
            errors.append(f"{path}: {exc}")
            continue
    raise OSError(
        "Unable to open device for raw hashing.\n" + "\n".join(errors)
    )


def _volume_total_bytes(mount_path: str | None, fallback: int) -> int:
    if not mount_path:
        return fallback
    root = mount_path if mount_path.endswith("\\") else mount_path.rstrip(":\\/") + ":\\"
    try:
        free = ctypes.c_ulonglong(0)
        total = ctypes.c_ulonglong(0)
        ok = ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            ctypes.c_wchar_p(root),
            None,
            ctypes.byref(total),
            ctypes.byref(free),
        )
        if ok and total.value > 0:
            return int(total.value)
    except Exception:
        pass
    return fallback


def hash_device(
    physical_disk_index: int,
    size_bytes: int,
    mount_path: str | None = None,
    *,
    label: str = "original",
    chunk_size: int = 1024 * 1024,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
    mode: str = "auto",
) -> HashResult:
    """
    Compute MD5, SHA-1, and SHA-256 in a single pass.

    mode:
      - "filesystem": hash all files on the volume (fast, works without admin)
      - "raw": hash the volume/disk bytes (slow on large media, usually needs admin)
      - "auto": filesystem if a mount exists, otherwise raw
    """
    if chunk_size % 512 != 0:
        chunk_size = ((chunk_size // 512) + 1) * 512

    chosen = mode
    if mode == "auto":
        chosen = "filesystem" if mount_path else "raw"

    if chosen == "filesystem":
        if not mount_path:
            raise OSError("Filesystem hash requires a mounted drive letter.")
        return _hash_filesystem(
            mount_path,
            label=label,
            progress=progress,
            should_cancel=should_cancel,
        )

    if chosen != "raw":
        raise ValueError(f"Unknown hash mode: {mode}")

    try:
        return _hash_raw(
            physical_disk_index,
            size_bytes,
            mount_path,
            label=label,
            chunk_size=chunk_size,
            progress=progress,
            should_cancel=should_cancel,
        )
    except OSError as raw_exc:
        if not mount_path:
            raise OSError(
                f"{raw_exc}\n\nTip: run 369box as Administrator for raw device hashing."
            ) from raw_exc
        # Last resort fallback so the user still gets a hash
        result = _hash_filesystem(
            mount_path,
            label=label,
            progress=progress,
            should_cancel=should_cancel,
        )
        result.source = f"{result.source} (fallback after raw error: {raw_exc})"
        return result


def _hash_raw(
    physical_disk_index: int,
    size_bytes: int,
    mount_path: str | None,
    *,
    label: str,
    chunk_size: int,
    progress: ProgressCallback | None,
    should_cancel: CancelCallback | None,
) -> HashResult:
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    sha256 = hashlib.sha256()

    fh = _open_hash_source(physical_disk_index, mount_path)
    bytes_read = 0
    # When hashing \\.\X:, use volume capacity; for physical, use disk size
    if fh.path.upper().startswith("\\\\.\\") and len(fh.path) <= 6:
        total = _volume_total_bytes(mount_path, size_bytes)
    else:
        total = size_bytes if size_bytes > 0 else 0

    try:
        while True:
            if should_cancel and should_cancel():
                raise RuntimeError("Hash calculation cancelled by user.")
            # Don't read past known size (raw devices may not EOF cleanly)
            to_read = chunk_size
            if total > 0:
                remaining = total - bytes_read
                if remaining <= 0:
                    break
                to_read = min(chunk_size, remaining)
                # Keep reads sector-aligned when possible
                if to_read >= 512 and to_read % 512 != 0:
                    to_read = to_read - (to_read % 512)
                if to_read <= 0:
                    break
            chunk = fh.read(to_read)
            if not chunk:
                break
            md5.update(chunk)
            sha1.update(chunk)
            sha256.update(chunk)
            bytes_read += len(chunk)
            if progress:
                progress(bytes_read, total if total > 0 else bytes_read)
    finally:
        fh.close()

    if bytes_read == 0:
        raise OSError(f"Read 0 bytes from {fh.path} — device may be inaccessible.")

    if progress and total > 0:
        progress(min(bytes_read, total), total)

    return HashResult(
        md5=md5.hexdigest(),
        sha1=sha1.hexdigest(),
        sha256=sha256.hexdigest(),
        bytes_hashed=bytes_read,
        source=fh.path,
        label=label,
        mode="raw",
    )


def _hash_filesystem(
    mount_path: str,
    *,
    label: str,
    progress: ProgressCallback | None,
    should_cancel: CancelCallback | None,
) -> HashResult:
    """Hash every file under the mount (sorted paths) into one digest set."""
    root = mount_path if mount_path.endswith("\\") else mount_path.rstrip(":\\/") + ":\\"
    if not os.path.isdir(root):
        raise OSError(f"Mount path not available for filesystem hash: {root}")

    # Phase 1: discover files (can take a while on large USBs — report indeterminate)
    if progress:
        progress(0, 0)

    files: list[str] = []
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        if should_cancel and should_cancel():
            raise RuntimeError("Hash calculation cancelled by user.")
        dirnames[:] = [
            d
            for d in dirnames
            if d.upper() not in {"System Volume Information".upper(), "$RECYCLE.BIN"}
        ]
        for name in filenames:
            files.append(os.path.join(dirpath, name))
            seen += 1
            if progress and seen % 50 == 0:
                # total=0 keeps the UI in "scanning" / indeterminate mode
                progress(seen, 0)

    files.sort(key=lambda p: p.lower())

    total_size = 0
    for i, path in enumerate(files):
        if should_cancel and should_cancel():
            raise RuntimeError("Hash calculation cancelled by user.")
        try:
            total_size += os.path.getsize(path)
        except OSError:
            continue
        if progress and i % 100 == 0:
            progress(i, 0)

    if progress:
        if total_size > 0:
            progress(0, total_size)
        else:
            progress(0, 0)

    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    sha256 = hashlib.sha256()
    bytes_read = 0

    # Include the relative path in the stream so renames change the hash
    for path in files:
        if should_cancel and should_cancel():
            raise RuntimeError("Hash calculation cancelled by user.")
        rel = os.path.relpath(path, root).replace("\\", "/")
        header = f"PATH:{rel}\n".encode("utf-8", errors="surrogateescape")
        md5.update(header)
        sha1.update(header)
        sha256.update(header)
        try:
            with open(path, "rb") as fh:
                while True:
                    if should_cancel and should_cancel():
                        raise RuntimeError("Hash calculation cancelled by user.")
                    chunk = fh.read(1024 * 1024)
                    if not chunk:
                        break
                    md5.update(chunk)
                    sha1.update(chunk)
                    sha256.update(chunk)
                    bytes_read += len(chunk)
                    if progress:
                        progress(bytes_read, total_size if total_size > 0 else bytes_read)
        except OSError:
            missing = f"MISSING:{rel}\n".encode("utf-8")
            md5.update(missing)
            sha1.update(missing)
            sha256.update(missing)

    if progress and total_size > 0:
        progress(total_size, total_size)

    return HashResult(
        md5=md5.hexdigest(),
        sha1=sha1.hexdigest(),
        sha256=sha256.hexdigest(),
        bytes_hashed=bytes_read,
        source=f"filesystem:{root} ({len(files)} files)",
        label=label,
        mode="filesystem",
    )


def compare_hashes(baseline: HashResult, current: HashResult) -> dict[str, bool]:
    return {
        "md5": baseline.md5.lower() == current.md5.lower(),
        "sha1": baseline.sha1.lower() == current.sha1.lower(),
        "sha256": baseline.sha256.lower() == current.sha256.lower(),
        "all": (
            baseline.md5.lower() == current.md5.lower()
            and baseline.sha1.lower() == current.sha1.lower()
            and baseline.sha256.lower() == current.sha256.lower()
        ),
    }
