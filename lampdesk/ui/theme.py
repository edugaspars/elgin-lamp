"""Paleta e tipografia: vidro escuro ou claro, acento na cor da lâmpada.

As cores são variáveis do módulo trocadas por `apply()`; leia sempre `theme.X`
na hora de pintar (nunca guarde a cor em argumento padrão ou no __init__).
"""

import sys

from PySide6.QtGui import QColor, QFont

MODES = ("dark", "light")

# Cores do painel e dos componentes desenhados à mão.
_PALETTES = {
    "dark": dict(
        PANEL=QColor(28, 28, 32, 178),        # véu sobre o fundo desfocado
        PANEL_SOLID=QColor(24, 24, 28, 246),  # sem desfoque (Wayland, transparência reduzida)
        SHEEN=QColor(255, 255, 255, 20),      # brilho especular no topo do vidro
        RIM_TOP=QColor(255, 255, 255, 64),    # borda iluminada (luz vindo de cima)
        RIM_BOTTOM=QColor(255, 255, 255, 12),
        BORDER=QColor(0, 0, 0, 90),           # contorno externo fino
        SHADOW=QColor(0, 0, 0, 56),
        GLOW=0.20,                            # força do brilho da lâmpada no vidro
        CARD=QColor(255, 255, 255, 14),
        CARD_HOVER=QColor(255, 255, 255, 26),
        CARD_ACTIVE=QColor(255, 255, 255, 38),
        CARD_BORDER=QColor(255, 255, 255, 22),
        CARD_BORDER_ACTIVE=QColor(255, 255, 255, 64),
        CARD_RIM=QColor(255, 255, 255, 34),
        HOVER=QColor(255, 255, 255, 18),
        TRACK=QColor(255, 255, 255, 16),
        HANDLE=QColor(250, 250, 252),
        HANDLE_SHADOW=QColor(0, 0, 0, 110),
        TEXT=QColor(245, 245, 247),
        MUTED=QColor(152, 152, 160),
        DIM=QColor(92, 92, 98),
        OK=QColor(48, 209, 88),
        WARN=QColor(255, 159, 10),
        ERROR=QColor(255, 69, 58),
        BULB_OFF_HI=QColor(86, 86, 92),
        BULB_OFF_LO=QColor(36, 36, 40),
        BULB_OFF_EDGE=QColor(255, 255, 255, 40),
        INVERSE=QColor(245, 245, 247),        # card ativo (como os botões do Control Center)
        INVERSE_TEXT=QColor(29, 29, 31),
        INVERSE_MUTED=QColor(96, 96, 102),
        SEGMENT=QColor(118, 118, 128, 60),
        SEGMENT_SEL=QColor(99, 99, 104),
        FILL_LOW=0.26,                        # opacidade do acento no slider (início, fim)
        FILL_HIGH=0.82,
    ),
    "light": dict(
        PANEL=QColor(250, 250, 252, 165),
        PANEL_SOLID=QColor(246, 246, 249, 250),
        SHEEN=QColor(255, 255, 255, 120),
        RIM_TOP=QColor(255, 255, 255, 240),
        RIM_BOTTOM=QColor(255, 255, 255, 90),
        BORDER=QColor(0, 0, 0, 34),
        SHADOW=QColor(0, 0, 0, 24),
        GLOW=0.16,
        CARD=QColor(255, 255, 255, 120),
        CARD_HOVER=QColor(255, 255, 255, 185),
        CARD_ACTIVE=QColor(255, 255, 255, 240),
        CARD_BORDER=QColor(0, 0, 0, 16),
        CARD_BORDER_ACTIVE=QColor(0, 0, 0, 34),
        CARD_RIM=QColor(255, 255, 255, 200),
        HOVER=QColor(0, 0, 0, 10),
        TRACK=QColor(0, 0, 0, 14),
        HANDLE=QColor(255, 255, 255),
        HANDLE_SHADOW=QColor(0, 0, 0, 60),
        TEXT=QColor(29, 29, 31),
        MUTED=QColor(110, 110, 116),
        DIM=QColor(176, 176, 182),
        OK=QColor(40, 180, 80),
        WARN=QColor(230, 130, 0),
        ERROR=QColor(235, 55, 45),
        BULB_OFF_HI=QColor(250, 250, 252),
        BULB_OFF_LO=QColor(206, 206, 212),
        BULB_OFF_EDGE=QColor(0, 0, 0, 34),
        INVERSE=QColor(29, 29, 31),
        INVERSE_TEXT=QColor(245, 245, 247),
        INVERSE_MUTED=QColor(160, 160, 166),
        SEGMENT=QColor(118, 118, 128, 30),
        SEGMENT_SEL=QColor(255, 255, 255),
        FILL_LOW=0.36,
        FILL_HIGH=0.95,
    ),
}

