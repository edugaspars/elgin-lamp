"""Componentes desenhados à mão que imitam o visual do painel de referência."""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient)
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from . import icons, theme


def mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(round(a.red() + (b.red() - a.red()) * t),
                  round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t),
                  round(a.alpha() + (b.alpha() - a.alpha()) * t))


def _painter(w) -> QPainter:
    p = QPainter(w)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    return p


class _HoverButton(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)

    def _bg(self, base: QColor = theme.CARD) -> QColor:
        if self.isDown():
            return base.darker(115)
        return theme.CARD_HOVER if self.underMouse() and self.isEnabled() else base


class CircleButton(_HoverButton):
    """Botão redondo com ícone (−, +)."""

    def __init__(self, icon_name: str, size: int = 40, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.setFixedSize(size, size)
        self.setAutoRepeat(True)
        self.setAutoRepeatDelay(350)
        self.setAutoRepeatInterval(90)

    def paintEvent(self, _):
        p = _painter(self)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(theme.CARD_BORDER, 1))
        p.setBrush(self._bg())
        p.drawEllipse(r)
        s = r.width() * 0.42
        icons.paint(p, self.icon_name, QRectF(r.center().x() - s / 2, r.center().y() - s / 2, s, s),
                    theme.TEXT if self.isEnabled() else theme.DIM, 1.8)


class PowerButton(_HoverButton):
    """Botão liga/desliga do canto superior direito; brilha na cor da lâmpada."""

    def __init__(self, size: int = 46, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.on = False
        self.accent = QColor(255, 190, 110)

    def set_state(self, on: bool, accent: QColor):
        self.on, self.accent = on, accent
        self.update()

    def paintEvent(self, _):
        p = _painter(self)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.on:
            glow = QRadialGradient(r.center(), r.width() / 2)
            glow.setColorAt(0.0, mix(theme.CARD, self.accent, 0.35))
            glow.setColorAt(1.0, mix(theme.CARD, self.accent, 0.12))
            p.setBrush(QBrush(glow))
            p.setPen(QPen(mix(theme.CARD, self.accent, 0.7), 1.2))
        else:
            p.setBrush(self._bg())
            p.setPen(QPen(theme.CARD_BORDER_ACTIVE if self.underMouse() else theme.CARD_BORDER, 1))
        p.drawEllipse(r)
        s = r.width() * 0.48
        icons.paint(p, "power", QRectF(r.center().x() - s / 2, r.center().y() - s / 2, s, s),
                    self.accent.lighter(115) if self.on else theme.TEXT, 2.0)


class Pill(_HoverButton):
    """Cápsula 'Cena ▾' (no lugar do 'Eco Mode' da referência)."""

    def __init__(self, icon_name: str, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.setFixedHeight(46)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        fm = QFontMetrics(theme.font(13.5, QFont.Weight.DemiBold))
        return QSize(min(200, 76 + fm.horizontalAdvance(self.text())), 46)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, _):
        p = _painter(self)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(theme.CARD_BORDER, 1))
        p.setBrush(self._bg())
        p.drawRoundedRect(r, 14, 14)
        icons.paint(p, self.icon_name, QRectF(14, r.center().y() - 9, 18, 18), theme.MUTED)
        p.setFont(theme.font(13.5, QFont.Weight.DemiBold))
        p.setPen(theme.TEXT)
        text_r = QRectF(42, 0, r.width() - 42 - 32, r.height())
        p.drawText(text_r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, int(text_r.width())))
        icons.paint(p, "chevron", QRectF(r.right() - 28, r.center().y() - 8, 16, 16), theme.MUTED)


