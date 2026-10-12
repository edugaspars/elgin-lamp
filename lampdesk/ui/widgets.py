"""Componentes desenhados à mão: cápsulas de vidro, controles animados e a lâmpada."""

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient)
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget

from . import icons, theme


def mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(round(a.red() + (b.red() - a.red()) * t),
                  round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t),
                  round(a.alpha() + (b.alpha() - a.alpha()) * t))


def with_alpha(c: QColor, a: float) -> QColor:
    c = QColor(c)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


def luminance(c: QColor) -> float:
    return (0.2126 * c.red() + 0.7152 * c.green() + 0.0722 * c.blue()) / 255


def _painter(w) -> QPainter:
    p = QPainter(w)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    return p


def paint_glass(p: QPainter, path: QPainterPath, rect: QRectF, fill: QColor, border: QColor = None,
                rim: QColor = None):
    """Cápsula de vidro: preenchimento translúcido, contorno fino e borda iluminada no topo."""
    p.setPen(QPen(border or theme.CARD_BORDER, 1))
    p.setBrush(fill)
    p.drawPath(path)
    rim = rim or theme.CARD_RIM
    g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    g.setColorAt(0, rim)
    g.setColorAt(0.5, with_alpha(rim, 0))
    p.setPen(QPen(QBrush(g), 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    s = (rect.width() - 2) / rect.width() if rect.width() > 2 else 1
    inner = QPainterPath(path)
    c = rect.center()
    p.save()
    p.translate(c)
    p.scale(s, (rect.height() - 2) / rect.height() if rect.height() > 2 else 1)
    p.translate(-c)
    p.drawPath(inner)
    p.restore()


def keyboard_focus(w: QWidget) -> bool:
    """Anel de foco só para quem navega pelo teclado (como no macOS)."""
    return w.hasFocus() and getattr(w, "_focus_by_key", False)


class _KeyFocus:
    def focusInEvent(self, e):
        self._focus_by_key = e.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason)
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e):
        self._focus_by_key = False
        super().focusOutEvent(e)
        self.update()


