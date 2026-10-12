"""Paleta e tipografia: painel escuro, cards discretos, acento na cor da lâmpada."""

import sys

from PySide6.QtGui import QColor, QFont

BG = QColor(16, 16, 16, 250)
BORDER = QColor(255, 255, 255, 26)
CARD = QColor(28, 28, 28)
CARD_HOVER = QColor(36, 36, 36)
CARD_ACTIVE = QColor(40, 40, 40)
CARD_BORDER = QColor(255, 255, 255, 14)
CARD_BORDER_ACTIVE = QColor(255, 255, 255, 60)
TRACK = QColor(30, 30, 30)
TEXT = QColor(242, 242, 242)
MUTED = QColor(140, 140, 140)
DIM = QColor(92, 92, 92)
OK = QColor(120, 200, 140)
WARN = QColor(240, 170, 80)
ERROR = QColor(235, 100, 90)

RADIUS = 22

_ASSETS = {
    "check": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#111" '
             'stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    "chevron": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#8c8c8c" '
               'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 10l5 5 5-5"/></svg>',
}


def _asset(name: str) -> str:
    """Grava o SVG na pasta de dados (o QSS só aceita imagens de arquivo/recurso)."""
    from ..paths import data_dir
    folder = data_dir() / "assets"
    folder.mkdir(exist_ok=True)
    path = folder / f"{name}.svg"
    if not path.exists() or path.read_text(encoding="utf-8") != _ASSETS[name]:
        path.write_text(_ASSETS[name], encoding="utf-8")
    return path.as_posix()


def font(size: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont()
    if sys.platform == "win32":
        f.setFamilies(["Segoe UI Variable Display", "Segoe UI Variable Text", "Segoe UI"])
    else:
        f.setFamilies(["Inter", "Noto Sans", "Cantarell", "Ubuntu", "DejaVu Sans"])
    f.setPixelSize(round(size))
    f.setWeight(weight)
    return f


def css(c: QColor) -> str:
    return f"rgba({c.red()},{c.green()},{c.blue()},{c.alpha()})"


# Folha de estilo das janelas comuns (configurações e diálogos).
DIALOG_QSS = f"""
QWidget {{ background: #121212; color: {css(TEXT)}; font-size: 13px; }}
QLabel[muted="true"] {{ color: {css(MUTED)}; }}
QLabel[title="true"] {{ font-size: 18px; font-weight: 600; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {css(MUTED)}; padding: 8px 14px;
    border-radius: 10px; margin-right: 4px; }}
QTabBar::tab:selected {{ background: #222; color: {css(TEXT)}; }}
QTabBar::tab:hover:!selected {{ color: {css(TEXT)}; }}
QListWidget {{ background: #1a1a1a; border: 1px solid rgba(255,255,255,14); border-radius: 14px;
    padding: 6px; outline: none; }}
QListWidget::item {{ padding: 10px; border-radius: 10px; }}
QListWidget::item:selected {{ background: #262626; color: {css(TEXT)}; }}
QListWidget::item:hover:!selected {{ background: #1f1f1f; }}
QLineEdit, QSpinBox, QTimeEdit, QComboBox, QDoubleSpinBox {{
    background: #1c1c1c; border: 1px solid rgba(255,255,255,20); border-radius: 10px;
    padding: 7px 10px; selection-background-color: #3a3a3a; }}
QLineEdit:focus, QSpinBox:focus, QTimeEdit:focus, QComboBox:focus {{ border-color: rgba(255,255,255,70); }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: #1c1c1c; border: 1px solid rgba(255,255,255,25);
    selection-background-color: #2c2c2c; outline: none; }}
QPushButton {{ background: #222; border: 1px solid rgba(255,255,255,18); border-radius: 10px;
    padding: 8px 14px; }}
QPushButton:hover {{ background: #2a2a2a; }}
QPushButton:pressed {{ background: #1a1a1a; }}
QPushButton:disabled {{ color: {css(DIM)}; }}
QPushButton[primary="true"] {{ background: #f2f2f2; color: #111; border: none; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: #ffffff; }}
QPushButton[danger="true"] {{ color: {css(ERROR)}; }}
QPushButton[day="true"] {{ min-width: 34px; padding: 6px 4px; }}
QPushButton[day="true"]:checked {{ background: #f2f2f2; color: #111; border: none; }}
QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator, QListWidget::indicator {{ width: 14px; height: 14px;
    border: 1px solid rgba(255,255,255,80); border-radius: 5px; background: #1c1c1c; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QListWidget::indicator:checked {{
    background: #f2f2f2; border-color: #f2f2f2; image: url({_asset("check")}); }}
QRadioButton::indicator:checked {{ background: #f2f2f2; border: 4px solid #1c1c1c; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: rgba(255,255,255,140); }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0; border: none; }}
QComboBox::down-arrow {{ image: url({_asset("chevron")}); width: 14px; height: 14px; margin-right: 8px; }}
QSlider::groove:horizontal {{ height: 6px; background: #2a2a2a; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: #d9d9d9; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: #fff; width: 16px; margin: -6px 0; border-radius: 8px; }}
QProgressBar {{ background: #1c1c1c; border: none; border-radius: 4px; height: 8px; text-align: center; }}
QProgressBar::chunk {{ background: #d9d9d9; border-radius: 4px; }}
QScrollBar:vertical {{ background: transparent; width: 8px; }}
QScrollBar::handle:vertical {{ background: #333; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QMenu {{ background: #1a1a1a; border: 1px solid rgba(255,255,255,25); border-radius: 12px; padding: 6px; }}
QMenu::item {{ padding: 8px 22px 8px 14px; border-radius: 8px; color: {css(TEXT)}; }}
QMenu::item:selected {{ background: #2a2a2a; }}
QMenu::item:disabled {{ color: {css(DIM)}; }}
QMenu::separator {{ height: 1px; background: rgba(255,255,255,20); margin: 6px 8px; }}
QMenu::indicator {{ width: 14px; height: 14px; }}
QToolTip {{ background: #222; color: {css(TEXT)}; border: 1px solid rgba(255,255,255,30);
    border-radius: 6px; padding: 4px 8px; }}
"""

# O painel é transparente (a forma é desenhada à mão); só menus e botões têm estilo.
POPUP_QSS = "QWidget { background: transparent; color: %s; }" % css(TEXT) + \
    DIALOG_QSS[DIALOG_QSS.index("QPushButton {"):DIALOG_QSS.index("QCheckBox")] + \
    DIALOG_QSS[DIALOG_QSS.index("QMenu {"):]
