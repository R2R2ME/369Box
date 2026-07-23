# 369box

A little Windows side project by **Rana Almeshari**: a desktop app that can mark a USB/external drive read-only, hash it, and keep a simple session log.

Built for tinkering and learning how software write protection behaves on Windows — **not** a hardware write-blocker, and not something to trust for real evidence work.

## Screenshots

![369box](screenshots/main.png)

## What it does

- Lists removable / external drives (skips the system disk)
- Turns disk read-only on/off (needs Admin)
- Checks that a test write actually fails after enabling protection
- Safely ejects the selected USB (Explorer eject)
- MD5 / SHA-1 / SHA-256 (quick file hash or slower raw disk hash)
- Basic case fields + an append-only log you can export

## Requirements

- Windows 10/11
- Python 3.10+
- Run as Administrator if you want write protection to work

## Setup

```powershell
cd $env:USERPROFILE\Projects\369box
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
cd $env:USERPROFILE\Projects\369box
python main.py
```

Or double-click `run.bat` (right-click → Run as administrator for write protection).

**Tips:** close File Explorer windows on that drive before enabling protection. Raw disk hash on a big drive can take a long time.

## Heads-up

Software read-only can fail or be bypassed. If Windows already touched the drive, or Explorer still has it open, results may surprise you. That’s kind of the point of poking at it.

## Layout

```
369box/
  main.py
  box369/
    devices.py
    writeprotect.py
    hashing.py
    audit.py
    case_meta.py
    gui/
```

## Author

Rana Almeshari

## License

Personal project — use at your own risk.
