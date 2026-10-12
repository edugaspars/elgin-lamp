"""Janela de configurações: lâmpadas, cenas, rotinas e opções gerais."""

import datetime as dt
import ipaddress
import os
import subprocess
import sys
import time

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTime, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox,
                               QCompleter, QDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLayout,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QProgressBar,
                               QPushButton, QRadioButton, QSlider, QSpinBox, QTabWidget, QTimeEdit,
                               QVBoxLayout, QWidget)

from .. import APP_NAME, autostart, discovery, geo, scheduler
from ..crypto import mask
from ..i18n import LANGUAGES, current, tr
from ..lamp import FakeBulb, TuyaBulb
from ..paths import data_dir
from ..storage import PROTOCOL_VERSIONS, Lamp, Location, Routine, Scene
from . import icons, theme


# ------------------------------------------------------------ utilidades ---
class _Signals(QObject):
    done = Signal(object, object)  # resultado, erro


class _Job(QRunnable):
    def __init__(self, fn, signals):
        super().__init__()
        self.fn, self.signals = fn, signals

    def run(self):
        try:
            self.signals.done.emit(self.fn(), None)
        except Exception as exc:  # noqa: BLE001 - erro vai para a interface
            self.signals.done.emit(None, exc)


_alive = set()


def run_async(fn, callback):
    """Roda `fn` numa thread e chama `callback(resultado, erro)` na thread da interface."""
    sig = _Signals()
    _alive.add(sig)

    def finish(res, err):
        _alive.discard(sig)
        callback(res, err)

    sig.done.connect(finish, Qt.ConnectionType.QueuedConnection)
    QThreadPool.globalInstance().start(_Job(fn, sig))


def muted(text: str = "", wrap: bool = True) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("muted", True)
    lbl.setWordWrap(wrap)
    return lbl


def button(text: str, slot=None, primary=False, danger=False) -> QPushButton:
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        b.setProperty("primary", True)
    if danger:
        b.setProperty("danger", True)
    if slot:
        b.clicked.connect(slot)
    return b


def swatch(color: QColor, size: int = 14) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(color)
    return QIcon(pm)


def days_text(days) -> str:
    days = sorted(set(days))
    names = tr("days.short").split(",")
    if days == list(range(7)):
        return tr("days.every")
    if days == [0, 1, 2, 3, 4]:
        return tr("days.weekdays")
    if days == [5, 6]:
        return tr("days.weekend")
    return ", ".join(names[d] for d in days)


def mask_ip(ip: str) -> str:
    parts = ip.split(".")
    return "•••." * (len(parts) - 1) + parts[-1] if len(parts) == 4 else mask(ip)


def confirm(parent, text: str) -> bool:
    return QMessageBox.question(parent, APP_NAME, text) == QMessageBox.StandardButton.Yes