class Tile(_HoverButton):
    """Card de modo (Brilho, Branco, Cor, Timer) como os da linha inferior da referência."""

    def __init__(self, icon_name: str, label: str, indicator: str = "", parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.label = label
        self.value = "—"
        self.indicator = indicator  # "chevron" | "dot" | ""
        self.dot = QColor(theme.DIM)
        self.active = False
        self.setMinimumSize(76, 88)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_value(self, value: str, dot: QColor = None):
        self.value = value
        if dot is not None:
            self.dot = dot
        self.update()

    def set_active(self, active: bool):
        self.active = active
        self.update()

    def paintEvent(self, _):
        p = _painter(self)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(theme.CARD_BORDER_ACTIVE if self.active else theme.CARD_BORDER, 1))
        p.setBrush(theme.CARD_ACTIVE if self.active else self._bg())
        p.drawRoundedRect(r, 14, 14)

        icon_color = theme.TEXT if self.active else theme.MUTED
        icons.paint(p, self.icon_name, QRectF(12, 12, 22, 22), icon_color, 1.5)
        if self.indicator == "chevron":
            icons.paint(p, "chevron", QRectF(r.right() - 26, 14, 16, 16), theme.MUTED)
        elif self.indicator == "dot":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.dot)
            p.drawEllipse(QPointF(r.right() - 16, 22), 4, 4)

        p.setFont(theme.font(11.5))
        p.setPen(theme.MUTED)
        p.drawText(QRectF(12, r.height() - 42, r.width() - 16, 16), Qt.AlignmentFlag.AlignLeft, self.label)
        p.setFont(theme.font(13, QFont.Weight.DemiBold))
        p.setPen(theme.TEXT if self.isEnabled() else theme.DIM)
        p.drawText(QRectF(12, r.height() - 25, r.width() - 14, 18), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(self.value, Qt.TextElideMode.ElideRight, int(r.width() - 14)))


