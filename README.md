# 369box

A little Windows side project by **Rana Almeshari**: a desktop app that can mark a USB/external drive read-only, hash it, and keep a simple session log


## What it does

- Lists removable / external drives (skips the system disk)
- Turns disk read-only on/off (needs Admin)
- Shows protection status in the UI, and after enabling runs a test write to check it actually blocked
- Safely ejects the selected USB (Explorer eject)
- MD5 / SHA-1 / SHA-256 (file hash, or slower raw disk hash)
- Basic case fields + an append-only log you can export

## Requirements

- Windows 10/11
- Python 3.10+
- Administrator rights for write protection (it uses Windows disk/volume APIs that need elevation)

## Setup

From the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

From the project root:

```powershell
python main.py
```

Or double-click `run.bat` (right-click → Run as administrator for write protection).

**Tips:** close File Explorer windows for that drive before enabling protection. Hashing a full USB can take a long time.

## Known limitations

- Software read-only can fail or be bypassed — this is not a hardware write-blocker
- Windows may already have touched the drive before protection is on
- Explorer (or other apps) keeping the drive open can make protection look flaky
- If something fails, the app shows an error/warning dialog and logs it — it shouldn’t silently pretend it worked
- Raw disk hash on large drives is slow; file hash only covers file contents, not every disk byte

## Layout

```
369box/
  main.py
  run.bat
  box369/
    devices.py
    writeprotect.py
    hashing.py
    eject.py
    audit.py
    case_meta.py
    gui/                 # PyQt6 UI (main_window, dialogs, styles)
    assets/
  screenshots/
```

## Author

Rana Almeshari

## License

No formal license yet — personal project, use at your own risk.