class _Dialog(QDialog):
    def __init__(self, parent, title: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setStyleSheet(theme.DIALOG_QSS)
        self.setMinimumWidth(440)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(22, 20, 22, 18)
        self.body.setSpacing(12)
        head = QLabel(title)
        head.setProperty("title", True)
        self.body.addWidget(head)

    def add_buttons(self, ok_text: str = None, extra=None):
        row = QHBoxLayout()
        if extra:
            for w in extra:
                row.addWidget(w)
        row.addStretch(1)
        row.addWidget(button(tr("btn.cancel"), self.reject))
        self.ok = button(ok_text or tr("btn.save"), self.accept_if_valid, primary=True)
        self.ok.setDefault(True)
        row.addWidget(self.ok)
        self.body.addLayout(row)

    def accept_if_valid(self):
        self.accept()


# ------------------------------------------------------------- lâmpadas ---
class LampDialog(_Dialog):
    def __init__(self, parent, lamp: Lamp = None, prefill: discovery.Found = None, demo=False, count=0,
                 live=None):
        super().__init__(parent, tr("lamp.edit") if lamp else tr("lamp.new"))
        self.demo = demo
        form = QFormLayout()
        form.setSpacing(10)
        self.name = QLineEdit(lamp.name if lamp else (prefill.name if prefill and prefill.name else
                                                      tr("lamp.default_name", n=count + 1)))
        self.ip = QLineEdit(lamp.ip if lamp else (prefill.ip if prefill else ""))
        self.ip.setPlaceholderText("192.168.0.10")
        self.dev = QLineEdit(lamp.device_id if lamp else (prefill.device_id if prefill else ""))
        self.key = QLineEdit(lamp.local_key if lamp else (prefill.local_key if prefill else ""))
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        eye = self.key.addAction(icons.icon("eye", theme.MUTED), QLineEdit.ActionPosition.TrailingPosition)
        eye.triggered.connect(lambda: self.key.setEchoMode(
            QLineEdit.EchoMode.Normal if self.key.echoMode() == QLineEdit.EchoMode.Password
            else QLineEdit.EchoMode.Password))
        self.version = QComboBox()
        for v in PROTOCOL_VERSIONS:
            self.version.addItem(tr("lamp.auto") if v == "auto" else v, v)
        ver = lamp.version if lamp else (prefill.version if prefill else "auto")
        self.version.setCurrentIndex(max(0, self.version.findData(ver)))
        for label, w in ((tr("lamp.name"), self.name), (tr("lamp.ip"), self.ip),
                         (tr("lamp.device_id"), self.dev), (tr("lamp.local_key"), self.key),
                         (tr("lamp.version"), self.version)):
            form.addRow(label, w)
        self.body.addLayout(form)
        get_key = button(tr("lamp.get_key"), self.fetch_key)
        get_key.setToolTip(tr("smartlife.title"))
        self.body.addWidget(get_key, 0, Qt.AlignmentFlag.AlignLeft)
        self.result_label = muted()
        self.body.addWidget(self.result_label)
        self.body.addWidget(muted(tr("lamp.help")))
        self.test_btn = button(tr("btn.test"), self.test)
        self.add_buttons(extra=[self.test_btn])
        self.lamp = lamp
        self.live = live  # (LampState, versão) da conexão ao vivo, se a lâmpada já existe

    def fetch_key(self):
        d = SmartLifeDialog(self, scan_lan=not self.ip.text().strip(), want_id=self.dev.text().strip())
        d.exec()
        if not d.found:
            return
        dev_id = self.dev.text().strip()
        match = next((f for f in d.found if f.device_id == dev_id), None)
        if match is None and not dev_id:
            chosen = d.value()  # sem ID digitado: usa a lâmpada marcada na lista
            match = chosen[0] if chosen else None
        if match is None:
            self.result_label.setText(tr("smartlife.not_found", id=mask(dev_id)))
            return
        self.dev.setText(match.device_id)
        self.key.setText(match.local_key)
        if match.ip and not self.ip.text().strip():
            self.ip.setText(match.ip)
        if match.version != "auto":
            self.version.setCurrentIndex(max(0, self.version.findData(match.version)))
        self.result_label.setText(tr("smartlife.key_filled"))

    def _build(self) -> Lamp:
        return Lamp(name=self.name.text().strip() or "Lamp", device_id=self.dev.text().strip(),
                    ip=self.ip.text().strip(), local_key=self.key.text().strip(),
                    version=self.version.currentData())

    def _validate(self) -> str:
        l = self._build()
        if not (l.ip and l.device_id and l.local_key):
            return tr("lamp.missing")
        try:
            ipaddress.ip_address(l.ip)
        except ValueError:
            return tr("lamp.bad_ip")
        return ""

    def test(self):
        err = self._validate()
        if err:
            self.result_label.setText(err)
            return
        new = self._build()
        if self.lamp and self.live and self.live[0].online and \
                (new.ip, new.device_id, new.local_key) == (self.lamp.ip, self.lamp.device_id, self.lamp.local_key):
            # muitas lâmpadas só aceitam uma conexão local: usa a que o app já mantém aberta
            self.result_label.setText(tr("test.ok", v=self.live[1] or self.lamp.version))
            return
        self.result_label.setText(tr("test.running"))
        self.test_btn.setEnabled(False)
        bulb = (FakeBulb if self.demo else TuyaBulb)(new)

        def done(_res, error):
            self.test_btn.setEnabled(True)
            if error:
                self.result_label.setText(tr("test.fail", err=error))
            else:
                self.result_label.setText(tr("test.ok", v=bulb.detected_version))
                idx = self.version.findData(bulb.detected_version)
                if idx >= 0:
                    self.version.setCurrentIndex(idx)
        run_async(bulb.read, done)

    def accept_if_valid(self):
        err = self._validate()
        if err:
            self.result_label.setText(err)
            return
        if len(self.key.text().strip()) != 16 and not self.result_label.text().startswith(tr("lamp.bad_key")):
            self.result_label.setText(tr("lamp.bad_key"))  # aviso; segundo clique salva
            return
        self.accept()

    def value(self) -> Lamp:
        new = self._build()
        if self.lamp:
            new.id = self.lamp.id
        return new


class ScanDialog(_Dialog):
    def __init__(self, parent, known_ids, demo=False):
        super().__init__(parent, tr("scan.title"))
        self.info = muted(tr("scan.running"))
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.list = QListWidget()
        self.list.setMinimumHeight(180)
        self.body.addWidget(self.info)
        self.body.addWidget(self.bar)
        self.body.addWidget(self.list)
        self.add_buttons(tr("scan.use"))
        self.ok.setEnabled(False)
        self.list.currentRowChanged.connect(lambda r: self.ok.setEnabled(r >= 0))
        self.list.itemDoubleClicked.connect(lambda *_: self.accept())
        self.found = []
        self.known = set(known_ids)
        if demo:
            run_async(lambda: [discovery.Found("demo0000000000000001", "192.0.2.50", "3.3")], self._done)
        else:
            run_async(discovery.scan_lan, self._done)

    def _done(self, res, err):
        self.bar.hide()
        if err:
            self.info.setText(tr("cloud.error", err=err))
            return
        self.found = res or []
        self.info.setText(tr("scan.found", n=len(self.found)) if self.found else tr("scan.none"))
        for f in self.found:
            extra = f"  ({tr('scan.known')})" if f.device_id in self.known else ""
            self.list.addItem(f"{f.ip}  ·  {f.device_id}  ·  v{f.version}{extra}")

    def value(self):
        r = self.list.currentRow()
        return self.found[r] if 0 <= r < len(self.found) else None


class _ImportDialog(_Dialog):
    """Base dos diálogos que trazem várias lâmpadas (com Local Key) de uma vez."""

    def __init__(self, parent, title: str):
        super().__init__(parent, title)
        self.setMinimumWidth(520)
        self.found = []

    def _add_results(self, extra_buttons):
        self.info = muted()
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.bar.hide()
        self.list = QListWidget()
        self.list.hide()
        self.body.addWidget(self.info)
        self.body.addWidget(self.bar)
        self.body.addWidget(self.list)
        self.add_buttons(tr("cloud.import"), extra=extra_buttons)
        self.ok.setEnabled(False)

    def _show(self, found):
        self.bar.hide()
        self.found = found or []
        self.info.setText(tr("cloud.result", n=len(self.found)))
        self.list.clear()
        self.list.show()
        for f in self.found:
            it = QListWidgetItem(f"{f.name}  ·  {f.ip or tr('cloud.no_ip')}")
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if f.ip else Qt.CheckState.Unchecked)
            if not f.ip:
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.list.addItem(it)
        self.ok.setEnabled(any(f.ip for f in self.found))

    def _fail(self, err):
        self.bar.hide()
        self.info.setText(tr("cloud.error", err=err))

    def value(self):
        return [f for i, f in enumerate(self.found)
                if self.list.item(i).checkState() == Qt.CheckState.Checked and f.ip]


