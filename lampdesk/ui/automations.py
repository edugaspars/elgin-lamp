"""Aba Automações das configurações: regras "Quando/Se/Então", recursos e diagnóstico."""

import copy
import datetime as dt

from PySide6.QtCore import QDate, Qt, QTime, QTimer
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDateEdit, QFormLayout, QGridLayout,
                               QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QScrollArea, QSpinBox, QTimeEdit, QVBoxLayout, QWidget)

from .. import rules as R
from ..i18n import tr
from ..storage import Rule
from .settings import _Dialog, button, confirm, days_text, muted, swatch
from .widgets import SegmentedTabs


def section(text: str, gap: int = 0) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setProperty("section", True)
    lbl.setContentsMargins(0, gap, 0, 0)
    return lbl


def row_widget(*widgets, stretch=True) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(8)
    for x in widgets:
        h.addWidget(x)
    if stretch:
        h.addStretch(1)
    return w


class TargetCombo(QComboBox):
    """Todas / grupos / lâmpadas (uma escolha)."""

    def __init__(self, cfg, targets):
        super().__init__()
        self.addItem(tr("all_lamps"), "*")
        for g in cfg.groups:
            self.addItem(f"{tr('group')}: {g.name}", g.id)
        for l in cfg.lamps:
            self.addItem(l.name, l.id)
        self.set_value(targets)

    def set_value(self, targets):
        key = targets[0] if len(targets) == 1 else "*"
        self.setCurrentIndex(max(0, self.findData(key)))

    def value(self):
        return [self.currentData() or "*"]


class ColorButton(QPushButton):
    """Botão que mostra e escolhe uma cor; com `allow_off`, [0, 0, 0] significa "apagada"."""

    def __init__(self, rgb, allow_off=False):
        super().__init__()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.allow_off = allow_off
        self.rgb = list(rgb)
        self.clicked.connect(self.pick)
        self._sync()

    def _sync(self):
        off = not any(self.rgb)
        self.setIcon(swatch(QColor(60, 60, 60) if off else QColor(*self.rgb), 16))
        self.setText(tr("rule.color_off") if off else QColor(*self.rgb).name().upper())

    def pick(self):
        if self.allow_off:
            from .tray import style_menu
            from PySide6.QtWidgets import QMenu
            m = QMenu(self)
            style_menu(m)
            m.addAction(tr("pick_color")).triggered.connect(self._dialog)
            m.addAction(tr("rule.color_off")).triggered.connect(lambda: self.set_rgb([0, 0, 0]))
            m.exec(self.mapToGlobal(self.rect().bottomLeft()))
        else:
            self._dialog()

    def _dialog(self):
        start = QColor(*self.rgb) if any(self.rgb) else QColor(255, 255, 255)
        c = QColorDialog.getColor(start, self, tr("pick_color"))
        if c.isValid():
            self.set_rgb([c.red(), c.green(), c.blue()])

    def set_rgb(self, rgb):
        self.rgb = list(rgb)
        self._sync()


def describe_rule(cfg, r: Rule) -> str:
    when = tr(f"trigger.{r.trigger}")
    if r.trigger == "time":
        when = f"{when} {r.time}"
    elif r.trigger in ("sunrise", "sunset") and r.offset_min:
        when += f" {r.offset_min:+d} min"
    elif r.trigger == "away":
        when += " · " + tr("rule.after_min", n=r.delay_min)
    elif r.trigger == "hotkey":
        when += f" {r.hotkey}"
    elif r.trigger == "notification" and r.apps:
        when += f" ({', '.join(r.apps)})"
    parts = [when]
    if r.days != list(range(7)):
        parts.append(days_text(r.days))
    if r.window_from and r.window_to:
        parts.append(f"{r.window_from}–{r.window_to}")
    if r.only_dark:
        parts.append(tr("rule.only_dark_short"))
    if r.mode:
        parts.append(tr(f"mode.{r.mode}"))
    action = tr(f"action.{r.action}")
    if r.action in ("scene", "fade_in") and cfg.scene(r.scene_id):
        action += f": {cfg.scene(r.scene_id).name}"
    elif r.action in ("fade_in", "fade_out", "off_later"):
        action += f" ({r.minutes} min)"
    targets = cfg.target_name(r.targets, tr("all_lamps"))
    return f"{r.name}\n{' · '.join(parts)} → {action} · {targets}"