class HeaderSelector(_HoverButton):
    """'💡 Lâmpada  Sala ▾' no canto superior esquerdo (como 'Room 23°C')."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.caption = ""
        self.value = ""
        self.setFixedHeight(32)

    def set_texts(self, caption: str, value: str):
        self.caption, self.value = caption, value
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        cap = theme.font(13)
        val = theme.font(14, QFont.Weight.Bold)
        w = 26 + QFontMetrics(cap).horizontalAdvance(self.caption) + 8 + \
            QFontMetrics(val).horizontalAdvance(self.value) + 26
        return QSize(min(w, 250), 32)

    def paintEvent(self, _):
        p = _painter(self)
        r = QRectF(self.rect())
        if self.underMouse():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 10))
            p.drawRoundedRect(r, 9, 9)
        icons.paint(p, "bulb", QRectF(4, r.center().y() - 9, 18, 18), theme.MUTED, 1.6)
        x = 26.0
        p.setFont(theme.font(13))
        p.setPen(theme.MUTED)
        p.drawText(QRectF(x, 0, 200, r.height()), Qt.AlignmentFlag.AlignVCenter, self.caption)
        x += p.fontMetrics().horizontalAdvance(self.caption) + 8
        p.setFont(theme.font(14, QFont.Weight.Bold))
        p.setPen(theme.TEXT)
        avail = int(r.width() - x - 24)
        text = p.fontMetrics().elidedText(self.value, Qt.TextElideMode.ElideRight, avail)
        p.drawText(QRectF(x, 0, avail, r.height()), Qt.AlignmentFlag.AlignVCenter, text)
        x += p.fontMetrics().horizontalAdvance(text) + 4
        icons.paint(p, "chevron", QRectF(x, r.center().y() - 7, 14, 14), theme.MUTED)


class IconButton(_HoverButton):
    """Ícone discreto do rodapé (rotinas, configurações)."""

    def __init__(self, icon_name: str, size: int = 30, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = _painter(self)
        r = QRectF(self.rect())
        if self.underMouse():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 14))
            p.drawRoundedRect(r, 8, 8)
        s = r.width() * 0.66
        icons.paint(p, self.icon_name, QRectF((r.width() - s) / 2, (r.height() - s) / 2, s, s),
                    theme.TEXT if self.underMouse() else theme.MUTED, 1.6)


class BigSlider(QWidget):
    """Slider largo com alça branca, como o de temperatura da referência.

    Modos: "brightness" (preenchimento na cor da lâmpada), "temperature"
    (quente → frio) e "hue" (arco-íris).
    """

    valueChanged = Signal(int)   # durante o arraste
    valueCommitted = Signal(int)  # ao soltar

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(54)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.mode = "brightness"
        self.minimum, self.maximum = 1, 100
        self.value = 50
        self.accent = QColor(255, 190, 110)
        self.dragging = False

    def configure(self, mode: str, minimum: int, maximum: int, value: int, accent: QColor):
        self.mode, self.minimum, self.maximum = mode, minimum, maximum
        self.accent = accent
        self.value = max(minimum, min(maximum, value))
        self.update()

    def set_value(self, value: int, accent: QColor = None):
        if self.dragging:
            return
        if accent is not None:
            self.accent = accent
        self.value = max(self.minimum, min(self.maximum, int(value)))
        self.update()

    def step(self, delta: int):
        self._set(self.value + delta, commit=True)

    # -- interação -----------------------------------------------------------
    def _value_at(self, x: float) -> int:
        pad = 18
        t = (x - pad) / max(1, self.width() - 2 * pad)
        return round(self.minimum + max(0.0, min(1.0, t)) * (self.maximum - self.minimum))

    def _set(self, v: int, commit: bool):
        v = max(self.minimum, min(self.maximum, int(v)))
        changed = v != self.value
        self.value = v
        self.update()
        if changed:
            self.valueChanged.emit(v)
        if commit:
            self.valueCommitted.emit(v)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self._set(self._value_at(e.position().x()), commit=False)

    def mouseMoveEvent(self, e):
        if self.dragging:
            self._set(self._value_at(e.position().x()), commit=False)

    def mouseReleaseEvent(self, e):
        if self.dragging:
            self.dragging = False
            self._set(self._value_at(e.position().x()), commit=True)

    def wheelEvent(self, e):
        step = max(1, (self.maximum - self.minimum) // 50)
        self._set(self.value + (step if e.angleDelta().y() > 0 else -step), commit=True)

    def keyPressEvent(self, e):
        step = max(1, (self.maximum - self.minimum) // 50)
        if e.key() in (Qt.Key.Key_Right, Qt.Key.Key_Up):
            self._set(self.value + step, commit=True)
        elif e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Down):
            self._set(self.value - step, commit=True)
        else:
            super().keyPressEvent(e)

    # -- pintura -------------------------------------------------------------
    def _gradient(self, r: QRectF, strength: float) -> QLinearGradient:
        g = QLinearGradient(r.topLeft(), r.topRight())
        if self.mode == "hue":
            for i in range(7):
                g.setColorAt(i / 6, mix(theme.TRACK, QColor.fromHsv(int(i * 60) % 360, 255, 255), strength))
        elif self.mode == "temperature":
            g.setColorAt(0, mix(theme.TRACK, QColor(255, 170, 80), strength))
            g.setColorAt(0.5, mix(theme.TRACK, QColor(255, 236, 210), strength))
            g.setColorAt(1, mix(theme.TRACK, QColor(200, 225, 255), strength))
        else:
            g.setColorAt(0, mix(theme.TRACK, self.accent, 0.18))
            g.setColorAt(1, mix(theme.TRACK, self.accent, 0.55))
        return g

    def paintEvent(self, _):
        p = _painter(self)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = 16
        track = QPainterPath()
        track.addRoundedRect(r, radius, radius)

        p.setPen(QPen(theme.CARD_BORDER, 1))
        p.setBrush(theme.TRACK if self.mode == "brightness" else QBrush(self._gradient(r, 0.22)))
        p.drawPath(track)

        span = max(1, self.maximum - self.minimum)
        t = (self.value - self.minimum) / span
        pad = 18
        hx = pad + t * (r.width() - 2 * pad)

        if self.mode == "brightness":
            fill = QPainterPath()
            fill.addRoundedRect(QRectF(r.left(), r.top(), max(hx + 14, 2 * radius), r.height()), radius, radius)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(self._gradient(QRectF(r.left(), r.top(), max(hx, 1), r.height()), 1)))
            p.drawPath(fill.intersected(track))
        else:
            # destaque leve até a alça para indicar o valor
            fill = QPainterPath()
            fill.addRoundedRect(QRectF(r.left(), r.top(), max(hx + 14, 2 * radius), r.height()), radius, radius)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(self._gradient(r, 0.5)))
            p.drawPath(fill.intersected(track))

        handle = QRectF(hx - 11, r.top() + 7, 22, r.height() - 14)
        p.setBrush(QColor(0, 0, 0, 70))
        p.drawRoundedRect(handle.translated(0, 1.5), 8, 8)
        p.setBrush(QColor(236, 236, 236) if self.isEnabled() else theme.DIM)
        p.drawRoundedRect(handle, 8, 8)
        if self.hasFocus():
            p.setPen(QPen(QColor(255, 255, 255, 60), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), radius - 1, radius - 1)


class BulbView(QWidget):
    """Ilustração da lâmpada (no lugar do ar-condicionado da referência)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(128)
        self.on = False
        self.color = QColor(255, 190, 110)
        self.level = 1.0

    def set_state(self, on: bool, color: QColor, brightness: int):
        self.on, self.color = on, color
        self.level = 0.35 + 0.65 * max(0, min(100, brightness)) / 100
        self.update()

    def paintEvent(self, _):
        p = _painter(self)
        cx, cy = self.width() / 2, 54.0
        rad = 34.0

        if self.on:  # halo elíptico que some por completo antes da borda
            p.save()
            p.translate(cx, cy)
            p.scale(1.7, 1.0)
            halo = QRadialGradient(QPointF(0, 0), 54)
            c = QColor(self.color)
            c.setAlpha(int(110 * self.level))
            halo.setColorAt(0, c)
            c2 = QColor(self.color)
            c2.setAlpha(int(30 * self.level))
            halo.setColorAt(0.5, c2)
            halo.setColorAt(1, QColor(0, 0, 0, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(halo))
            p.drawEllipse(QPointF(0, 0), 54, 54)
            p.restore()

        # vidro: círculo + pescoço afinando até a base
        glass = QPainterPath()
        glass.addEllipse(QPointF(cx, cy), rad, rad)
        neck = QPainterPath()
        neck.moveTo(cx - rad * 0.72, cy + rad * 0.62)
        neck.cubicTo(cx - rad * 0.45, cy + rad * 1.0, cx - rad * 0.48, cy + rad * 1.18, cx - rad * 0.48, cy + rad * 1.42)
        neck.lineTo(cx + rad * 0.48, cy + rad * 1.42)
        neck.cubicTo(cx + rad * 0.48, cy + rad * 1.18, cx + rad * 0.45, cy + rad * 1.0, cx + rad * 0.72, cy + rad * 0.62)
        neck.closeSubpath()
        glass = glass.united(neck)

        g = QRadialGradient(QPointF(cx - rad * 0.25, cy - rad * 0.3), rad * 1.6)
        if self.on:
            g.setColorAt(0, QColor(255, 255, 255))
            g.setColorAt(0.35, mix(QColor(255, 255, 255), self.color, 0.55))
            g.setColorAt(1, mix(self.color, QColor(40, 30, 20), 0.15))
        else:
            g.setColorAt(0, QColor(78, 78, 78))
            g.setColorAt(1, QColor(34, 34, 34))
        p.setBrush(QBrush(g))
        p.setPen(QPen(QColor(255, 255, 255, 40 if not self.on else 90), 1))
        p.drawPath(glass)

        # reflexo
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 110 if self.on else 40))
        p.drawEllipse(QRectF(cx - rad * 0.62, cy - rad * 0.62, rad * 0.32, rad * 0.5))

        # filamento
        if self.on:
            p.setPen(QPen(QColor(255, 255, 255, 200), 1.4))
        else:
            p.setPen(QPen(QColor(120, 120, 120), 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        f = QPainterPath()
        f.moveTo(cx - 9, cy + 22)
        f.lineTo(cx - 7, cy + 4)
        f.cubicTo(cx - 4, cy - 4, cx + 4, cy - 4, cx + 7, cy + 4)
        f.lineTo(cx + 9, cy + 22)
        p.drawPath(f)

        # rosca metálica (lembra o acabamento branco da referência)
        top = cy + rad * 1.42
        metal = QLinearGradient(QPointF(cx - 18, 0), QPointF(cx + 18, 0))
        metal.setColorAt(0, QColor(150, 150, 150))
        metal.setColorAt(0.35, QColor(235, 235, 235))
        metal.setColorAt(1, QColor(110, 110, 110))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(metal))
        for i in range(3):
            w = rad * 0.96 - i * 2
            p.drawRoundedRect(QRectF(cx - w / 2, top + 1 + i * 6.5, w, 5.5), 2.5, 2.5)
        p.setBrush(QColor(60, 60, 60))
        p.drawRoundedRect(QRectF(cx - 7, top + 20, 14, 5), 2.5, 2.5)