class CloudDialog(_ImportDialog):
    def __init__(self, parent, hint_device_id=""):
        super().__init__(parent, tr("cloud.title"))
        self.body.addWidget(muted(tr("cloud.intro")))
        form = QFormLayout()
        self.region = QComboBox()
        self.region.addItems(discovery.TUYA_REGIONS)
        self.key = QLineEdit()
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.device = QLineEdit(hint_device_id)
        for label, w in ((tr("cloud.region"), self.region), (tr("cloud.key"), self.key),
                         (tr("cloud.secret"), self.secret), (tr("cloud.device"), self.device)):
            form.addRow(label, w)
        self.body.addLayout(form)
        self.run_btn = button(tr("cloud.run"), self.run)
        self._add_results([self.run_btn])

    def run(self):
        args = (self.region.currentText(), self.key.text().strip(), self.secret.text().strip(),
                self.device.text().strip())
        if not all(args):
            self.info.setText(tr("lamp.missing").split(".")[0])
            return
        self.run_btn.setEnabled(False)
        self.bar.show()
        self.info.setText(tr("cloud.running"))

        def job():
            cloud = discovery.import_cloud(*args)
            return discovery.merge(cloud, discovery.scan_lan())

        def done(res, err):
            self.run_btn.setEnabled(True)
            self._fail(err) if err else self._show(res)
        run_async(job, done)