# Cores das janelas comuns (configurações, diálogos, menus), em CSS.
_QSS = {
    "dark": dict(
        window="#1c1c1e", text="rgba(245,245,247,1)", muted="rgba(152,152,160,1)", dim="rgba(92,92,98,1)",
        field="rgba(255,255,255,0.07)", field_border="rgba(255,255,255,0.09)", focus="rgba(255,255,255,0.38)",
        list="rgba(255,255,255,0.045)", item_hover="rgba(255,255,255,0.05)", item_sel="rgba(255,255,255,0.11)",
        button="rgba(255,255,255,0.09)", button_hover="rgba(255,255,255,0.14)", button_down="rgba(255,255,255,0.05)",
        primary="#f5f5f7", primary_text="#1d1d1f", primary_hover="#ffffff",
        segment="rgba(118,118,128,0.24)", segment_sel="rgba(99,99,102,1)",
        selection="rgba(255,255,255,0.22)", popup="#2c2c2e", menu="rgba(36,36,40,0.97)",
        menu_border="rgba(255,255,255,0.12)", menu_sel="rgba(255,255,255,0.12)", separator="rgba(255,255,255,0.10)",
        groove="rgba(255,255,255,0.12)", fill="#f5f5f7", scroll="rgba(255,255,255,0.20)",
        indicator="rgba(255,255,255,0.30)", tooltip="#2c2c2e", danger="#ff453a",
        check_stroke="#1d1d1f", chevron="#98989f",
    ),
    "light": dict(
        window="#f2f2f7", text="rgba(29,29,31,1)", muted="rgba(110,110,116,1)", dim="rgba(176,176,182,1)",
        field="#ffffff", field_border="rgba(0,0,0,0.10)", focus="rgba(0,0,0,0.35)",
        list="#ffffff", item_hover="rgba(0,0,0,0.035)", item_sel="rgba(0,0,0,0.07)",
        button="#ffffff", button_hover="#fafafa", button_down="#ececf0",
        primary="#1d1d1f", primary_text="#ffffff", primary_hover="#3a3a3c",
        segment="rgba(118,118,128,0.12)", segment_sel="#ffffff",
        selection="rgba(0,0,0,0.14)", popup="#ffffff", menu="rgba(252,252,253,0.98)",
        menu_border="rgba(0,0,0,0.10)", menu_sel="rgba(0,0,0,0.06)", separator="rgba(0,0,0,0.08)",
        groove="rgba(0,0,0,0.10)", fill="#1d1d1f", scroll="rgba(0,0,0,0.22)",
        indicator="rgba(0,0,0,0.22)", tooltip="#ffffff", danger="#ff3b30",
        check_stroke="#ffffff", chevron="#6e6e74",
    ),
}

RADIUS = 26
MODE = "dark"
DARK = True
TRANSPARENCY = True  # False = "Reduzir transparência" (sem desfoque, sem Mica)