# ------------------------------------------------------------ diálogos ---
class PauseDialog(_Dialog):
    """Férias: pausar as rotinas até uma data."""

    def __init__(self, parent=None, current=""):
        super().__init__(parent, tr("pause.title"))
        self.body.addWidget(muted(tr("pause.note")))
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd/MM/yyyy")
        self.date.setMinimumDate(QDate.currentDate())
        try:
            self.date.setDate(QDate.fromString(current, "yyyy-MM-dd") if current else QDate.currentDate().addDays(7))
        except Exception:  # noqa: BLE001
            self.date.setDate(QDate.currentDate().addDays(7))
        form = QFormLayout()
        form.addRow(tr("pause.until"), self.date)
        self.body.addLayout(form)
        self.add_buttons(tr("pause.ok"))

    def value(self) -> str:
        return self.date.date().toString("yyyy-MM-dd")


class RuleDialog(_Dialog):
    def __init__(self, parent, cfg, rule: Rule = None, automation=None):
        super().__init__(parent, tr("rule.edit") if rule else tr("rule.new"))
        self.setMinimumWidth(540)
        self.cfg = cfg
        self.automation = automation
        self.rule = rule or Rule(name=tr("rule.default_name", n=len(cfg.rules) + 1))
        r = self.rule
        form = QFormLayout()
        form.setSpacing(9)
        self.form = form
        self.name = QLineEdit(r.name)
        form.addRow(tr("rule.name"), self.name)

        # ---- quando
        form.addRow(section(tr("rule.when")))
        self.trigger = QComboBox()
        for t in R.TRIGGERS:
            self.trigger.addItem(tr(f"trigger.{t}"), t)
        self.trigger.setCurrentIndex(max(0, self.trigger.findData(r.trigger)))
        self.trigger_hint = muted()
        self.time = QTimeEdit(QTime.fromString(r.time, "HH:mm"))
        self.time.setDisplayFormat("HH:mm")
        self.offset = QSpinBox()
        self.offset.setRange(-180, 180)
        self.offset.setSingleStep(5)
        self.offset.setValue(r.offset_min)
        self.offset.setSuffix(" min")
        self.delay = QSpinBox()
        self.delay.setRange(0, 240)
        self.delay.setValue(r.delay_min)
        self.delay.setSuffix(" min")
        self.idle = QSpinBox()
        self.idle.setRange(0, 240)
        self.idle.setValue(r.idle_min)
        self.idle.setSuffix(" min")
        self.idle.setSpecialValueText(tr("rule.idle_never"))
        self.any_fullscreen = QCheckBox(tr("rule.any_fullscreen"))
        self.any_fullscreen.setChecked(r.any_fullscreen)
        self.apps = QLineEdit(", ".join(r.apps))
        self.text = QLineEdit(r.text)
        self.text.setPlaceholderText(tr("rule.text_hint"))
        self.exclude = QLineEdit(r.exclude)
        self.hotkey = QKeySequenceEdit(QKeySequence(r.hotkey))
        try:
            self.hotkey.setMaximumSequenceLength(1)
        except AttributeError:  # Qt < 6.5
            pass
        self.suspend = QCheckBox(tr("rule.suspend"))
        self.suspend.setChecked(r.suspend)
        form.addRow(tr("rule.trigger"), self.trigger)
        form.addRow("", self.trigger_hint)
        form.addRow(tr("routine.time"), self.time)
        form.addRow(tr("routine.offset"), self.offset)
        form.addRow(tr("rule.delay"), self.delay)
        form.addRow(tr("rule.idle"), self.idle)
        form.addRow("", self.any_fullscreen)
        form.addRow(tr("rule.apps"), self.apps)
        form.addRow(tr("rule.text"), self.text)
        form.addRow(tr("rule.exclude"), self.exclude)
        form.addRow(tr("rule.hotkey"), self.hotkey)
        form.addRow("", self.suspend)

        # ---- se
        form.addRow(section(tr("rule.if")))
        self.day_buttons = []
        days = []
        for i, name in enumerate(tr("days.short").split(",")):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setChecked(i in r.days)
            b.setProperty("day", True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.day_buttons.append(b)
            days.append(b)
        form.addRow(tr("routine.days"), row_widget(*days))
        self.window_on = QCheckBox(tr("rule.window"))
        self.window_on.setChecked(bool(r.window_from and r.window_to))
        self.w_from = QTimeEdit(QTime.fromString(r.window_from or "18:00", "HH:mm"))
        self.w_to = QTimeEdit(QTime.fromString(r.window_to or "23:59", "HH:mm"))
        for w in (self.w_from, self.w_to):
            w.setDisplayFormat("HH:mm")
        self.window_on.toggled.connect(self._sync)
        form.addRow("", row_widget(self.window_on, self.w_from, QLabel("–"), self.w_to))
        self.only_dark = QCheckBox(tr("rule.only_dark"))
        self.only_dark.setChecked(r.only_dark)
        form.addRow("", self.only_dark)
        self.discord = QCheckBox(tr("rule.only_discord"))
        self.discord.setChecked(r.mode == "discord")
        form.addRow("", self.discord)

        # ---- então
        form.addRow(section(tr("rule.then")))
        self.action = QComboBox()
        for a in R.ACTIONS:
            self.action.addItem(tr(f"action.{a}"), a)
        self.action.setCurrentIndex(max(0, self.action.findData(r.action)))
        self.scene = QComboBox()
        self.restore_scene = QComboBox()
        for s in cfg.scenes:
            self.scene.addItem(s.name, s.id)
            self.restore_scene.addItem(s.name, s.id)
        self.scene.setCurrentIndex(max(0, self.scene.findData(r.scene_id)))
        self.restore_scene.setCurrentIndex(max(0, self.restore_scene.findData(r.restore_scene)))
        self.color = ColorButton(r.color)
        self.color2 = ColorButton(r.color2, allow_off=True)
        self.times = QSpinBox()
        self.times.setRange(1, 20)
        self.times.setValue(r.times)
        self.times.setSuffix("×")
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 240)
        self.minutes.setValue(r.minutes)
        self.minutes.setSuffix(" min")
        self.value_spin = QSpinBox()
        self.value_spin.setSuffix(" %")
        self.value_spin.setRange(-100, 100)
        self.value_spin.setValue(r.value)
        self.targets = TargetCombo(cfg, r.targets)
        self.restore = QComboBox()
        for key in ("previous", "scene", "none"):
            self.restore.addItem(tr(f"rule.restore_{key}"), key)
        self.restore.setCurrentIndex(max(0, self.restore.findData(r.restore)))
        form.addRow(tr("routine.action"), self.action)
        form.addRow(tr("scenes"), self.scene)
        form.addRow(tr("color"), self.color)
        form.addRow(tr("rule.color2"), self.color2)
        form.addRow(tr("rule.times"), self.times)
        form.addRow(tr("rule.minutes"), self.minutes)
        form.addRow(tr("rule.value"), self.value_spin)
        form.addRow(tr("routine.targets"), self.targets)
        form.addRow(tr("rule.restore"), self.restore)
        form.addRow(tr("rule.restore_scene"), self.restore_scene)
        self.body.addLayout(form)
        self.warn = muted()
        self.body.addWidget(self.warn)
        for combo in (self.trigger, self.action, self.restore):
            combo.currentIndexChanged.connect(self._sync)
        self._sync()
        self.test_btn = button(tr("rule.test"), self.test)
        self.add_buttons(extra=[self.test_btn] if automation is not None else None)

    def _sync(self):
        t, a = self.trigger.currentData(), self.action.currentData()
        f = self.form
        f.setRowVisible(self.time, t == "time")
        f.setRowVisible(self.offset, t in ("sunrise", "sunset"))
        f.setRowVisible(self.delay, t == "away")
        f.setRowVisible(self.idle, t == "away")
        f.setRowVisible(self.any_fullscreen, t == "fullscreen")
        f.setRowVisible(self.apps, t in ("fullscreen", "notification"))
        f.setRowVisible(self.text, t == "notification")
        f.setRowVisible(self.exclude, t == "notification")
        f.setRowVisible(self.hotkey, t == "hotkey")
        f.setRowVisible(self.suspend, t == "shutdown")
        label = f.labelForField(self.apps)
        if label is not None:
            label.setText(tr("rule.apps_fullscreen" if t == "fullscreen" else "rule.apps"))
        self.apps.setPlaceholderText(tr("rule.apps_fullscreen_hint" if t == "fullscreen" else "rule.apps_hint"))
        self.trigger_hint.setText(tr(f"trigger.{t}.hint"))
        for w in (self.w_from, self.w_to):
            w.setEnabled(self.window_on.isChecked())

        f.setRowVisible(self.scene, a in ("scene", "fade_in"))
        f.setRowVisible(self.color, a in ("color", "blink"))
        f.setRowVisible(self.color2, a == "blink")
        f.setRowVisible(self.times, a == "blink")
        f.setRowVisible(self.minutes, a in ("fade_in", "fade_out", "off_later"))
        f.setRowVisible(self.value_spin, a in ("brightness", "brightness_step"))
        if a == "brightness":
            self.value_spin.setRange(1, 100)
        else:
            self.value_spin.setRange(-100, 100)
        f.setRowVisible(self.targets, a not in ("pomodoro", "focus", "discord_mode", "circadian", "music"))
        lasting = t in R.STATE_TRIGGERS and (a in R.LOOK_ACTIONS or a == "screen")
        f.setRowVisible(self.restore, lasting)
        f.setRowVisible(self.restore_scene, lasting and self.restore.currentData() == "scene")
        self.adjustSize()

    def _collect(self, r: Rule) -> Rule:
        r.name = self.name.text().strip() or r.name
        r.trigger = self.trigger.currentData()
        r.time = self.time.time().toString("HH:mm")
        r.offset_min = self.offset.value()
        r.delay_min = self.delay.value()
        r.idle_min = self.idle.value()
        r.any_fullscreen = self.any_fullscreen.isChecked()
        r.apps = [a.strip() for a in self.apps.text().split(",") if a.strip()]
        r.text = self.text.text().strip()
        r.exclude = self.exclude.text().strip()
        r.hotkey = self.hotkey.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        r.suspend = self.suspend.isChecked()
        r.days = [i for i, b in enumerate(self.day_buttons) if b.isChecked()]
        on = self.window_on.isChecked()
        r.window_from = self.w_from.time().toString("HH:mm") if on else ""
        r.window_to = self.w_to.time().toString("HH:mm") if on else ""
        r.only_dark = self.only_dark.isChecked()
        r.mode = "discord" if self.discord.isChecked() else ""
        r.action = self.action.currentData()
        r.scene_id = self.scene.currentData() or ""
        r.color, r.color2 = list(self.color.rgb), list(self.color2.rgb)
        r.times = self.times.value()
        r.minutes = self.minutes.value()
        r.value = self.value_spin.value()
        r.targets = self.targets.value()
        r.restore = self.restore.currentData()
        r.restore_scene = self.restore_scene.currentData() or ""
        return r

    def _error(self, r: Rule) -> str:
        if not r.days:
            return tr("routine.no_days")
        if r.trigger == "hotkey" and not R.parse_hotkey(r.hotkey):
            return tr("rule.bad_hotkey")
        if r.trigger == "notification" and not (r.apps or r.text):
            return tr("rule.need_app")
        if r.trigger == "fullscreen" and not (r.any_fullscreen or r.apps):
            return tr("rule.need_program")
        if r.action in ("scene",) and not self.cfg.scene(r.scene_id):
            return tr("routine.no_scene")
        if r.trigger in ("sunrise", "sunset") and not self.cfg.settings.location.is_set:
            return tr("routine.need_location")
        return ""

    def test(self):
        tmp = self._collect(copy.deepcopy(self.rule))
        self.automation.run_action(tmp, manual=True)

    def accept_if_valid(self):
        err = self._error(self._collect(copy.deepcopy(self.rule)))
        if err:
            self.warn.setText(err)
        else:
            self.accept()

    def value(self) -> Rule:
        return self._collect(self.rule)