class QrView(QWidget):
    """Desenha um QR Code (quadrado branco com módulos pretos)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.matrix = []
        self.setFixedSize(232, 232)

    def set_data(self, data: str):
        import qrcode
        qr = qrcode.QRCode(border=0, error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(data)
        qr.make(fit=True)
        self.matrix = qr.get_matrix()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("white"))
        p.drawRoundedRect(self.rect(), 14, 14)
        if not self.matrix:
            return
        n = len(self.matrix)
        cell = (self.width() - 32) // n
        off = (self.width() - cell * n) // 2
        p.setBrush(QColor("black"))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        for y, row in enumerate(self.matrix):
            for x, on in enumerate(row):
                if on:
                    p.drawRect(off + x * cell, off + y * cell, cell, cell)


class SmartLifeDialog(_ImportDialog):
    """Login por QR Code no app Smart Life: traz o Local Key sem conta de desenvolvedor."""

    TIMEOUT_S = 180

    def __init__(self, parent, scan_lan=True, want_id=""):
        super().__init__(parent, tr("smartlife.title"))
        self.scan_lan = scan_lan
        self.want_id = want_id
        self.body.addWidget(muted(tr("smartlife.intro")))
        self.body.addWidget(muted(tr("smartlife.where")))
        form = QFormLayout()
        self.code = QLineEdit()
        self.code.setPlaceholderText("Ab1Cd2")
        form.addRow(tr("smartlife.code"), self.code)
        self.body.addLayout(form)
        self.qr = QrView()
        self.qr.hide()
        self.qr_hint = muted(tr("smartlife.scan"))
        self.qr_hint.hide()
        self.body.addWidget(self.qr, 0, Qt.AlignmentFlag.AlignHCenter)
        self.body.addWidget(self.qr_hint)
        self.run_btn = button(tr("smartlife.generate"), self.run)
        self._add_results([self.run_btn])
        # a janela acompanha o conteúdo (o QR aparece e some durante o fluxo)
        self.body.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        self.login = None
        self._polling = False
        self._started = 0.0
        self.poll_timer = QTimer(self, interval=2000)
        self.poll_timer.timeout.connect(self._poll)

    def run(self):
        code = self.code.text().strip()
        if not code:
            self.info.setText(tr("smartlife.no_code"))
            return
        try:
            self.login = discovery.SmartLifeLogin(code)
        except ImportError:
            self.info.setText(tr("smartlife.missing_dep"))
            return
        self.run_btn.setEnabled(False)
        self.bar.show()
        self.info.setText("")

        def done(payload, err):
            self.bar.hide()
            if err:
                self.run_btn.setEnabled(True)
                self._fail(err)
                return
            self.qr.set_data(payload)
            self.qr.show()
            self.qr_hint.show()
            self.info.setText(tr("smartlife.waiting"))
            self._started = time.monotonic()
            self.poll_timer.start()
            self.adjustSize()
        run_async(self.login.start, done)

    def _poll(self):
        if self._polling:
            return
        if time.monotonic() - self._started > self.TIMEOUT_S:
            self.poll_timer.stop()
            self.qr.hide()
            self.qr_hint.hide()
            self.run_btn.setEnabled(True)
            self.info.setText(tr("smartlife.expired"))
            return
        self._polling = True

        def done(info, err):
            self._polling = False
            if err or not info:
                return  # ainda não escaneado (ou falha momentânea): tenta de novo
            self.poll_timer.stop()
            self.qr.hide()
            self.qr_hint.hide()
            self.bar.show()
            self.info.setText(tr("smartlife.fetching_lan" if self.scan_lan else "smartlife.fetching"))
            self.adjustSize()

            def job():
                found = self.login.fetch(info)
                return discovery.merge(found, discovery.scan_lan()) if self.scan_lan else found

            def fetched(res, err2):
                self.run_btn.setEnabled(True)
                self._fail(err2) if err2 else self._show(res)
            run_async(job, fetched)
        run_async(self.login.poll, done)

    def _show(self, found):
        super()._show(found)
        if self.want_id and any(f.device_id == self.want_id for f in self.found):
            self.accept()  # aberto pelo cadastro de uma lâmpada: achou, volta direto

    def done(self, r):
        self.poll_timer.stop()
        super().done(r)


class LampsTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 12, 0, 0)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda *_: self.edit())
        v.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(button(tr("btn.add"), self.add, primary=True))
        row.addWidget(button(tr("btn.edit"), self.edit))
        row.addWidget(button(tr("btn.remove"), self.remove, danger=True))
        row.addStretch(1)
        row.addWidget(button(tr("btn.scan"), self.scan))
        row.addWidget(button(tr("btn.smartlife"), self.smartlife))
        row.addWidget(button(tr("btn.cloud"), self.cloud))
        v.addLayout(row)
        v.addWidget(muted(tr("lamp.help")))
        self.refresh()

    @property
    def cfg(self):
        return self.win.store.config

    def refresh(self):
        self.list.clear()
        for l in self.cfg.lamps:
            st = self.win.service.state(l.id)
            dot = theme.OK if st.online else (theme.ERROR if st.error else theme.DIM)
            it = QListWidgetItem(swatch(dot, 10), f"{l.name}\n{mask_ip(l.ip)}  ·  ID {mask(l.device_id)}  ·  "
                                                  f"{tr('lamp.auto') if l.version == 'auto' else 'v' + l.version}")
            it.setData(Qt.ItemDataRole.UserRole, l.id)
            self.list.addItem(it)

    def _selected(self):
        it = self.list.currentItem()
        return self.cfg.lamp(it.data(Qt.ItemDataRole.UserRole)) if it else None

    def add(self, prefill=None):
        d = LampDialog(self, prefill=prefill if isinstance(prefill, discovery.Found) else None,
                       demo=self.win.service.demo, count=len(self.cfg.lamps))
        if d.exec():
            self.cfg.lamps.append(d.value())
            self.win.changed()

    def edit(self):
        lamp = self._selected()
        if not lamp:
            return
        svc = self.win.service
        d = LampDialog(self, lamp=lamp, demo=svc.demo, live=(svc.state(lamp.id), svc.version(lamp.id)))
        if d.exec():
            idx = self.cfg.lamps.index(lamp)
            self.cfg.lamps[idx] = d.value()
            self.win.changed()

    def remove(self):
        lamp = self._selected()
        if lamp and confirm(self, tr("confirm.remove", name=lamp.name)):
            self.cfg.lamps.remove(lamp)
            for r in self.cfg.routines:
                r.targets = [t for t in r.targets if t != lamp.id] or ["*"]
            self.win.changed()

    def scan(self):
        d = ScanDialog(self, [l.device_id for l in self.cfg.lamps], demo=self.win.service.demo)
        if d.exec() and d.value():
            found = d.value()
            existing = next((l for l in self.cfg.lamps if l.device_id == found.device_id), None)
            if existing:  # só atualiza o IP (pode ter mudado no roteador)
                existing.ip = found.ip
                if found.version != "auto":
                    existing.version = found.version
                self.win.changed()
            else:
                self.add(found)

    def smartlife(self):
        d = SmartLifeDialog(self)
        if d.exec():
            self._import(d.value())

    def cloud(self):
        hint = self.cfg.lamps[0].device_id if self.cfg.lamps else ""
        d = CloudDialog(self, hint)
        if d.exec():
            self._import(d.value())

    def _import(self, found):
        if found:
            for f in found:
                existing = next((l for l in self.cfg.lamps if l.device_id == f.device_id), None)
                if existing:
                    existing.ip, existing.local_key = f.ip, f.local_key
                else:
                    self.cfg.lamps.append(Lamp(name=f.name or f.device_id[-4:], device_id=f.device_id,
                                               ip=f.ip, local_key=f.local_key, version=f.version))
            self.win.changed()


# --------------------------------------------------------------- cenas ---
class SceneDialog(_Dialog):
    def __init__(self, parent, scene: Scene = None, count=0):
        super().__init__(parent, tr("scene.edit") if scene else tr("scene.new"))
        self.scene = scene or Scene(name=f"{tr('scene.new')} {count + 1}")
        self.color = QColor(*self.scene.color)
        form = QFormLayout()
        form.setSpacing(10)
        self.name = QLineEdit(self.scene.name)
        mode_row = QHBoxLayout()
        self.white = QRadioButton(tr("scene.mode_white"))
        self.colour = QRadioButton(tr("scene.mode_colour"))
        (self.colour if self.scene.mode == "colour" else self.white).setChecked(True)
        mode_row.addWidget(self.white)
        mode_row.addWidget(self.colour)
        mode_row.addStretch(1)
        self.bright = QSlider(Qt.Orientation.Horizontal)
        self.bright.setRange(1, 100)
        self.bright.setValue(self.scene.brightness)
        self.temp = QSlider(Qt.Orientation.Horizontal)
        self.temp.setRange(0, 100)
        self.temp.setValue(self.scene.temperature)
        self.color_btn = button(tr("scene.pick"), self.pick)
        form.addRow(tr("scene.name"), self.name)
        form.addRow(tr("scene.mode"), mode_row)
        form.addRow(tr("brightness"), self.bright)
        form.addRow(tr("scene.temperature"), self.temp)
        form.addRow(tr("color"), self.color_btn)
        self.body.addLayout(form)
        self.white.toggled.connect(self._sync)
        self._sync()
        self.add_buttons()

    def _sync(self):
        white = self.white.isChecked()
        self.temp.setEnabled(white)
        self.color_btn.setEnabled(not white)
        self.color_btn.setIcon(swatch(self.color, 16))

    def pick(self):
        c = QColorDialog.getColor(self.color, self, tr("pick_color"))
        if c.isValid():
            self.color = c
            self._sync()

    def value(self) -> Scene:
        s = self.scene
        s.name = self.name.text().strip() or s.name
        s.mode = "white" if self.white.isChecked() else "colour"
        s.brightness, s.temperature = self.bright.value(), self.temp.value()
        s.color = [self.color.red(), self.color.green(), self.color.blue()]
        return s


class ScenesTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 12, 0, 0)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda *_: self.edit())
        v.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(button(tr("btn.add"), self.add, primary=True))
        row.addWidget(button(tr("btn.edit"), self.edit))
        row.addWidget(button(tr("btn.remove"), self.remove, danger=True))
        row.addStretch(1)
        v.addLayout(row)
        self.refresh()

    def refresh(self):
        from ..lamp import white_rgb
        self.list.clear()
        for s in self.win.store.config.scenes:
            rgb = s.color if s.mode == "colour" else white_rgb(s.temperature)
            detail = tr("scene.mode_colour") if s.mode == "colour" else tr("scene.mode_white")
            it = QListWidgetItem(swatch(QColor(*rgb), 14), f"{s.name}\n{detail} · {s.brightness}%")
            it.setData(Qt.ItemDataRole.UserRole, s.id)
            self.list.addItem(it)

    def _selected(self):
        it = self.list.currentItem()
        return self.win.store.config.scene(it.data(Qt.ItemDataRole.UserRole)) if it else None

    def add(self):
        d = SceneDialog(self, count=len(self.win.store.config.scenes))
        if d.exec():
            self.win.store.config.scenes.append(d.value())
            self.win.changed()

    def edit(self):
        s = self._selected()
        if s and SceneDialog(self, s).exec():
            self.win.changed()

    def remove(self):
        s = self._selected()
        if s and confirm(self, tr("confirm.remove", name=s.name)):
            self.win.store.config.scenes.remove(s)
            self.win.changed()


# ------------------------------------------------------------- rotinas ---
class RoutineDialog(_Dialog):
    def __init__(self, parent, cfg, routine: Routine = None):
        super().__init__(parent, tr("routine.edit") if routine else tr("routine.new"))
        self.cfg = cfg
        self.routine = routine or Routine(name=tr("routine.default_name", n=len(cfg.routines) + 1))
        r = self.routine
        form = QFormLayout()
        form.setSpacing(10)
        self.name = QLineEdit(r.name)
        self.trigger = QComboBox()
        for key, label in (("time", tr("routine.at_time")), ("sunrise", tr("routine.sunrise")),
                           ("sunset", tr("routine.sunset"))):
            self.trigger.addItem(label, key)
        self.trigger.setCurrentIndex(max(0, self.trigger.findData(r.trigger)))
        self.time = QTimeEdit(QTime.fromString(r.time, "HH:mm"))
        self.time.setDisplayFormat("HH:mm")
        self.offset = QSpinBox()
        self.offset.setRange(-180, 180)
        self.offset.setSingleStep(5)
        self.offset.setValue(r.offset_min)
        self.offset.setSuffix(tr("routine.offset_suffix"))

        days_row = QHBoxLayout()
        days_row.setSpacing(4)
        self.day_buttons = []
        for i, name in enumerate(tr("days.short").split(",")):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setChecked(i in r.days)
            b.setProperty("day", True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.day_buttons.append(b)
            days_row.addWidget(b)

        self.action = QComboBox()
        for key, label in (("on", tr("routine.turn_on")), ("off", tr("routine.turn_off")),
                           ("scene", tr("routine.scene"))):
            self.action.addItem(label, key)
        self.action.setCurrentIndex(max(0, self.action.findData(r.action)))
        self.scene = QComboBox()
        for s in cfg.scenes:
            self.scene.addItem(s.name, s.id)
        self.scene.setCurrentIndex(max(0, self.scene.findData(r.scene_id)))

        self.targets = QListWidget()
        self.targets.setMaximumHeight(130)
        self.targets.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        for key, label in [("*", tr("all_lamps"))] + [(l.id, l.name) for l in cfg.lamps]:
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, key)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if key in r.targets else Qt.CheckState.Unchecked)
            self.targets.addItem(it)

        form.addRow(tr("routine.name"), self.name)
        form.addRow(tr("routine.when"), self.trigger)
        form.addRow(tr("routine.time"), self.time)
        form.addRow(tr("routine.offset"), self.offset)
        form.addRow(tr("routine.days"), days_row)
        form.addRow(tr("routine.action"), self.action)
        form.addRow(tr("scenes"), self.scene)
        form.addRow(tr("routine.targets"), self.targets)
        self.form = form
        self.body.addLayout(form)
        self.warn = muted()
        self.body.addWidget(self.warn)
        self.trigger.currentIndexChanged.connect(self._sync)
        self.action.currentIndexChanged.connect(self._sync)
        self._sync()
        self.add_buttons()

    def _sync(self):
        is_time = self.trigger.currentData() == "time"
        self.form.setRowVisible(self.time, is_time)
        self.form.setRowVisible(self.offset, not is_time)
        self.form.setRowVisible(self.scene, self.action.currentData() == "scene")
        need_loc = not is_time and not self.cfg.settings.location.is_set
        self.warn.setText(tr("routine.need_location") if need_loc else "")

    def accept_if_valid(self):
        if not any(b.isChecked() for b in self.day_buttons):
            self.warn.setText(tr("routine.no_days"))
        elif not self._targets():
            self.warn.setText(tr("routine.no_targets"))
        elif self.action.currentData() == "scene" and self.scene.currentData() is None:
            self.warn.setText(tr("routine.no_scene"))
        else:
            self.accept()

    def _targets(self):
        out = [self.targets.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.targets.count())
               if self.targets.item(i).checkState() == Qt.CheckState.Checked]
        return ["*"] if "*" in out else out

    def value(self) -> Routine:
        r = self.routine
        r.name = self.name.text().strip() or r.name
        r.trigger = self.trigger.currentData()
        r.time = self.time.time().toString("HH:mm")
        r.offset_min = self.offset.value()
        r.days = [i for i, b in enumerate(self.day_buttons) if b.isChecked()]
        r.action = self.action.currentData()
        r.scene_id = self.scene.currentData() or ""
        r.targets = self._targets()
        return r


class RoutinesTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 12, 0, 0)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda *_: self.edit())
        self.list.itemChanged.connect(self._toggled)
        v.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(button(tr("btn.add"), self.add, primary=True))
        row.addWidget(button(tr("btn.edit"), self.edit))
        row.addWidget(button(tr("btn.remove"), self.remove, danger=True))
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(muted(tr("routine.note")))
        self.refresh()

    def describe(self, r: Routine) -> str:
        cfg = self.win.store.config
        if r.trigger == "time":
            when = r.time
        else:
            when = tr("routine.sunrise" if r.trigger == "sunrise" else "routine.sunset")
            if r.offset_min:
                when += f" {r.offset_min:+d} min"
        if r.action == "scene":
            sc = cfg.scene(r.scene_id)
            action = f"{tr('routine.scene')}: {sc.name if sc else '?'}"
        else:
            action = tr("routine.turn_on" if r.action == "on" else "routine.turn_off")
        targets = tr("all_lamps") if "*" in r.targets else ", ".join(
            l.name for l in cfg.resolve_targets(r.targets))
        nxt = scheduler.next_occurrence(r, dt.datetime.now().astimezone(), cfg.settings.location)
        nxt_txt = tr("routine.next", t=nxt.strftime("%a %H:%M")) if nxt else tr("routine.never")
        return f"{r.name}\n{when} · {days_text(r.days)} · {action} · {targets} — {nxt_txt}"

    def refresh(self):
        self.list.blockSignals(True)
        self.list.clear()
        for r in self.win.store.config.routines:
            it = QListWidgetItem(self.describe(r))
            it.setData(Qt.ItemDataRole.UserRole, r.id)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if r.enabled else Qt.CheckState.Unchecked)
            self.list.addItem(it)
        self.list.blockSignals(False)

    def _routine(self, it):
        rid = it.data(Qt.ItemDataRole.UserRole) if it else None
        return next((r for r in self.win.store.config.routines if r.id == rid), None)

    def _toggled(self, it):
        r = self._routine(it)
        if r:
            r.enabled = it.checkState() == Qt.CheckState.Checked
            self.win.changed()

    def add(self):
        d = RoutineDialog(self, self.win.store.config)
        if d.exec():
            self.win.store.config.routines.append(d.value())
            self.win.changed()

    def edit(self):
        r = self._routine(self.list.currentItem())
        if r and RoutineDialog(self, self.win.store.config, r).exec():
            self.win.changed()

    def remove(self):
        r = self._routine(self.list.currentItem())
        if r and confirm(self, tr("confirm.remove", name=r.name)):
            self.win.store.config.routines.remove(r)
            self.win.changed()


# --------------------------------------------------------------- geral ---
class GeneralTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        s = win.store.config.settings
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 16, 0, 0)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(1, 1)

        self.lang = QComboBox()
        for code, label in LANGUAGES.items():
            self.lang.addItem(label, code)
        self.lang.setCurrentIndex(max(0, self.lang.findData(current())))
        self.lang.currentIndexChanged.connect(self._lang)
        grid.addWidget(QLabel(tr("general.language")), 0, 0)
        grid.addWidget(self.lang, 0, 1)

        self.auto = QCheckBox(tr("general.autostart"))
        self.auto.setChecked(autostart.is_enabled() if not win.service.demo else s.autostart)
        self.auto.toggled.connect(self._autostart)
        grid.addWidget(self.auto, 1, 1)

        grid.addWidget(QLabel(tr("general.location")), 2, 0, 1, 2)
        self.loc_label = muted()
        grid.addWidget(self.loc_label, 3, 0, 1, 2)
        self.city = QLineEdit()
        self.city.setPlaceholderText(tr("general.city"))
        comp = QCompleter([c[0] for c in geo.CITIES], self)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        comp.popup().setStyleSheet(theme.DIALOG_QSS)
        comp.activated.connect(self._city)
        self.city.setCompleter(comp)
        self.city.returnPressed.connect(lambda: self._city(self.city.text()))
        grid.addWidget(self.city, 4, 0, 1, 2)
        self.coords = QLineEdit()
        self.coords.setPlaceholderText(tr("general.coords"))
        self.coords.editingFinished.connect(self._coords)
        grid.addWidget(self.coords, 5, 0, 1, 2)
        self.gps = button(tr("general.gps"), self._gps)
        if not geo.gps_supported():
            self.gps.setEnabled(False)
            self.gps.setToolTip(tr("general.gps_unsupported"))
        self.gps_info = muted()
        grid.addWidget(self.gps, 6, 0)
        grid.addWidget(self.gps_info, 6, 1)

        grid.addWidget(QLabel(tr("general.data")), 7, 0, 1, 2)
        path = muted(str(data_dir()))
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        grid.addWidget(path, 8, 0, 1, 2)
        grid.addWidget(muted(tr("general.data_note")), 9, 0, 1, 2)
        grid.addWidget(button(tr("btn.open_folder"), self._open_folder), 10, 0)
        grid.setRowStretch(11, 1)
        self.refresh()

    def refresh(self):
        loc = self.win.store.config.settings.location
        if not loc.is_set:
            self.loc_label.setText(tr("general.location_none"))
            return
        text = f"{loc.label or ''} ({loc.latitude:.3f}, {loc.longitude:.3f})".strip()
        now = dt.datetime.now().astimezone()
        sun = scheduler.sun_times(loc, now.date(), now.tzinfo)
        if sun:
            text += "\n" + tr("general.sun_today", rise=sun[0].strftime("%H:%M"), set=sun[1].strftime("%H:%M"))
        self.loc_label.setText(text)

    def _set_location(self, label, lat, lon):
        self.win.store.config.settings.location = Location(label, lat, lon)
        self.win.changed()

    def _city(self, text):
        matches = geo.search(text)
        if matches:
            name, lat, lon = matches[0]
            self.city.setText(name)
            self._set_location(name, lat, lon)

    def _coords(self):
        c = geo.parse_coords(self.coords.text())
        if c:
            self._set_location("", *c)

    def _gps(self):
        self.gps.setEnabled(False)
        self.gps_info.setText(tr("general.gps_running"))

        def done(res, err):
            self.gps.setEnabled(True)
            if err:
                key = str(err) if str(err) in ("denied", "unknown", "unsupported") else "unknown"
                self.gps_info.setText(tr(f"general.gps_{key}"))
            else:
                self.gps_info.setText("")
                self._set_location("GPS", *res)
        run_async(geo.locate_windows, done)

    def _lang(self):
        self.win.store.config.settings.language = self.lang.currentData()
        self.win.store.save()
        self.win.languageChanged.emit()

    def _autostart(self, on):
        self.win.store.config.settings.autostart = on
        if not self.win.service.demo:
            autostart.set_enabled(on)
        self.win.changed()

    def _open_folder(self):
        path = str(data_dir())
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))


# -------------------------------------------------------------- janela ---
class SettingsWindow(QWidget):
    configChanged = Signal()
    languageChanged = Signal()

    TABS = ["lamps", "scenes", "routines", "general"]

    def __init__(self, store, service):
        super().__init__()
        self.store, self.service = store, service
        self.setWindowTitle(f"{APP_NAME} — {tr('settings')}")
        self.setStyleSheet(theme.DIALOG_QSS)
        self.resize(680, 580)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        title = QLabel(tr("settings"))
        title.setProperty("title", True)
        v.addWidget(title)
        self.tabs = QTabWidget()
        self.lamps = LampsTab(self)
        self.scenes = ScenesTab(self)
        self.routines = RoutinesTab(self)
        self.general = GeneralTab(self)
        self.tabs.addTab(self.lamps, tr("lamps"))
        self.tabs.addTab(self.scenes, tr("scenes"))
        self.tabs.addTab(self.routines, tr("routines"))
        self.tabs.addTab(self.general, tr("general"))
        v.addWidget(self.tabs)
        service.stateChanged.connect(self._on_state)

    def _on_state(self, *_):
        if self.isVisible():
            self.lamps.refresh()

    def show_tab(self, name: str):
        if name in self.TABS:
            self.tabs.setCurrentIndex(self.TABS.index(name))
        self.show()
        self.raise_()
        self.activateWindow()

    def changed(self):
        self.store.save()
        for tab in (self.lamps, self.scenes, self.routines, self.general):
            tab.refresh()
        self.configChanged.emit()