# preenchidas por apply(); declaradas para leitores e linters
PANEL = PANEL_SOLID = SHEEN = RIM_TOP = RIM_BOTTOM = BORDER = SHADOW = QColor()
CARD = CARD_HOVER = CARD_ACTIVE = CARD_BORDER = CARD_BORDER_ACTIVE = CARD_RIM = HOVER = QColor()
TRACK = HANDLE = HANDLE_SHADOW = TEXT = MUTED = DIM = OK = WARN = ERROR = QColor()
BULB_OFF_HI = BULB_OFF_LO = BULB_OFF_EDGE = INVERSE = INVERSE_TEXT = INVERSE_MUTED = QColor()
SEGMENT = SEGMENT_SEL = QColor()
GLOW = FILL_LOW = FILL_HIGH = 0.0


def apply(mode: str = "dark", transparency: bool = True) -> None:
    """Troca o tema ativo. Janelas já abertas precisam reaplicar a folha de estilo."""
    global MODE, DARK, TRANSPARENCY
    MODE = mode if mode in MODES else "dark"
    DARK = MODE == "dark"
    TRANSPARENCY = bool(transparency)
    globals().update({k: (QColor(v) if isinstance(v, QColor) else v) for k, v in _PALETTES[MODE].items()})


apply()


def _asset(name: str, svg: str) -> str:
    """Grava o SVG na pasta de dados (o QSS só aceita imagens de arquivo/recurso)."""
    from ..paths import data_dir
    folder = data_dir() / "assets"
    folder.mkdir(exist_ok=True)
    path = folder / f"{name}.svg"
    if not path.exists() or path.read_text(encoding="utf-8") != svg:
        path.write_text(svg, encoding="utf-8")
    return path.as_posix()


def _check(color: str) -> str:
    return _asset(f"check-{MODE}",
                  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
                  f'stroke="{color}" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round">'
                  '<path d="M5 12.5l4.5 4.5L19 7.5"/></svg>')


def _chevron(color: str) -> str:
    return _asset(f"chevron-{MODE}",
                  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
                  f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
                  '<path d="M7 10l5 5 5-5"/></svg>')


def font(size: float, weight: QFont.Weight = QFont.Weight.Normal, tracking: float = 0.0) -> QFont:
    """Fonte do sistema; `tracking` em % (negativo aperta os números grandes, como no SF Pro)."""
    f = QFont()
    if sys.platform == "win32":
        f.setFamilies(["Segoe UI Variable Display", "Segoe UI Variable Text", "Segoe UI"])
    elif sys.platform == "darwin":
        f.setFamilies(["SF Pro Display", "Helvetica Neue"])
    else:
        f.setFamilies(["Inter", "Noto Sans", "Cantarell", "Ubuntu", "DejaVu Sans"])
    f.setPixelSize(round(size))
    f.setWeight(weight)
    if tracking:
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100 + tracking)
    return f


def css(c: QColor) -> str:
    return f"rgba({c.red()},{c.green()},{c.blue()},{c.alpha()})"


def dialog_color(name: str) -> str:
    return _QSS[MODE][name]


