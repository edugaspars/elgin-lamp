"""Ícones de traço fino desenhados em SVG (sem arquivos externos)."""

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_PATHS = {
    "power": '<path d="M12 3v8"/><path d="M6.4 6.6a8 8 0 1 0 11.2 0"/>',
    "bulb": '<path d="M9.5 18h5"/><path d="M10.5 21h3"/>'
            '<path d="M12 3a6 6 0 0 0-3.6 10.8c.7.6 1.1 1.3 1.1 2.2h5c0-.9.4-1.6 1.1-2.2A6 6 0 0 0 12 3z"/>',
    "sun": '<circle cx="12" cy="12" r="3.5"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6l1.4 1.4M18 18l1.4 1.4'
           'M2.5 12h2M19.5 12h2M4.6 19.4L6 18M18 6l1.4-1.4"/>',
    "thermo": '<path d="M14 14.6V5a2 2 0 0 0-4 0v9.6a4 4 0 1 0 4 0z"/><path d="M12 9v6.5"/>',
    "palette": '<path d="M12 3a9 9 0 1 0 0 18c1 0 1.6-.7 1.6-1.5 0-.4-.2-.8-.5-1.1a1.5 1.5 0 0 1 1.1-2.6H16'
               'a5 5 0 0 0 5-5C21 6.4 17 3 12 3z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10" cy="7.3" r="1"/>'
               '<circle cx="14.5" cy="7.3" r="1"/><circle cx="17" cy="11" r="1"/>',
    "moon": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    "sparkles": '<path d="M11 3.5l1.7 4.3 4.3 1.7-4.3 1.7L11 15.5l-1.7-4.3L5 9.5l4.3-1.7z"/>'
                '<path d="M18.5 14.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
    "chevron": '<path d="M7 10l5 5 5-5"/>',
    "minus": '<path d="M6 12h12"/>',
    "plus": '<path d="M6 12h12M12 6v12"/>',
    "shield": '<path d="M12 3l7 2.8V11c0 4.6-2.9 8-7 9.8-4.1-1.8-7-5.2-7-9.8V5.8z"/><path d="M9 12l2.2 2.2L15.2 10"/>',
    "shield-x": '<path d="M12 3l7 2.8V11c0 4.6-2.9 8-7 9.8-4.1-1.8-7-5.2-7-9.8V5.8z"/><path d="M9.5 9.5l5 5M14.5 9.5l-5 5"/>',
    "sliders": '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14.8-3.5M4 4v4h4"/><path d="M4 13a8 8 0 0 0 14.8 3.5M20 20v-4h-4"/>',
    "bolt": '<path d="M13 2.5L5 13.5h6l-1 8 8-11h-6z"/>',
    "eye": '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
}


def _svg(name: str, color: str, stroke: float) -> bytes:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
        f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{_PATHS[name]}</svg>'
    ).encode()


@lru_cache(maxsize=256)
def _renderer(name: str, color: str, stroke: float) -> QSvgRenderer:
    return QSvgRenderer(QByteArray(_svg(name, color, stroke)))


def paint(p: QPainter, name: str, rect: QRectF, color: QColor, stroke: float = 1.7) -> None:
    _renderer(name, color.name(QColor.NameFormat.HexArgb if color.alpha() < 255 else QColor.NameFormat.HexRgb),
              stroke).render(p, rect)


def pixmap(name: str, size: int, color: QColor, stroke: float = 1.7, dpr: float = 2.0) -> QPixmap:
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint(p, name, QRectF(0, 0, size, size), color, stroke)
    p.end()
    return pm


def icon(name: str, color: QColor, size: int = 18) -> QIcon:
    return QIcon(pixmap(name, size, color))