def rounded(r: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(r, radius, radius)
    return path


def ellipse(r: QRectF) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(r)
    return path


class Fader:
    """Número que desliza até o alvo e repinta o widget a cada passo."""

    def __init__(self, widget: QWidget, value: float = 0.0, ms: int = 180,
                 curve: QEasingCurve.Type = QEasingCurve.Type.OutCubic):
        self.widget = widget
        self.value = self.target = float(value)
        self._anim = QVariantAnimation(widget)
        self._anim.setDuration(ms)
        self._anim.setEasingCurve(curve)
        self._anim.valueChanged.connect(self._step)

    def _step(self, v):
        self.value = float(v)
        self.widget.update()

    def to(self, target: float, animate: bool = True):
        target = float(target)
        if target == self.target:
            return
        self.target = target
        self._anim.stop()
        if not animate or not self.widget.isVisible():
            self.value = target
            self.widget.update()
            return
        self._anim.setStartValue(self.value)
        self._anim.setEndValue(target)
        self._anim.start()


class _HoverButton(QAbstractButton):
    """Botão com hover suave e leve 'afundar' ao clicar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._hover = Fader(self, 0, 140)
        self._press = Fader(self, 0, 90)
        self.pressed.connect(lambda: self._press.to(1))
        self.released.connect(lambda: self._press.to(0))

    def enterEvent(self, e):
        self._hover.to(1)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover.to(0)
        super().leaveEvent(e)

    def _fill(self, base: QColor = None, hover: QColor = None) -> QColor:
        base = theme.CARD if base is None else base
        t = self._hover.value if self.isEnabled() else 0
        return mix(base, theme.CARD_HOVER if hover is None else hover, t)

    def _begin(self) -> QPainter:
        p = _painter(self)
        s = 1 - 0.04 * self._press.value
        if s != 1:
            c = QRectF(self.rect()).center()
            p.translate(c)
            p.scale(s, s)
            p.translate(-c)
        return p


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
        p = self._begin()
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        paint_glass(p, ellipse(r), r, self._fill())
        s = r.width() * 0.4
        icons.paint(p, self.icon_name, QRectF(r.center().x() - s / 2, r.center().y() - s / 2, s, s),
                    theme.TEXT if self.isEnabled() else theme.DIM, 1.8)


class PowerButton(_HoverButton):
    """Liga/desliga do canto superior direito: vira um disco sólido na cor da lâmpada."""

    def __init__(self, size: int = 46, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.on = False
        self.accent = QColor(255, 190, 110)
        self._on = Fader(self, 0, 260)

    def set_state(self, on: bool, accent: QColor):
        self.on, self.accent = on, QColor(accent)
        self._on.to(1 if on else 0)
        self.update()

    def paintEvent(self, _):
        p = self._begin()
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        t = self._on.value
        paint_glass(p, ellipse(r), r, self._fill())
        glyph = theme.TEXT
        if t > 0:
            p.save()
            p.setOpacity(t)
            fill = QRadialGradient(QPointF(r.center().x(), r.top()), r.height() * 1.1)
            fill.setColorAt(0, self.accent.lighter(112))
            fill.setColorAt(1, self.accent)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(fill))
            p.drawEllipse(r)
            sheen = QLinearGradient(r.topLeft(), r.bottomLeft())  # reflexo de vidro líquido
            sheen.setColorAt(0, QColor(255, 255, 255, 110))
            sheen.setColorAt(0.55, QColor(255, 255, 255, 0))
            p.setBrush(QBrush(sheen))
            p.drawEllipse(r.adjusted(1, 1, -1, -1))
            p.setPen(QPen(QColor(255, 255, 255, 90), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(r.adjusted(0.5, 0.5, -0.5, -0.5))
            p.restore()
            on_glyph = QColor(29, 29, 31) if luminance(self.accent) > 0.62 else QColor(255, 255, 255)
            glyph = mix(theme.TEXT, on_glyph, t)
        s = r.width() * 0.46
        icons.paint(p, "power", QRectF(r.center().x() - s / 2, r.center().y() - s / 2, s, s), glyph, 2.0)


class Pill(_HoverButton):
    """Cápsula 'Cenas ▾'."""

    def __init__(self, icon_name: str, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.setFixedHeight(46)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        fm = QFontMetrics(theme.font(13.5, QFont.Weight.DemiBold))
        return QSize(min(200, 84 + fm.horizontalAdvance(self.text())), 46)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, _):
        p = self._begin()
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        paint_glass(p, rounded(r, r.height() / 2), r, self._fill())
        icons.paint(p, self.icon_name, QRectF(16, r.center().y() - 9, 18, 18), theme.MUTED)
        p.setFont(theme.font(13.5, QFont.Weight.DemiBold))
        p.setPen(theme.TEXT)
        text_r = QRectF(42, 0, r.width() - 42 - 34, r.height())
        p.drawText(text_r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, int(text_r.width())))
        icons.paint(p, "chevron", QRectF(r.right() - 30, r.center().y() - 8, 16, 16), theme.MUTED)


class Tile(_HoverButton):
    """Card de modo (Brilho, Branco, Cor, Timer); o ativo fica invertido, como no Control Center."""

    def __init__(self, icon_name: str, label: str, indicator: str = "", parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.label = label
        self.value = "—"
        self.indicator = indicator  # "chevron" | "dot" | ""
        self.dot = None
        self.active = False
        self._act = Fader(self, 0, 220)
        self.setMinimumSize(76, 88)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_value(self, value: str, dot: QColor = None):
        self.value = value
        if dot is not None:
            self.dot = QColor(dot)
        self.update()

    def set_active(self, active: bool):
        self.active = active
        self._act.to(1 if active else 0)

    def paintEvent(self, _):
        p = self._begin()
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        a = self._act.value
        fill = mix(self._fill(), theme.INVERSE, a)
        border = mix(theme.CARD_BORDER, with_alpha(theme.INVERSE, 0.0), a)
        paint_glass(p, rounded(r, 20), r, fill, border)

        text = mix(theme.TEXT, theme.INVERSE_TEXT, a) if self.isEnabled() else theme.DIM
        muted = mix(theme.MUTED, theme.INVERSE_MUTED, a)
        icons.paint(p, self.icon_name, QRectF(13, 13, 22, 22), text if a > 0.5 else mix(theme.MUTED, text, a), 1.6)
        if self.indicator == "chevron":
            icons.paint(p, "chevron", QRectF(r.right() - 27, 15, 16, 16), muted)
        elif self.indicator == "dot":
            p.setPen(QPen(with_alpha(text, 0.25), 1))
            p.setBrush(self.dot if self.dot is not None else theme.DIM)
            p.drawEllipse(QPointF(r.right() - 17, 23), 4.5, 4.5)

        p.setFont(theme.font(11.5))
        p.setPen(muted)
        p.drawText(QRectF(13, r.height() - 42, r.width() - 16, 16), Qt.AlignmentFlag.AlignLeft, self.label)
        p.setFont(theme.font(13.5, QFont.Weight.DemiBold))
        p.setPen(text)
        p.drawText(QRectF(13, r.height() - 25, r.width() - 15, 18), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(self.value, Qt.TextElideMode.ElideRight, int(r.width() - 15)))


class HeaderSelector(_HoverButton):
    """'Lâmpada  Sala ▾' no canto superior esquerdo."""

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
        w = 30 + QFontMetrics(cap).horizontalAdvance(self.caption) + 8 + \
            QFontMetrics(val).horizontalAdvance(self.value) + 28
        return QSize(min(w, 250), 32)

    def paintEvent(self, _):
        p = self._begin()
        r = QRectF(self.rect())
        if self._hover.value > 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(with_alpha(theme.HOVER, theme.HOVER.alphaF() * self._hover.value))
            p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        icons.paint(p, "bulb", QRectF(8, r.center().y() - 9, 18, 18), theme.MUTED, 1.6)
        x = 30.0
        p.setFont(theme.font(13))
        p.setPen(theme.MUTED)
        p.drawText(QRectF(x, 0, 200, r.height()), Qt.AlignmentFlag.AlignVCenter, self.caption)
        x += p.fontMetrics().horizontalAdvance(self.caption) + 8
        p.setFont(theme.font(14, QFont.Weight.Bold))
        p.setPen(theme.TEXT)
        avail = int(r.width() - x - 26)
        text = p.fontMetrics().elidedText(self.value, Qt.TextElideMode.ElideRight, avail)
        p.drawText(QRectF(x, 0, avail, r.height()), Qt.AlignmentFlag.AlignVCenter, text)
        x += p.fontMetrics().horizontalAdvance(text) + 4
        icons.paint(p, "chevron", QRectF(x, r.center().y() - 7, 14, 14), theme.MUTED)


class IconButton(_HoverButton):
    """Ícone discreto do rodapé (rotinas, configurações)."""

    def __init__(self, icon_name: str, size: int = 32, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = self._begin()
        r = QRectF(self.rect())
        h = self._hover.value
        if h > 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(with_alpha(theme.HOVER, theme.HOVER.alphaF() * h))
            p.drawEllipse(r)
        s = r.width() * 0.6
        icons.paint(p, self.icon_name, QRectF((r.width() - s) / 2, (r.height() - s) / 2, s, s),
                    mix(theme.MUTED, theme.TEXT, h), 1.6)


class BigSlider(_KeyFocus, QWidget):
    """Slider largo de vidro com alça em cápsula.

    Modos: "brightness" (preenchimento na cor da lâmpada), "temperature"
    (quente → frio) e "hue" (arco-íris).
    """

    valueChanged = Signal(int)   # durante o arraste
    valueCommitted = Signal(int)  # ao soltar

    PAD = 18

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
        self._pos = Fader(self, self._t(), 240)

    def _t(self, value: int = None) -> float:
        value = self.value if value is None else value
        return (value - self.minimum) / max(1, self.maximum - self.minimum)

    def configure(self, mode: str, minimum: int, maximum: int, value: int, accent: QColor):
        changed_mode = mode != self.mode
        self.mode, self.minimum, self.maximum = mode, minimum, maximum
        self.accent = QColor(accent)
        self.value = max(minimum, min(maximum, value))
        self._pos.to(self._t(), animate=not changed_mode)
        self.update()

    def set_value(self, value: int, accent: QColor = None):
        if self.dragging:
            return
        if accent is not None:
            self.accent = QColor(accent)
        self.value = max(self.minimum, min(self.maximum, int(value)))
        self._pos.to(self._t())
        self.update()

    def step(self, delta: int):
        self._set(self.value + delta, commit=True, animate=True)

    # -- interação -----------------------------------------------------------
    def _value_at(self, x: float) -> int:
        t = (x - self.PAD) / max(1, self.width() - 2 * self.PAD)
        return round(self.minimum + max(0.0, min(1.0, t)) * (self.maximum - self.minimum))

    def _set(self, v: int, commit: bool, animate: bool = False):
        v = max(self.minimum, min(self.maximum, int(v)))
        changed = v != self.value
        self.value = v
        self._pos.to(self._t(), animate=animate)
        self.update()
        if changed:
            self.valueChanged.emit(v)
        if commit:
            self.valueCommitted.emit(v)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self._set(self._value_at(e.position().x()), commit=False, animate=True)

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
            self._set(self.value + step, commit=True, animate=True)
        elif e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Down):
            self._set(self.value - step, commit=True, animate=True)
        else:
            super().keyPressEvent(e)

    # -- pintura -------------------------------------------------------------
    def _gradient(self, r: QRectF, strength: float) -> QLinearGradient:
        g = QLinearGradient(r.topLeft(), r.topRight())
        if self.mode == "hue":
            for i in range(7):
                g.setColorAt(i / 6, with_alpha(QColor.fromHsv(int(i * 60) % 360, 235, 255), strength))
        elif self.mode == "temperature":
            g.setColorAt(0, with_alpha(QColor(255, 166, 76), strength))
            g.setColorAt(0.5, with_alpha(QColor(255, 236, 214), strength))
            g.setColorAt(1, with_alpha(QColor(190, 220, 255), strength))
        else:
            g.setColorAt(0, with_alpha(self.accent, theme.FILL_LOW))
            g.setColorAt(1, with_alpha(self.accent, theme.FILL_HIGH))
        return g

    def paintEvent(self, _):
        p = _painter(self)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = r.height() / 2 - 6
        track = rounded(r, radius)
        if self.mode == "brightness":
            paint_glass(p, track, r, theme.TRACK)
        else:
            paint_glass(p, track, r, theme.TRACK)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(self._gradient(r, 0.30 if theme.DARK else 0.42)))
            p.drawPath(track)

        hx = self.PAD + self._pos.value * (r.width() - 2 * self.PAD)
        fill = rounded(QRectF(r.left(), r.top(), max(hx + 14, 2 * radius), r.height()), radius)
        p.setPen(Qt.PenStyle.NoPen)
        if self.mode == "brightness":
            p.setBrush(QBrush(self._gradient(QRectF(r.left(), r.top(), max(hx, 1), r.height()), 1)))
        else:
            p.setBrush(QBrush(self._gradient(r, 0.78 if theme.DARK else 0.9)))
        p.drawPath(fill.intersected(track))
        sheen = QLinearGradient(r.topLeft(), r.bottomLeft())  # reflexo sobre o preenchimento
        sheen.setColorAt(0, QColor(255, 255, 255, 46))
        sheen.setColorAt(0.5, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(sheen))
        p.drawPath(fill.intersected(track))

        handle = QRectF(hx - 11, r.top() + 7, 22, r.height() - 14)
        for spread, a in ((3.0, 0.18), (1.5, 0.35)):  # sombra macia em duas camadas
            p.setBrush(with_alpha(theme.HANDLE_SHADOW, theme.HANDLE_SHADOW.alphaF() * a))
            p.drawRoundedRect(handle.adjusted(-spread / 2, 0, spread / 2, spread), 11, 11)
        p.setBrush(theme.HANDLE if self.isEnabled() else theme.DIM)
        p.drawRoundedRect(handle, 11, 11)
        if keyboard_focus(self):
            p.setPen(QPen(theme.CARD_BORDER_ACTIVE, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), radius - 1, radius - 1)


class BulbView(QWidget):
    """Ilustração da lâmpada; acende e apaga com transição."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(128)
        self.on = False
        self.color = QColor(255, 190, 110)
        self._on = Fader(self, 0, 320)
        self._level = Fader(self, 1.0, 240)

    def set_state(self, on: bool, color: QColor, brightness: int):
        self.on, self.color = on, QColor(color)
        self._on.to(1 if on else 0)
        self._level.to(0.35 + 0.65 * max(0, min(100, brightness)) / 100)
        self.update()

    def _glass_path(self, cx, cy, rad) -> QPainterPath:
        glass = QPainterPath()
        glass.addEllipse(QPointF(cx, cy), rad, rad)
        neck = QPainterPath()
        neck.moveTo(cx - rad * 0.72, cy + rad * 0.62)
        neck.cubicTo(cx - rad * 0.45, cy + rad * 1.0, cx - rad * 0.48, cy + rad * 1.18, cx - rad * 0.48, cy + rad * 1.42)
        neck.lineTo(cx + rad * 0.48, cy + rad * 1.42)
        neck.cubicTo(cx + rad * 0.48, cy + rad * 1.18, cx + rad * 0.45, cy + rad * 1.0, cx + rad * 0.72, cy + rad * 0.62)
        neck.closeSubpath()
        return glass.united(neck)

    def paintEvent(self, _):
        p = _painter(self)
        cx, cy = self.width() / 2, 54.0
        rad = 34.0
        t, level = self._on.value, self._level.value

        if t > 0:  # halo elíptico que some por completo antes da borda
            p.save()
            p.translate(cx, cy)
            p.scale(1.7, 1.0)
            halo = QRadialGradient(QPointF(0, 0), 54)
            boost = 1.0 if theme.DARK else 0.8
            halo.setColorAt(0, with_alpha(self.color, 0.45 * level * t * boost))
            halo.setColorAt(0.5, with_alpha(self.color, 0.12 * level * t * boost))
            halo.setColorAt(1, with_alpha(self.color, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(halo))
            p.drawEllipse(QPointF(0, 0), 54, 54)
            p.restore()

        glass = self._glass_path(cx, cy, rad)
        off = QRadialGradient(QPointF(cx - rad * 0.25, cy - rad * 0.3), rad * 1.6)
        off.setColorAt(0, theme.BULB_OFF_HI)
        off.setColorAt(1, theme.BULB_OFF_LO)
        p.setBrush(QBrush(off))
        p.setPen(QPen(theme.BULB_OFF_EDGE, 1))
        p.drawPath(glass)
        if t > 0:
            p.save()
            p.setOpacity(t)
            g = QRadialGradient(QPointF(cx - rad * 0.25, cy - rad * 0.3), rad * 1.6)
            g.setColorAt(0, QColor(255, 255, 255))
            g.setColorAt(0.35, mix(QColor(255, 255, 255), self.color, 0.55))
            g.setColorAt(1, mix(self.color, QColor(40, 30, 20), 0.15))
            p.setBrush(QBrush(g))
            p.setPen(QPen(QColor(255, 255, 255, 90), 1))
            p.drawPath(glass)
            p.restore()

        # reflexo
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, round(40 + 70 * t) if theme.DARK else round(150 + 20 * t)))
        p.drawEllipse(QRectF(cx - rad * 0.62, cy - rad * 0.62, rad * 0.32, rad * 0.5))

        # filamento
        off_fil = QColor(120, 120, 120) if theme.DARK else QColor(170, 170, 176)
        p.setPen(QPen(mix(off_fil, QColor(255, 255, 255, 220), t), 1.2 + 0.2 * t))
        p.setBrush(Qt.BrushStyle.NoBrush)
        f = QPainterPath()
        f.moveTo(cx - 9, cy + 22)
        f.lineTo(cx - 7, cy + 4)
        f.cubicTo(cx - 4, cy - 4, cx + 4, cy - 4, cx + 7, cy + 4)
        f.lineTo(cx + 9, cy + 22)
        p.drawPath(f)

        # rosca metálica
        top = cy + rad * 1.42
        metal = QLinearGradient(QPointF(cx - 18, 0), QPointF(cx + 18, 0))
        metal.setColorAt(0, QColor(150, 150, 150))
        metal.setColorAt(0.35, QColor(238, 238, 238))
        metal.setColorAt(1, QColor(110, 110, 110))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(metal))
        for i in range(3):
            w = rad * 0.96 - i * 2
            p.drawRoundedRect(QRectF(cx - w / 2, top + 1 + i * 6.5, w, 5.5), 2.5, 2.5)
        p.setBrush(QColor(60, 60, 60) if theme.DARK else QColor(90, 90, 96))
        p.drawRoundedRect(QRectF(cx - 7, top + 20, 14, 5), 2.5, 2.5)