# ---------------------------------------------------------------- abas ---
class RulesPage(QWidget):
    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 8, 0, 0)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda *_: self.edit())
        self.list.itemChanged.connect(self._toggled)
        v.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(button(tr("btn.add"), self.add, primary=True))
        row.addWidget(button(tr("btn.edit"), self.edit))
        row.addWidget(button(tr("rule.duplicate"), self.duplicate))
        row.addWidget(button(tr("btn.remove"), self.remove, danger=True))
        row.addStretch(1)
        row.addWidget(button(tr("rule.examples"), self.examples))
        v.addLayout(row)
        v.addWidget(muted(tr("rule.note")))

    @property
    def cfg(self):
        return self.tab.win.store.config

    def refresh(self):
        self.list.blockSignals(True)
        row = self.list.currentRow()
        self.list.clear()
        for r in self.cfg.rules:
            it = QListWidgetItem(describe_rule(self.cfg, r))
            it.setData(Qt.ItemDataRole.UserRole, r.id)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if r.enabled else Qt.CheckState.Unchecked)
            self.list.addItem(it)
        self.list.setCurrentRow(min(row, self.list.count() - 1))
        self.list.blockSignals(False)

    def _rule(self, it=None):
        it = it or self.list.currentItem()
        rid = it.data(Qt.ItemDataRole.UserRole) if it else None
        return next((r for r in self.cfg.rules if r.id == rid), None)

    def _toggled(self, it):
        r = self._rule(it)
        if r:
            r.enabled = it.checkState() == Qt.CheckState.Checked
            self.tab.win.changed()

    def add(self):
        d = RuleDialog(self, self.cfg, automation=self.tab.win.automation)
        if d.exec():
            self.cfg.rules.append(d.value())
            self.tab.win.changed()

    def edit(self):
        r = self._rule()
        if r and RuleDialog(self, self.cfg, r, automation=self.tab.win.automation).exec():
            self.tab.win.changed()

    def duplicate(self):
        r = self._rule()
        if r:
            from ..storage import new_id
            dup = copy.deepcopy(r)
            dup.id = new_id()
            dup.name = tr("rule.copy_of", name=r.name)
            self.cfg.rules.insert(self.cfg.rules.index(r) + 1, dup)
            self.tab.win.changed()

    def remove(self):
        r = self._rule()
        if r and confirm(self, tr("confirm.remove", name=r.name)):
            self.cfg.rules.remove(r)
            self.tab.win.changed()

    def examples(self):
        from ..automation import default_rules
        have = {r.name for r in self.cfg.rules}
        new = [r for r in default_rules(tr, self.cfg) if r.name not in have]
        self.cfg.rules.extend(new)
        self.tab.win.changed()


