"""369box — USB write protection & hashing (personal project)."""

from __future__ import annotations

import sys


def _ensure_windows() -> None:
    if sys.platform != "win32":
        print("369box requires Windows.", file=sys.stderr)
        sys.exit(1)


def main() -> int:
    _ensure_windows()

    from PyQt6.QtWidgets import QApplication, QMessageBox

    from box369.gui.main_window import MainWindow
    from box369.writeprotect import is_admin, request_elevation

    app = QApplication(sys.argv)
    app.setApplicationName("369box")
    app.setOrganizationName("369box")

    if not is_admin():
        choice = QMessageBox.warning(
            None,
            "Administrator required",
            "369box must run as Administrator for write protection and reliable "
            "raw-disk hashing to work.\n\n"
            "Click Yes to restart elevated (UAC prompt), or No to continue "
            "with limited functionality.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if choice == QMessageBox.StandardButton.Yes:
            import os

            script = os.path.abspath(__file__)
            if request_elevation(script):
                return 0
            QMessageBox.critical(
                None,
                "Elevation failed",
                "Could not relaunch as Administrator. "
                "Right-click PowerShell/Terminal → Run as administrator, then:\n\n"
                f"python \"{script}\"",
            )

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
