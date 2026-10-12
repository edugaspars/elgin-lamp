"""Vidro do painel: desfoque do que está atrás da janela e pintura em camadas.

O Qt não desfoca o fundo de uma janela. Antes de mostrar o painel, capturamos
o trecho da tela que ele vai cobrir, desfocamos e realçamos a saturação (como
o "vibrancy" da Apple). A captura é estática, o que basta para um painel que
fica aberto poucos segundos. Onde não dá para capturar a tela (Wayland, modo
offscreen dos testes) o painel usa um vidro simulado, mais opaco.
"""

import logging
from typing import Optional

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen, \
    QPixmap, QRadialGradient
from PySide6.QtWidgets import QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene

from . import theme

log = logging.getLogger(__name__)

SCALE = 8         # a imagem é reduzida antes de desfocar (mais rápido e mais macio)
BLUR = 7          # raio do desfoque na imagem reduzida
SATURATION = 1.5  # realce de cor do fundo
MARGIN = 48       # captura além da borda para o desfoque não escurecer as beiradas


def supported() -> bool:
    return QGuiApplication.platformName() in ("windows", "xcb", "cocoa")


def _blur(img: QImage, radius: float) -> QImage:
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(QPixmap.fromImage(img))
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(radius)
    effect.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    out = QImage(img.size(), QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    scene.render(p, QRectF(out.rect()), QRectF(0, 0, img.width(), img.height()))
    p.end()
    return out


def _saturate(img: QImage, amount: float) -> QImage:
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            h, s, v, _ = c.getHsvF()
            if h >= 0:
                img.setPixelColor(x, y, QColor.fromHsvF(h, min(1.0, s * amount), v))
    return img


def with_luma(img: QImage) -> QImage:
    """Guarda na imagem o brilho médio do fundo (0–1), usado para ajustar o véu."""
    total = n = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            c = QColor(img.pixel(x, y))
            total += 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
            n += 1
    img.setText("luma", f"{total / max(1, n):.3f}")
    return img


def veil(backdrop: QImage) -> QColor:
    """Véu do vidro: mais opaco quando o fundo prejudicaria a leitura.

    Texto claro sobre fundo claro (ou escuro sobre escuro) perde contraste;
    a Apple resolve com materiais mais densos, e aqui fazemos o mesmo.
    """
    c = QColor(theme.PANEL)
    try:
        luma = float(backdrop.text("luma"))
    except ValueError:
        return c
    risk = (luma - 0.30) / 0.6 if theme.DARK else (0.70 - luma) / 0.6
    risk = max(0.0, min(1.0, risk))
    c.setAlphaF(c.alphaF() + (0.94 - c.alphaF()) * risk * 0.75)
    return c


def grab_backdrop(rect: QRect) -> Optional[QImage]:
    """Captura e desfoca o trecho da tela em `rect` (coordenadas globais).

    Retorna uma imagem pequena que cobre `rect` exatamente, ou None.
    """
    if not supported():
        return None
    try:
        screen = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return None
        geo = screen.geometry()
        area = rect.adjusted(-MARGIN, -MARGIN, MARGIN, MARGIN).intersected(geo)
        if area.isEmpty():
            return None
        shot = screen.grabWindow(0)
        if shot.isNull():
            return None
        ratio = shot.width() / max(1, geo.width())
        local = QRect(round((area.x() - geo.x()) * ratio), round((area.y() - geo.y()) * ratio),
                      round(area.width() * ratio), round(area.height() * ratio))
        small = shot.copy(local).toImage().scaled(max(1, area.width() // SCALE), max(1, area.height() // SCALE),
                                                  Qt.AspectRatioMode.IgnoreAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation)
        if max(QColor(small.pixel(x, y)).value() for x in range(0, small.width(), 4)
               for y in range(0, small.height(), 4)) < 3:
            return None  # tela preta: captura bloqueada (Wayland, conteúdo protegido)
        small = _blur(_saturate(small, SATURATION), BLUR)
        # recorta de volta para o retângulo do painel
        fx, fy = small.width() / area.width(), small.height() / area.height()
        crop = QRectF((rect.x() - area.x()) * fx, (rect.y() - area.y()) * fy, rect.width() * fx, rect.height() * fy)
        return with_luma(small.copy(crop.toAlignedRect()))
    except Exception:  # noqa: BLE001 - sem desfoque é só menos bonito
        log.debug("Não foi possível capturar o fundo do painel", exc_info=True)
        return None


def paint_panel(p: QPainter, path: QPainterPath, backdrop: Optional[QImage], area: QRectF, glow: QColor,
                glow_level: float, glow_center: QPointF):
    """Pinta o vidro: fundo desfocado, véu, luz da lâmpada, reflexo e borda iluminada.

    `area` é o retângulo (no widget) que a imagem `backdrop` cobre.
    """
    r = path.boundingRect()
    p.save()
    p.setClipPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    if backdrop is not None and theme.TRANSPARENCY:
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(area, backdrop)
        p.setBrush(veil(backdrop))
    else:
        p.setBrush(theme.PANEL_SOLID)
    p.drawPath(path)

    # vidro simulado: leve gradiente vertical para dar profundidade
    depth = QLinearGradient(r.topLeft(), r.bottomLeft())
    depth.setColorAt(0, QColor(255, 255, 255, 6 if theme.DARK else 30))
    depth.setColorAt(1, QColor(0, 0, 0, 22 if theme.DARK else 6))
    p.setBrush(QBrush(depth))
    p.drawPath(path)

    # a luz da lâmpada atravessando o vidro
    if glow_level > 0.01:
        g = QRadialGradient(glow_center, r.width() * 0.85)
        c = QColor(glow)
        c.setAlphaF(min(1.0, theme.GLOW * glow_level))
        g.setColorAt(0, c)
        c2 = QColor(glow)
        c2.setAlphaF(min(1.0, theme.GLOW * glow_level * 0.35))
        g.setColorAt(0.45, c2)
        g.setColorAt(1, QColor(glow.red(), glow.green(), glow.blue(), 0))
        p.setBrush(QBrush(g))
        p.drawPath(path)

    # reflexo especular no terço de cima
    sheen = QLinearGradient(r.topLeft(), QPointF(r.left(), r.top() + r.height() * 0.38))
    sheen.setColorAt(0, theme.SHEEN)
    sheen.setColorAt(1, QColor(theme.SHEEN.red(), theme.SHEEN.green(), theme.SHEEN.blue(), 0))
    p.setBrush(QBrush(sheen))
    p.drawPath(path)
    p.restore()

    # contorno externo fino + borda iluminada de cima para baixo
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(theme.BORDER, 1))
    p.drawPath(path)
    rim = QLinearGradient(r.topLeft(), r.bottomLeft())
    rim.setColorAt(0, theme.RIM_TOP)
    rim.setColorAt(0.35, theme.RIM_BOTTOM)
    rim.setColorAt(1, theme.RIM_BOTTOM)
    p.save()
    c = r.center()
    p.translate(c)
    p.scale((r.width() - 2) / r.width(), (r.height() - 2) / r.height())
    p.translate(-c)
    p.setPen(QPen(QBrush(rim), 1.2))
    p.drawPath(path)
    p.restore()
