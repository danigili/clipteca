"""Tema oscuro neutro (como un visor de revelado: el color lo pone el vídeo)."""
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

BG = "#1b1c1f"
PANEL = "#232428"
CARD = "#2b2d32"
CARD_HOVER = "#33363c"
TEXT = "#d9dadd"
TEXT_DIM = "#8b8e95"
SELECT = "#4a7fd4"
PICK = "#5fb36b"
REJECT = "#d9534f"
TRIM = "#e0a526"
HDR = "#b48ce0"


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    p = QPalette()
    c = QColor
    p.setColor(QPalette.Window, c(PANEL))
    p.setColor(QPalette.WindowText, c(TEXT))
    p.setColor(QPalette.Base, c(BG))
    p.setColor(QPalette.AlternateBase, c(CARD))
    p.setColor(QPalette.ToolTipBase, c(CARD))
    p.setColor(QPalette.ToolTipText, c(TEXT))
    p.setColor(QPalette.Text, c(TEXT))
    p.setColor(QPalette.Button, c(CARD))
    p.setColor(QPalette.ButtonText, c(TEXT))
    p.setColor(QPalette.Highlight, c(SELECT))
    p.setColor(QPalette.HighlightedText, c("#ffffff"))
    p.setColor(QPalette.PlaceholderText, c(TEXT_DIM))
    p.setColor(QPalette.Link, c(SELECT))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, c("#5d6066"))
    app.setPalette(p)
    app.setStyleSheet(f"""
        QToolTip {{ border: 1px solid #3a3d44; padding: 4px; }}
        QSplitter::handle {{ background: {BG}; }}
        QTreeWidget, QListView {{ border: none; }}
        QLabel#sectionTitle {{ color: {TEXT_DIM}; font-weight: 600; padding: 6px 2px 2px 2px; }}
        QPushButton#chip {{
            background: {CARD_HOVER}; border: 1px solid #40434a; border-radius: 10px;
            padding: 2px 8px; color: {TEXT};
        }}
        QPushButton#chip:hover {{ border-color: {REJECT}; color: #fff; }}
        QPushButton#flagPick:checked   {{ background: {PICK};   color: #0d1a10; font-weight: 700; }}
        QPushButton#flagReject:checked {{ background: {REJECT}; color: #1e0b0a; font-weight: 700; }}
        QPushButton#trimBtn {{ color: {TRIM}; }}
        QStatusBar {{ color: {TEXT_DIM}; }}
    """)