def _spin(lo, hi, suffix=" min"):
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setSuffix(suffix)
    return s


class FeaturesPage(QScrollArea):
    """Recursos contínuos: modo foco, modo Discord, ciclo do dia, música, pomodoro e férias."""

    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        g = QGridLayout(inner)
        g.setContentsMargins(0, 8, 12, 8)
        g.setVerticalSpacing(10)
        g.setColumnStretch(1, 1)
        self.setWidget(inner)
        cfg = self.cfg
        row = 0

        def add(label, w):
            nonlocal row
            if label is None:
                g.addWidget(w, row, 0, 1, 2)
            else:
                g.addWidget(QLabel(label), row, 0)
                g.addWidget(w, row, 1)
            row += 1

        # modo foco
        add(None, section(tr("mode.focus")))
        self.focus_on = QCheckBox(tr("feature.focus_on"))
        add(None, self.focus_on)
        self.focus_targets = TargetCombo(cfg, cfg.settings.focus.targets)
        add(tr("routine.targets"), self.focus_targets)
        self.focus_scene = QComboBox()
        for sc in cfg.scenes:
            self.focus_scene.addItem(sc.name, sc.id)
        add(tr("feature.focus_scene"), self.focus_scene)
        self.focus_schedule = QCheckBox(tr("feature.focus_schedule"))
        self.focus_start = QTimeEdit()
        self.focus_end = QTimeEdit()
        for w in (self.focus_start, self.focus_end):
            w.setDisplayFormat("HH:mm")
        add(None, row_widget(self.focus_schedule, self.focus_start, QLabel("–"), self.focus_end))
        self.focus_days = []
        for i, name in enumerate(tr("days.short").split(",")):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setProperty("day", True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.toggled.connect(self._save)
            self.focus_days.append(b)
        add(tr("routine.days"), row_widget(*self.focus_days))
        add(None, muted(tr("feature.focus_note")))

        # modo Discord
        add(None, section(tr("mode.discord"), 14))
        self.discord = QCheckBox(tr("feature.discord_on"))
        add(None, self.discord)
        add(None, muted(tr("feature.discord_note")))

        # ciclo do dia
        add(None, section(tr("mode.circadian"), 14))
        self.circ = QCheckBox(tr("feature.circadian_on"))
        add(None, self.circ)
        self.circ_targets = TargetCombo(cfg, cfg.settings.circadian.targets)
        add(tr("routine.targets"), self.circ_targets)
        self.circ_bright = QCheckBox(tr("feature.circadian_brightness"))
        add(None, self.circ_bright)
        self.circ_night = _spin(5, 100, " %")
        add(tr("feature.night_brightness"), self.circ_night)
        add(None, muted(tr("feature.circadian_note")))

        # música
        add(None, section(tr("feature.music"), 14))
        self.music = QCheckBox(tr("feature.music_on"))
        add(None, self.music)
        self.music_source = QComboBox()
        self.music_source.addItem(tr("mode.music_cover"), "cover")
        self.music_source.addItem(tr("mode.music_screen"), "screen")
        add(tr("feature.music_source"), self.music_source)
        self.music_targets = TargetCombo(cfg, cfg.settings.music.targets)
        add(tr("routine.targets"), self.music_targets)
        self.music_bright = _spin(5, 100, " %")
        add(tr("brightness"), self.music_bright)
        add(None, muted(tr("feature.music_note")))

        # pomodoro
        add(None, section(tr("feature.pomodoro"), 14))
        self.p_focus, self.p_short, self.p_long = _spin(1, 180), _spin(1, 60), _spin(1, 90)
        self.p_every = _spin(1, 12, "")
        add(tr("pomodoro.focus"), self.p_focus)
        add(tr("pomodoro.short"), self.p_short)
        add(tr("pomodoro.long"), self.p_long)
        add(tr("feature.pomodoro_every"), self.p_every)
        self.p_targets = TargetCombo(cfg, cfg.settings.pomodoro.targets)
        add(tr("routine.targets"), self.p_targets)
        self.p_break_color = ColorButton(cfg.settings.pomodoro.break_color)
        self.p_focus_color = ColorButton(cfg.settings.pomodoro.focus_color)
        add(tr("feature.pomodoro_break_color"), self.p_break_color)
        add(tr("feature.pomodoro_focus_color"), self.p_focus_color)
        self.p_button = button("", self._toggle_pomodoro)
        add(None, row_widget(self.p_button))

        # férias
        add(None, section(tr("pause.title"), 14))
        self.pause = QCheckBox(tr("pause.until"))
        self.pause_date = QDateEdit()
        self.pause_date.setCalendarPopup(True)
        self.pause_date.setDisplayFormat("dd/MM/yyyy")
        add(None, row_widget(self.pause, self.pause_date))
        add(None, muted(tr("pause.note")))
        g.setRowStretch(row, 1)

        self.refresh()
        for w in (self.focus_on, self.focus_schedule, self.discord, self.circ, self.circ_bright, self.music,
                  self.pause):
            w.toggled.connect(self._save)
        for w in (self.focus_targets, self.focus_scene, self.circ_targets, self.music_source, self.music_targets,
                  self.p_targets):
            w.currentIndexChanged.connect(self._save)
        for w in (self.focus_start, self.focus_end):
            w.timeChanged.connect(self._save)
        for w in (self.circ_night, self.music_bright, self.p_focus, self.p_short, self.p_long, self.p_every):
            w.valueChanged.connect(self._save)
        self.pause_date.dateChanged.connect(self._save)
        for b in (self.p_break_color, self.p_focus_color):
            b.clicked.connect(lambda: QTimer.singleShot(0, self._save))  # depois do diálogo de cor
        self.tab.win.automation.pomodoro.changed.connect(self._pomodoro_label)
        self.tab.win.automation.changed.connect(self._sync_focus)  # ligado pelo painel ou pelo horário

    @property
    def cfg(self):
        return self.tab.win.store.config

    def _widgets(self):
        return self.findChildren(QWidget)

    def refresh(self):
        s = self.cfg.settings
        for w in self._widgets():
            w.blockSignals(True)
        f = s.focus
        self.focus_on.setChecked(f.active)
        self.focus_targets.set_value(f.targets)
        self.focus_scene.setCurrentIndex(max(0, self.focus_scene.findData(
            f.scene_id or self.tab.win.automation.focus_scene().id)))
        self.focus_schedule.setChecked(f.schedule)
        self.focus_start.setTime(QTime.fromString(f.start, "HH:mm"))
        self.focus_end.setTime(QTime.fromString(f.end, "HH:mm"))
        for i, b in enumerate(self.focus_days):
            b.setChecked(i in f.days)
        for w in (self.focus_start, self.focus_end, *self.focus_days):
            w.setEnabled(f.schedule)
        self.discord.setChecked(s.discord_mode)
        self.circ.setChecked(s.circadian.enabled)
        self.circ_targets.set_value(s.circadian.targets)
        self.circ_bright.setChecked(s.circadian.brightness)
        self.circ_night.setValue(s.circadian.night_brightness)
        self.music.setChecked(s.music.enabled)
        self.music_source.setCurrentIndex(max(0, self.music_source.findData(s.music.source)))
        self.music_targets.set_value(s.music.targets)
        self.music_bright.setValue(s.music.brightness)
        p = s.pomodoro
        self.p_focus.setValue(p.focus_min)
        self.p_short.setValue(p.short_min)
        self.p_long.setValue(p.long_min)
        self.p_every.setValue(p.every)
        self.p_targets.set_value(p.targets)
        self.p_break_color.set_rgb(p.break_color)
        self.p_focus_color.set_rgb(p.focus_color)
        paused = R.paused(s.pause_until, dt.date.today())
        self.pause.setChecked(paused)
        self.pause_date.setDate(QDate.fromString(s.pause_until, "yyyy-MM-dd") if paused
                                else QDate.currentDate().addDays(7))
        self.pause_date.setEnabled(paused)
        for w in self._widgets():
            w.blockSignals(False)
        self._pomodoro_label()

    def _sync_focus(self):
        on = self.cfg.settings.focus.active
        if self.focus_on.isChecked() != on:
            self.focus_on.blockSignals(True)
            self.focus_on.setChecked(on)
            self.focus_on.blockSignals(False)

    def _pomodoro_label(self):
        running = self.tab.win.automation.pomodoro.running()
        self.p_button.setText(tr("pomodoro.stop_short") if running else tr("pomodoro.start"))

    def _toggle_pomodoro(self):
        self.tab.win.automation.pomodoro.toggle()

    def _save(self, *_):
        s = self.cfg.settings
        auto = self.tab.win.automation
        f = s.focus
        focus_changed = (f.targets, f.scene_id) != (self.focus_targets.value(), self.focus_scene.currentData() or "")
        f.targets = self.focus_targets.value()
        f.scene_id = self.focus_scene.currentData() or ""
        f.schedule = self.focus_schedule.isChecked()
        f.start = self.focus_start.time().toString("HH:mm")
        f.end = self.focus_end.time().toString("HH:mm")
        f.days = [i for i, b in enumerate(self.focus_days) if b.isChecked()]
        for w in (self.focus_start, self.focus_end, *self.focus_days):
            w.setEnabled(f.schedule)
        if self.focus_on.isChecked() != f.active:
            auto.set_focus(self.focus_on.isChecked())
        elif f.active and focus_changed:  # outra cena/lâmpadas: reaplica o foco
            auto.set_focus(False)
            auto.set_focus(True)
        s.discord_mode = self.discord.isChecked()
        s.circadian.targets = self.circ_targets.value()
        s.circadian.brightness = self.circ_bright.isChecked()
        s.circadian.night_brightness = self.circ_night.value()
        s.music.source = self.music_source.currentData()
        s.music.targets = self.music_targets.value()
        s.music.brightness = self.music_bright.value()
        p = s.pomodoro
        p.focus_min, p.short_min, p.long_min = self.p_focus.value(), self.p_short.value(), self.p_long.value()
        p.every = self.p_every.value()
        p.targets = self.p_targets.value()
        p.break_color, p.focus_color = list(self.p_break_color.rgb), list(self.p_focus_color.rgb)
        s.pause_until = self.pause_date.date().toString("yyyy-MM-dd") if self.pause.isChecked() else ""
        self.pause_date.setEnabled(self.pause.isChecked())
        if self.circ.isChecked() != s.circadian.enabled:
            auto.set_circadian(self.circ.isChecked())
        if self.music.isChecked() != s.music.enabled:
            auto.set_music(self.music.isChecked())
        self.tab.win.changed()


class DiagnosticsPage(QWidget):
    """O que o app está enxergando (para descobrir por que uma automação não disparou)."""

    KEYS = ("locked", "display_off", "idle", "foreground", "fullscreen", "notifications", "last_notification",
            "hotkeys_failed", "media", "track", "uptime", "active")

    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 8, 0, 0)
        v.addWidget(muted(tr("diag.note")))
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setVerticalSpacing(8)
        self.values = {}
        for i, key in enumerate(self.KEYS):
            grid.addWidget(QLabel(tr(f"diag.{key}")), i, 0, Qt.AlignmentFlag.AlignTop)
            val = muted()
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.values[key] = val
            grid.addWidget(val, i, 1)
        v.addLayout(grid)
        v.addWidget(section(tr("diag.simulate")))
        self.sim_app = QLineEdit("com.squirrel.Discord.Discord")
        self.sim_text = QLineEdit(tr("diag.simulate_text"))
        v.addWidget(row_widget(self.sim_app, self.sim_text, button(tr("diag.simulate_run"), self._simulate),
                               stretch=False))
        v.addStretch(1)
        self.timer = QTimer(self, interval=1000)
        self.timer.timeout.connect(self.refresh)

    def showEvent(self, e):
        self.refresh()
        self.timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)

    def refresh(self):
        d = self.tab.win.automation.diagnostics()
        yes, no = tr("diag.yes"), tr("diag.no")
        for key, lbl in self.values.items():
            v = d.get(key)
            if isinstance(v, bool):
                v = yes if v else no
            elif key == "idle":
                v = f"{v} s"
            elif key == "uptime":
                v = f"{int(v // 60)} min" if v is not None else "—"
            elif key in ("notifications", "media"):
                v = tr("diag.ok") if v == "ok" else (tr("diag.missing") if v == "missing" else v)
            lbl.setText(str(v) if v not in ("", None) else "—")

    def _simulate(self):
        self.tab.win.automation.on_notification(self.sim_app.text().strip(), self.sim_text.text().strip())
        self.refresh()


class AutomationsTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 10, 0, 0)
        self.tabs = SegmentedTabs()
        self.rules = RulesPage(self)
        self.features = FeaturesPage(self)
        self.diag = DiagnosticsPage(self)
        self.tabs.addTab(self.rules, tr("rule.tab"))
        self.tabs.addTab(self.features, tr("feature.tab"))
        self.tabs.addTab(self.diag, tr("diag.tab"))
        v.addWidget(self.tabs)
        self.refresh()

    def refresh(self):
        self.rules.refresh()
        self.features.refresh()
