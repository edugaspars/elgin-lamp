"""Painel flutuante aberto pelo ícone da bandeja."""

import time

from PySide6.QtCore import (QEasingCurve, QEvent, QParallelAnimationGroup, QPoint, QPointF, QPropertyAnimation, QRect,
                            QRectF, Qt, QTimer, Signal)
from PySide6.QtGui import QAction, QActionGroup, QColor, QCursor, QFont, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QColorDialog, QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..i18n import tr
from ..lamp import LampState, display_rgb, rgb_from_hue
from . import glass, icons, theme
from .tray import style_menu
from .widgets import BigSlider, BulbView, CircleButton, Fader, HeaderSelector, IconButton, Pill, PowerButton, Tile

WIDTH = 400
SHADOW = 22
ARROW = 10
SLIDE = 10  # deslocamento da animação de abertura


def temp_label(pct: int) -> str:
    if pct < 34:
        return tr("temp.warm")
    if pct < 67:
        return tr("temp.neutral")
    return tr("temp.cool")


def fmt_remaining(sec: int) -> str:
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class Popup(QWidget):
    openSettings = Signal(str)

    def __init__(self, store, service, parent=None):
        super().__init__(parent)
        self.store = store
        self.service = service
        self.selection = store.config.settings.last_selected or "*"
        self.slider_mode = "brightness"
        self.last_scene = ""
        self._arrow_up = False
        self._arrow_x = WIDTH / 2
        self._hidden_at = 0.0
        self._suffix = ""
        self._backdrop = None
        self._glow = QColor(255, 190, 110)
        self._glow_level = Fader(self, 0, 420)

        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(WIDTH + 2 * SHADOW)
        self.setStyleSheet(theme.popup_qss())

        self._send_timer = QTimer(self, singleShot=True, interval=60)
        self._send_timer.timeout.connect(self._send_slider)
        self._tick = QTimer(self, interval=1000)
        self._tick.timeout.connect(self._update_timer_tile)

        self._opening = QParallelAnimationGroup(self)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._slide = QPropertyAnimation(self, b"pos", self)
        for a in (self._fade, self._slide):
            a.setDuration(240)
            a.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._opening.addAnimation(a)

        self._build()
        # métodos (e não lambdas): o Qt desconecta sozinho quando o painel é destruído
        service.stateChanged.connect(self._on_state)
        service.timersChanged.connect(self._update_timer_tile)
        QApplication.instance().applicationStateChanged.connect(self._on_app_state)

    # ------------------------------------------------------------ montagem ---
    def _build(self):
        root = QVBoxLayout(self)
        self._root = root
        root.setSpacing(0)

        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        # ---- página principal
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        head = QHBoxLayout()
        self.selector = HeaderSelector()
        self.selector.clicked.connect(self._choose_lamp)
        self.power = PowerButton()
        self.power.clicked.connect(self._toggle_power)
        head.addWidget(self.selector)
        head.addStretch(1)
        head.addWidget(self.power)
        v.addLayout(head)

        self.bulb = BulbView()
        v.addWidget(self.bulb)

        row = QHBoxLayout()
        row.setSpacing(4)
        num = QVBoxLayout()
        num.setSpacing(0)
        line = QHBoxLayout()
        line.setSpacing(4)
        self.big = QLabel("—")
        self.big.setFont(theme.font(60, QFont.Weight.DemiBold, tracking=-3))
        self.unit = QLabel("%")
        self.unit.setFont(theme.font(24, QFont.Weight.Normal))
        self.unit.setStyleSheet(f"color: {theme.css(theme.MUTED)};")
        line.addWidget(self.big, 0, Qt.AlignmentFlag.AlignBottom)
        line.addWidget(self.unit, 0, Qt.AlignmentFlag.AlignBottom)
        line.addStretch(1)
        self.unit.setContentsMargins(0, 0, 0, 12)
        num.addLayout(line)
        row.addLayout(num, 1)
        self.scene_pill = Pill("sparkles")
        self.scene_pill.clicked.connect(self._choose_scene)
        row.addWidget(self.scene_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        v.addLayout(row)
        v.addSpacing(6)

        srow = QHBoxLayout()
        srow.setSpacing(10)
        self.minus = CircleButton("minus")
        self.plus = CircleButton("plus")
        self.slider = BigSlider()
        self.minus.clicked.connect(lambda: self.slider.step(-self._step()))
        self.plus.clicked.connect(lambda: self.slider.step(self._step()))
        self.slider.valueChanged.connect(self._slider_moved)
        self.slider.valueCommitted.connect(self._slider_committed)
        srow.addWidget(self.minus)
        srow.addWidget(self.slider, 1)
        srow.addWidget(self.plus)
        v.addLayout(srow)

        lrow = QHBoxLayout()
        lrow.setContentsMargins(56, 6, 56, 0)
        self.lo = QLabel()
        self.hi = QLabel()
        for lbl in (self.lo, self.hi):
            lbl.setMinimumWidth(80)
            lbl.setFont(theme.font(11.5, QFont.Weight.DemiBold))
            lbl.setStyleSheet(f"color: {theme.css(theme.MUTED)};")
        lrow.addWidget(self.lo)
        lrow.addStretch(1)
        lrow.addWidget(self.hi)
        self.hi.setAlignment(Qt.AlignmentFlag.AlignRight)
        v.addLayout(lrow)
        v.addSpacing(16)

        tiles = QHBoxLayout()
        tiles.setSpacing(8)
        self.t_bright = Tile("sun", tr("brightness"))
        self.t_temp = Tile("thermo", tr("white"))
        self.t_color = Tile("palette", tr("color"), "dot")
        self.t_timer = Tile("moon", tr("timer"), "chevron")
        self.t_bright.clicked.connect(lambda: self._set_mode("brightness"))
        self.t_temp.clicked.connect(lambda: self._set_mode("temperature"))
        self.t_color.clicked.connect(self._color_clicked)
        self.t_timer.clicked.connect(self._choose_timer)
        for t in (self.t_bright, self.t_temp, self.t_color, self.t_timer):
            tiles.addWidget(t)
        v.addLayout(tiles)
        v.addSpacing(16)
        v.addLayout(self._footer())
        self.stack.addWidget(page)

        # ---- página vazia (primeiro uso)
        empty = QWidget()
        e = QVBoxLayout(empty)
        e.setContentsMargins(0, 8, 0, 0)
        e.setSpacing(10)
        title = QLabel(tr("empty.title"))
        title.setFont(theme.font(18, QFont.Weight.DemiBold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body = QLabel(tr("empty.body"))
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setStyleSheet(f"color: {theme.css(theme.MUTED)};")
        add = QPushButton(tr("empty.add"))
        add.setProperty("primary", True)
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.clicked.connect(lambda: self.openSettings.emit("lamps"))
        empty_bulb = BulbView()
        e.addWidget(empty_bulb)
        e.addWidget(title)
        e.addWidget(body)
        e.addSpacing(6)
        e.addWidget(add)
        e.addSpacing(10)
        self.stack.addWidget(empty)

    def _footer(self):
        f = QHBoxLayout()
        f.setSpacing(6)
        self.status_icon = QLabel()
        self.status_text = QLabel()
        self.status_text.setFont(theme.font(12))
        self.status_text.setStyleSheet(f"color: {theme.css(theme.MUTED)};")
        routines = IconButton("clock")
        routines.setToolTip(tr("routines"))
        routines.clicked.connect(lambda: self.openSettings.emit("routines"))
        settings = IconButton("sliders")
        settings.setToolTip(tr("settings"))
        settings.clicked.connect(lambda: self.openSettings.emit("lamps"))
        f.addWidget(self.status_icon)
        f.addWidget(self.status_text)
        f.addStretch(1)
        f.addWidget(routines)
        f.addWidget(settings)
        return f

    # ------------------------------------------------------------- estado ---
    def ids(self):
        return self.service.ids(self.selection)

    def _state(self) -> LampState:
        states = [self.service.state(i) for i in self.ids()]
        if not states:
            return LampState()
        for s in states:
            if s.online and s.is_on:
                return s
        return states[0]

    def update_view(self):
        lamps = self.store.config.lamps
        page = 0 if lamps else 1
        for i in range(self.stack.count()):  # a página oculta não ocupa espaço
            policy = QSizePolicy.Policy.Preferred if i == page else QSizePolicy.Policy.Ignored
            self.stack.widget(i).setSizePolicy(policy, policy)
        self.stack.setCurrentIndex(page)
        if not lamps:
            return
        if self.selection != "*" and not self.store.config.lamp(self.selection):
            self.selection = "*"

        name = tr("all_lamps") if self.selection == "*" else self.store.config.lamp(self.selection).name
        self.selector.set_texts(tr("lamp") if self.selection != "*" else tr("lamps"), name)

        s = self._state()
        accent = QColor(*display_rgb(s))
        on = s.is_on and s.online
        self.power.set_state(on, accent)
        self.bulb.set_state(on, accent, s.brightness)
        self._glow = accent
        self._glow_level.to((0.45 + 0.55 * s.brightness / 100) if on else 0)

        self.t_temp.setEnabled(s.has_temperature)
        self.t_color.setEnabled(s.has_colour)
        if self.slider_mode == "temperature" and not s.has_temperature or \
                self.slider_mode == "hue" and not s.has_colour:
            self.slider_mode = "brightness"

        if self.slider_mode == "brightness":
            value, unit, lo, hi, labels = s.brightness, "%", 1, 100, ("1%", "100%")
        elif self.slider_mode == "temperature":
            value, unit, lo, hi, labels = s.temperature, "%", 0, 100, (tr("temp.warm"), tr("temp.cool"))
        else:
            value, unit, lo, hi, labels = s.hue, "", 0, 359, ("0°", "360°")
        self._suffix = "°" if self.slider_mode == "hue" else ""
        if not self.slider.dragging:
            self._set_big(value)
            self.slider.configure(self.slider_mode, lo, hi, value, accent)
        self.unit.setText(unit)
        self.lo.setText(labels[0])
        self.hi.setText(labels[1])

        self.t_bright.set_value(f"{s.brightness}%")
        self.t_temp.set_value(temp_label(s.temperature) if s.mode == "white" else "—")
        self.t_color.set_value(QColor(*s.color).name().upper() if s.mode == "colour" else "—",
                               QColor(*s.color) if s.mode == "colour" else theme.DIM)
        for t, mode in ((self.t_bright, "brightness"), (self.t_temp, "temperature"), (self.t_color, "hue")):
            t.set_active(self.slider_mode == mode)
        self._update_timer_tile()

        self.scene_pill.setText(self.last_scene or tr("scenes"))
        self.scene_pill.updateGeometry()

        states = [self.service.state(i) for i in self.ids()]
        online = sum(1 for st in states if st.online)
        if online == len(states):
            text, ic, col = tr("status.connected"), "shield", theme.MUTED
        elif any(st.error for st in states):
            text = tr("status.partial", n=online, total=len(states)) if online else tr("status.offline")
            ic, col = "shield-x", theme.ERROR if not online else theme.WARN
        else:
            text, ic, col = tr("status.connecting"), "shield", theme.DIM
        self.status_icon.setPixmap(icons.pixmap(ic, 15, col))
        self.status_text.setText(text)
        err = next((st.error for st in states if st.error), "")
        self.status_text.setToolTip(err)
        self._root.activate()

    def _on_state(self, *_):
        if self.isVisible():
            self.update_view()

    def _on_app_state(self, state):
        # no Windows o painel às vezes não recebe foco; fecha quando o app perde o foco
        if state != Qt.ApplicationState.ApplicationActive and self.isVisible():
            QTimer.singleShot(150, self._maybe_hide)

    def _update_timer_tile(self):
        rem = self.service.timer_remaining(self.selection)
        self.t_timer.set_value(fmt_remaining(rem) if rem is not None else tr("off"))

    # ------------------------------------------------------------- ações ---
    def _step(self):
        return 10 if self.slider_mode == "hue" else 5

    def _set_mode(self, mode):
        self.slider_mode = mode
        self.update_view()

    def _color_clicked(self):
        if self.slider_mode != "hue":
            self._set_mode("hue")
            return
        s = self._state()
        c = QColorDialog.getColor(QColor(*s.color), self, tr("pick_color"))
        if c.isValid():
            self.service.set_color(self.ids(), (c.red(), c.green(), c.blue()))
            self.last_scene = ""

    def _toggle_power(self):
        self.service.toggle(self.ids())

    def _set_big(self, v):
        text = f"{v}{self._suffix}"
        self.big.setText(text)
        self.big.setMinimumWidth(self.big.fontMetrics().horizontalAdvance(text) + 4)

    def _slider_moved(self, v):
        self._set_big(v)
        if not self._send_timer.isActive():
            self._send_timer.start()

    def _slider_committed(self, _v):
        self._send_timer.stop()
        self._send_slider()

    def _send_slider(self):
        v = self.slider.value
        ids = self.ids()
        if self.slider_mode == "brightness":
            self.service.set_brightness(ids, v)
        elif self.slider_mode == "temperature":
            self.service.set_temperature(ids, v)
        else:
            self.service.set_color(ids, rgb_from_hue(v))
        self.last_scene = ""

    def _menu(self):
        m = QMenu(self)
        style_menu(m)
        return m

    def _choose_lamp(self):
        m = self._menu()
        group = QActionGroup(m)
        options = [("*", tr("all_lamps"))] + [(l.id, l.name) for l in self.store.config.lamps]
        for key, label in options:
            st = None if key == "*" else self.service.state(key)
            suffix = "" if st is None else ("  ●" if st.online and st.is_on else ("  ○" if st.online else "  ⚠"))
            a = QAction(label + suffix, m, checkable=True, checked=key == self.selection)
            a.triggered.connect(lambda _=False, k=key: self._select(k))
            group.addAction(a)
            m.addAction(a)
            if key == "*":
                m.addSeparator()
        m.exec(self.selector.mapToGlobal(QPoint(0, self.selector.height() + 4)))

    def _select(self, key):
        self.selection = key
        self.store.config.settings.last_selected = key
        self.store.save()
        self.service.refresh(self.ids())
        self.update_view()

    def _choose_scene(self):
        m = self._menu()
        for sc in self.store.config.scenes:
            a = m.addAction(sc.name)
            a.triggered.connect(lambda _=False, s=sc: self._apply_scene(s))
        if self.store.config.scenes:
            m.addSeparator()
        m.addAction(tr("manage_scenes")).triggered.connect(lambda: self.openSettings.emit("scenes"))
        m.exec(self.scene_pill.mapToGlobal(QPoint(0, self.scene_pill.height() + 4)))

    def _apply_scene(self, scene):
        self.service.apply_scene(self.ids(), scene)
        self.last_scene = scene.name
        self.update_view()

    def _choose_timer(self):
        m = self._menu()
        for minutes in (15, 30, 60, 120):
            label = tr("timer.minutes", n=minutes) if minutes < 60 else tr("timer.hours", n=minutes // 60)
            a = m.addAction(tr("timer.off_in", t=label))
            a.triggered.connect(lambda _=False, n=minutes: self.service.start_timer(self.selection, self.ids(), n))
        if self.service.timer_remaining(self.selection) is not None:
            m.addSeparator()
            m.addAction(tr("timer.cancel")).triggered.connect(lambda: self.service.cancel_timer(self.selection))
        m.exec(self.t_timer.mapToGlobal(QPoint(0, self.t_timer.height() + 4)))

    # ---------------------------------------------------------- janela ---
    def toggle_at(self, anchor: QRect):
        if self.isVisible():
            self.hide()
            return
        if time.monotonic() - self._hidden_at < 0.3:  # o clique na bandeja acabou de fechá-lo
            return
        self.show_at(anchor)

    def show_at(self, anchor: QRect = None):
        if anchor is None or not anchor.isValid() or anchor.isNull():
            pos = QCursor.pos()
            anchor = QRect(pos.x() - 8, pos.y() - 8, 16, 16)
        screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        self._arrow_up = anchor.center().y() < avail.center().y()

        top = SHADOW + (ARROW if self._arrow_up else 0) + 20
        bottom = SHADOW + (0 if self._arrow_up else ARROW) + 16
        self._root.setContentsMargins(SHADOW + 20, top, SHADOW + 20, bottom)
        self.update_view()
        self.adjustSize()
        w, h = self.width(), self.sizeHint().height()
        self.resize(w, h)

        x = anchor.center().x() - w // 2
        x = max(avail.left() + 4 - SHADOW, min(x, avail.right() - w + SHADOW - 4))
        if self._arrow_up:
            y = max(avail.top(), anchor.bottom()) + 2 - SHADOW
        else:
            y = min(avail.bottom(), anchor.top()) - h - 2 + SHADOW
        y = max(avail.top() - SHADOW, min(y, avail.bottom() - h + SHADOW))
        self._arrow_x = max(SHADOW + 36, min(anchor.center().x() - x, w - SHADOW - 36))
        # o fundo é capturado antes de mostrar (senão o próprio painel sai na foto)
        self._backdrop = glass.grab_backdrop(QRect(x, y, w, h)) if theme.TRANSPARENCY else None
        start = QPoint(x, y + (-SLIDE if self._arrow_up else SLIDE))
        self._opening.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._slide.setStartValue(start)
        self._slide.setEndValue(QPoint(x, y))
        self.setWindowOpacity(0.0)
        self.move(start)
        self.show()
        self.raise_()
        self.activateWindow()
        self._opening.start()
        self.service.refresh(self.ids())
        self._tick.start()

    def hideEvent(self, e):
        self._opening.stop()
        self.setWindowOpacity(1.0)
        self._hidden_at = time.monotonic()
        self._tick.stop()
        super().hideEvent(e)

    def event(self, e):
        if e.type() == QEvent.Type.WindowDeactivate and self.isVisible():
            QTimer.singleShot(120, self._maybe_hide)
        return super().event(e)

    def _maybe_hide(self):
        # menus e diálogos abertos a partir do painel não devem fechá-lo
        if QApplication.activePopupWidget() is None and QApplication.activeModalWidget() is None \
                and not self.isActiveWindow():
            self.hide()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(e)

    def _panel_path(self) -> QPainterPath:
        r = QRectF(self.rect()).adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW)
        if self._arrow_up:
            r.setTop(r.top() + ARROW)
        else:
            r.setBottom(r.bottom() - ARROW)
        path = QPainterPath()
        path.addRoundedRect(r, theme.RADIUS, theme.RADIUS)
        ax = self._arrow_x
        tri = QPainterPath()
        if self._arrow_up:
            tri.moveTo(ax - ARROW - 4, r.top() + 1)
            tri.quadTo(ax - 3, r.top() - ARROW + 1, ax, r.top() - ARROW)
            tri.quadTo(ax + 3, r.top() - ARROW + 1, ax + ARROW + 4, r.top() + 1)
        else:
            tri.moveTo(ax - ARROW - 4, r.bottom() - 1)
            tri.quadTo(ax - 3, r.bottom() + ARROW - 1, ax, r.bottom() + ARROW)
            tri.quadTo(ax + 3, r.bottom() + ARROW - 1, ax + ARROW + 4, r.bottom() - 1)
        tri.closeSubpath()
        return path.united(tri)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # repinturas parciais (um filho animando) não podem somar vidro translúcido sobre o que já estava
        # no buffer: limpa a área antes, senão surgem retângulos mais escuros ou furos que mostram a tela
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(e.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        path = self._panel_path()
        p.setBrush(Qt.BrushStyle.NoBrush)
        outside = QPainterPath()
        outside.addRect(QRectF(self.rect()))
        p.save()
        p.setClipPath(outside.subtracted(path))  # o vidro é translúcido: a sombra não pode vazar por baixo
        shadow = theme.SHADOW
        for i in range(SHADOW, 0, -2):  # sombra difusa, mais forte embaixo
            c = QColor(shadow)
            c.setAlphaF(shadow.alphaF() * (1 - i / SHADOW) ** 3)
            p.setPen(QPen(c, i * 2))
            p.drawPath(path.translated(0, 5))
        p.restore()
        center = QPointF(self.bulb.mapTo(self, QPoint(self.bulb.width() // 2, 54)))
        glass.paint_panel(p, path, self._backdrop, QRectF(self.rect()), self._glow, self._glow_level.value, center)
        p.end()
