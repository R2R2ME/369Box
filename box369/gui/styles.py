"""Application stylesheet — dark purple / grey forensic theme."""

APP_STYLE = """
QWidget {
    font-family: "Segoe UI", "IBM Plex Sans", sans-serif;
    font-size: 13px;
    color: #e6e1ef;
}
QMainWindow, QDialog {
    background-color: #16121f;
}
QGroupBox {
    font-weight: 600;
    border: 1px solid #3a314d;
    border-radius: 8px;
    margin-top: 14px;
    padding: 14px 12px 12px 12px;
    background: #1e1830;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 8px;
    color: #c4b5e0;
}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background: #12101a;
    color: #f0ebf8;
    border: 1px solid #4a3f63;
    border-radius: 5px;
    padding: 7px 9px;
    selection-background-color: #7c5cbf;
    selection-color: #ffffff;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
    border: 1px solid #9b7fd4;
}
QPushButton {
    background: #7c5cbf;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 9px 15px;
    font-weight: 600;
}
QPushButton:hover {
    background: #9170d4;
}
QPushButton:pressed {
    background: #6a4ba8;
}
QPushButton:disabled {
    background: #3a314d;
    color: #8a8199;
}
QPushButton#dangerButton {
    background: #b33a4a;
}
QPushButton#dangerButton:hover {
    background: #c94d5c;
}
QPushButton#safeButton {
    background: #2f9e6b;
}
QPushButton#safeButton:hover {
    background: #3bb87d;
}
QPushButton#secondaryButton {
    background: #3d3552;
    color: #e6e1ef;
    border: 1px solid #5a4e73;
}
QPushButton#secondaryButton:hover {
    background: #4d4466;
}
QTreeWidget, QListWidget, QTableWidget, QTextBrowser, QTextEdit {
    background: #12101a;
    color: #e6e1ef;
    border: 1px solid #3a314d;
    border-radius: 6px;
    alternate-background-color: #1a1528;
}
QTreeWidget::item:selected, QListWidget::item:selected {
    background: #5a3f8a;
    color: #ffffff;
}
QTreeWidget::item:hover, QListWidget::item:hover {
    background: #2a2340;
}
QHeaderView::section {
    background: #2a2340;
    color: #c4b5e0;
    padding: 7px;
    border: none;
    border-right: 1px solid #3a314d;
    border-bottom: 1px solid #3a314d;
    font-weight: 600;
}
QProgressBar {
    border: 1px solid #3a314d;
    border-radius: 5px;
    text-align: center;
    background: #12101a;
    color: #e6e1ef;
    height: 18px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #6a4ba8, stop:1 #9b7fd4);
    border-radius: 4px;
}
QScrollBar:vertical {
    background: #16121f;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #4a3f63;
    border-radius: 5px;
    min-height: 24px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QStatusBar {
    background: #12101a;
    color: #a89bb8;
    border-top: 1px solid #3a314d;
}
QSplitter::handle {
    background: #3a314d;
}
QSplitter::handle:horizontal {
    width: 6px;
}
QSplitter::handle:vertical {
    height: 6px;
}
QSplitter::handle:hover {
    background: #7c5cbf;
}
QLabel#statusProtected {
    background: #143528;
    color: #7ddea8;
    border: 2px solid #2f9e6b;
    border-radius: 8px;
    padding: 12px;
    font-size: 15px;
    font-weight: 700;
}
QLabel#statusUnprotected {
    background: #3a1820;
    color: #f0a0a8;
    border: 2px solid #b33a4a;
    border-radius: 8px;
    padding: 12px;
    font-size: 15px;
    font-weight: 700;
}
QLabel#statusUnknown {
    background: #3a3420;
    color: #e8d48a;
    border: 2px solid #c4a035;
    border-radius: 8px;
    padding: 12px;
    font-size: 15px;
    font-weight: 700;
}
QLabel#matchOk {
    color: #7ddea8;
    font-weight: 700;
    font-size: 14px;
}
QLabel#matchBad {
    color: #f0a0a8;
    font-weight: 700;
    font-size: 14px;
}
QWidget#bannerBar {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #1a1228, stop:0.5 #2a1a45, stop:1 #1a1228);
    border-bottom: 1px solid #5a3f8a;
}
QLabel#bannerTitle {
    color: #f0ebf8;
    font-size: 22px;
    font-weight: 700;
    letter-spacing: 1.5px;
}
QLabel#bannerTagline {
    color: #a89bb8;
    font-size: 12px;
}
QLabel#subtitle {
    color: #a89bb8;
    font-size: 12px;
}
QMessageBox {
    background-color: #1e1830;
}
QMessageBox QLabel {
    color: #e6e1ef;
}
"""