def dialog_qss(translucent: bool = False) -> str:
    """Folha de estilo das janelas comuns (configurações e diálogos).

    `translucent`: a janela tem fundo Mica do Windows 11; os contêineres ficam
    transparentes para o desfoque aparecer, mas diálogos e popups seguem sólidos.
    """
    c = _QSS[MODE]
    window = "transparent" if translucent else c["window"]
    return f"""
QWidget {{ background: {window}; color: {c['text']}; font-size: 13px; }}
QDialog, QMessageBox, QColorDialog, QInputDialog {{ background: {c['window']}; }}
QLabel {{ background: transparent; }}
QLabel[muted="true"] {{ color: {c['muted']}; }}
QLabel[title="true"] {{ font-size: 22px; font-weight: 700; }}
QLabel[section="true"] {{ color: {c['muted']}; font-size: 11px; font-weight: 600; }}
QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
QListWidget {{ background: {c['list']}; border: 1px solid {c['field_border']}; border-radius: 14px;
    padding: 6px; outline: none; }}
QListWidget::item {{ padding: 10px; border-radius: 10px; color: {c['text']}; }}
QListWidget::item:selected {{ background: {c['item_sel']}; color: {c['text']}; }}
QListWidget::item:hover:!selected {{ background: {c['item_hover']}; }}
QLineEdit, QSpinBox, QTimeEdit, QDateEdit, QComboBox, QDoubleSpinBox {{
    background: {c['field']}; border: 1px solid {c['field_border']}; border-radius: 10px;
    padding: 7px 10px; selection-background-color: {c['selection']}; selection-color: {c['text']}; }}
QLineEdit:focus, QSpinBox:focus, QTimeEdit:focus, QDateEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {{
    border-color: {c['focus']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView, QCompleter QAbstractItemView, QListView[completer="true"] {{
    background: {c['popup']}; border: 1px solid {c['menu_border']}; border-radius: 8px; padding: 4px;
    selection-background-color: {c['menu_sel']}; selection-color: {c['text']}; outline: none; }}
QPushButton {{ background: {c['button']}; border: 1px solid {c['field_border']}; border-radius: 10px;
    padding: 8px 16px; font-weight: 500; }}
QPushButton:hover {{ background: {c['button_hover']}; }}
QPushButton:pressed {{ background: {c['button_down']}; }}
QPushButton:disabled {{ color: {c['dim']}; }}
QPushButton[primary="true"] {{ background: {c['primary']}; color: {c['primary_text']}; border: none;
    font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: {c['primary_hover']}; }}
QPushButton[danger="true"] {{ color: {c['danger']}; }}
QPushButton[chip="true"] {{ padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }}
QPushButton[day="true"] {{ min-width: 34px; padding: 6px 4px; border-radius: 17px; }}
QPushButton[day="true"]:checked {{ background: {c['primary']}; color: {c['primary_text']}; border: none; }}
QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator, QListWidget::indicator {{ width: 16px; height: 16px;
    border: 1px solid {c['indicator']}; border-radius: 5px; background: {c['field']}; }}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:checked, QListWidget::indicator:checked {{
    background: {c['primary']}; border-color: {c['primary']}; image: url({_check(c['check_stroke'])}); }}
QRadioButton::indicator:checked {{ background: {c['primary_text']}; border: 5px solid {c['primary']};
    width: 8px; height: 8px; border-radius: 9px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {c['focus']}; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0; border: none; }}
QComboBox::down-arrow {{ image: url({_chevron(c['chevron'])}); width: 14px; height: 14px; margin-right: 8px; }}
QSlider {{ background: transparent; }}
QSlider::groove:horizontal {{ height: 6px; background: {c['groove']}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {c['fill']}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: #ffffff; border: 1px solid rgba(0,0,0,0.12); width: 20px;
    margin: -8px 0; border-radius: 11px; }}
QProgressBar {{ background: {c['groove']}; border: none; border-radius: 4px; height: 8px; text-align: center;
    color: transparent; }}
QProgressBar::chunk {{ background: {c['fill']}; border-radius: 4px; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['scroll']}; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    height: 0; background: transparent; }}
QMenu {{ background: {c['menu']}; border: 1px solid {c['menu_border']}; border-radius: 12px; padding: 6px; }}
QMenu::item {{ padding: 7px 22px 7px 12px; border-radius: 7px; color: {c['text']}; background: transparent; }}
QMenu::item:selected {{ background: {c['menu_sel']}; }}
QMenu::item:disabled {{ color: {c['dim']}; }}
QMenu::separator {{ height: 1px; background: {c['separator']}; margin: 5px 10px; }}
QMenu::indicator {{ width: 14px; height: 14px; }}
QToolTip {{ background: {c['tooltip']}; color: {c['text']}; border: 1px solid {c['menu_border']};
    border-radius: 7px; padding: 5px 9px; }}
"""


def popup_qss() -> str:
    """O painel é transparente (a forma é desenhada à mão); só menus e botões têm estilo."""
    qss = dialog_qss()
    return "QWidget { background: transparent; color: %s; }\n" % css(TEXT) + \
        qss[qss.index("QPushButton {"):qss.index("QCheckBox")] + qss[qss.index("QMenu {"):]