class Segmented(_KeyFocus, QWidget):
    """Controle segmentado no estilo Apple: o destaque desliza até a opção escolhida."""

    currentChanged = Signal(int)

    def __init__(self, items=(), parent=None):
        super().__init__(parent)
        self.items = list(items)
        self.index = 0
        self._x = Fader(self, 0, 240)
        self.setFixedHeight(32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def addItem(self, label: str):
        self.items.append(label)
        self.updateGeometry()
        self.update()

    def currentIndex(self) -> int:
        return self.index

    def setCurrentIndex(self, i: int, animate: bool = True):
        i = max(0, min(len(self.items) - 1, i))
        if i == self.index:
            return
        self.index = i
        self._x.to(i, animate)
        self.currentChanged.emit(i)

    def sizeHint(self):
        fm = QFontMetrics(theme.font(13, QFont.Weight.DemiBold))
        w = max((fm.horizontalAdvance(t) for t in self.items), default=40) + 36
        return QSize(4 + w * max(1, len(self.items)), 32)

    def _seg(self) -> float:
        return (self.width() - 4) / max(1, len(self.items))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.items:
            self.setCurrentIndex(int((e.position().x() - 2) // self._seg()))

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self.setCurrentIndex(self.index + 1)
        elif e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.setCurrentIndex(self.index - 1)
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _):
        p = _painter(self)
        r = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.SEGMENT)
        p.drawRoundedRect(r, 9, 9)
        seg = self._seg()
        chip = QRectF(2 + self._x.value * seg, 2, seg, r.height() - 4)
        if not theme.DARK:
            p.setBrush(QColor(0, 0, 0, 14))
            p.drawRoundedRect(chip.adjusted(0, 0.5, 0, 1.5), 7, 7)
        p.setBrush(theme.SEGMENT_SEL)
        p.drawRoundedRect(chip, 7, 7)
        if keyboard_focus(self):
            p.setPen(QPen(theme.CARD_BORDER_ACTIVE, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(0.75, 0.75, -0.75, -0.75), 9, 9)
        for i, text in enumerate(self.items):
            sel = i == self.index
            p.setFont(theme.font(13, QFont.Weight.DemiBold if sel else QFont.Weight.Medium))
            p.setPen(theme.TEXT)
            p.drawText(QRectF(2 + i * seg, 0, seg, r.height()), Qt.AlignmentFlag.AlignCenter, text)


class SegmentedTabs(QWidget):
    """Abas com um controle segmentado no topo (substitui o QTabWidget)."""

    currentChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        row = QHBoxLayout()
        self.bar = Segmented()
        row.addWidget(self.bar)
        row.addStretch(1)
        v.addLayout(row)
        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)
        self.bar.currentChanged.connect(self._changed)

    def _changed(self, i: int):
        self.stack.setCurrentIndex(i)
        self.currentChanged.emit(i)

    def addTab(self, widget: QWidget, label: str):
        self.stack.addWidget(widget)
        self.bar.addItem(label)

    def count(self) -> int:
        return self.stack.count()

    def widget(self, i: int) -> QWidget:
        return self.stack.widget(i)

    def currentIndex(self) -> int:
        return self.stack.currentIndex()

    def setCurrentIndex(self, i: int):
        self.bar.setCurrentIndex(i)
        self.stack.setCurrentIndex(self.bar.currentIndex())
