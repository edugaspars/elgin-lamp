"""Modelo de dados e persistência criptografada da configuração."""

import json
import logging
import shutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import List, Optional

from . import crypto
from .paths import config_file

log = logging.getLogger(__name__)

PROTOCOL_VERSIONS = ["auto", "3.3", "3.4", "3.5", "3.1"]
REACTIVE_MODES = ("screen", "cover")
ROOM = "@room"  # alvo "Ambiente deste PC": as lâmpadas escolhidas em Settings.room  # cenas que acompanham a tela ou a música (ver automation)


def new_id() -> str:
    return uuid.uuid4().hex[:10]


@dataclass
class Lamp:
    name: str
    device_id: str
    ip: str
    local_key: str
    version: str = "auto"  # "auto" ou "3.1".."3.5"
    id: str = field(default_factory=new_id)


@dataclass
class Scene:
    name: str
    mode: str = "white"           # "white" | "colour" | reativas: "screen" (tela) e "cover" (capa do álbum)
    brightness: int = 100         # 1..100
    temperature: int = 50         # 0 (quente) .. 100 (frio)
    color: List[int] = field(default_factory=lambda: [255, 160, 60])
    id: str = field(default_factory=new_id)


@dataclass
class Routine:
    name: str
    trigger: str = "time"         # "time" | "sunrise" | "sunset"
    time: str = "07:00"           # HH:MM, usado quando trigger == "time"
    offset_min: int = 0           # deslocamento para nascer/pôr do sol
    days: List[int] = field(default_factory=lambda: list(range(7)))  # 0=seg .. 6=dom
    action: str = "on"            # "on" | "off" | "scene"
    scene_id: str = ""
    targets: List[str] = field(default_factory=lambda: ["*"])  # ids de Lamp ou "*"
    enabled: bool = True
    id: str = field(default_factory=new_id)


@dataclass
class Group:
    name: str
    members: List[str] = field(default_factory=list)  # ids de Lamp
    id: str = field(default_factory=new_id)


@dataclass
class Rule:
    """Automação "Quando [gatilho] / Se [condições] / Então [ação]"."""

    name: str
    # -- quando
    trigger: str = "away"         # ver rules.TRIGGERS
    time: str = "07:00"           # "time"
    offset_min: int = 0           # "sunrise" | "sunset"
    delay_min: int = 1            # "away": minutos depois de bloquear/apagar a tela
    idle_min: int = 0             # "away": também conta X min sem mexer no PC (0 = não)
    apps: List[str] = field(default_factory=list)  # "fullscreen": programas extras; "notification": apps
    any_fullscreen: bool = True   # "fullscreen": qualquer programa em tela cheia
    text: str = ""                # "notification": contém (alternativas separadas por |)
    exclude: str = ""             # "notification": não contém
    hotkey: str = ""              # "hotkey": ex. "Ctrl+Alt+L"
    suspend: bool = True          # "shutdown": também ao suspender
    # -- se
    days: List[int] = field(default_factory=lambda: list(range(7)))
    window_from: str = ""         # HH:MM; vazio = qualquer hora
    window_to: str = ""
    only_dark: bool = False       # só entre o pôr e o nascer do sol
    mode: str = ""                # "discord": só com o modo Discord ligado
    # -- então
    action: str = "off"           # ver rules.ACTIONS
    scene_id: str = ""
    color: List[int] = field(default_factory=lambda: [40, 110, 255])
    color2: List[int] = field(default_factory=lambda: [0, 0, 0])  # "blink": [0, 0, 0] = apagada
    times: int = 3                # "blink": repetições
    minutes: int = 15             # "fade_in" | "fade_out" | "off_later"
    value: int = 10               # "brightness" (%) | "brightness_step" (±%)
    restore: str = "previous"     # gatilhos de estado, ao terminar: "previous" | "scene" | "none"
    restore_scene: str = ""
    targets: List[str] = field(default_factory=lambda: [ROOM])
    enabled: bool = True
    id: str = field(default_factory=new_id)


@dataclass
class Circadian:
    enabled: bool = False
    targets: List[str] = field(default_factory=lambda: [ROOM])
    brightness: bool = True       # também ajusta o brilho (não só a temperatura)
    night_brightness: int = 40


@dataclass
class Music:
    enabled: bool = False
    source: str = "cover"         # "cover" (capa do álbum) | "screen" (cor da tela)
    targets: List[str] = field(default_factory=lambda: [ROOM])
    brightness: int = 80


@dataclass
class Pomodoro:
    focus_min: int = 25
    short_min: int = 5
    long_min: int = 15
    every: int = 4                # pausa longa a cada N focos
    targets: List[str] = field(default_factory=lambda: [ROOM])
    focus_color: List[int] = field(default_factory=lambda: [255, 60, 40])   # pisca ao fim da pausa
    break_color: List[int] = field(default_factory=lambda: [40, 220, 90])   # pisca ao fim do foco


@dataclass
class Focus:
    """Modo foco (trabalho/estudo/reuniões): automações não mexem na luz destas lâmpadas."""
    active: bool = False
    targets: List[str] = field(default_factory=lambda: [ROOM])
    scene_id: str = ""            # cena aplicada ao ligar ("" = cena Foco)
    schedule: bool = True         # liga/desliga sozinho no horário de trabalho
    start: str = "08:00"
    end: str = "17:50"
    days: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])


@dataclass
class Location:
    label: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @property
    def is_set(self) -> bool:
        return self.latitude is not None and self.longitude is not None


@dataclass
class Settings:
    language: str = ""            # "" = detectar do sistema
    autostart: bool = False
    location: Location = field(default_factory=Location)
    last_selected: str = "*"
    room: List[str] = field(default_factory=lambda: ["*"])  # ambiente deste PC (grupo ou lâmpada)
    room_asked: bool = False      # já perguntou qual é o ambiente
    theme: str = "dark"           # "dark" | "light"
    reduce_transparency: bool = False
    discord_mode: bool = False
    pause_until: str = ""         # data ISO: rotinas pausadas (férias) até esse dia, inclusive
    countdown_pending: bool = False  # o app pediu às lâmpadas para desligarem sozinhas
    circadian: Circadian = field(default_factory=Circadian)
    music: Music = field(default_factory=Music)
    pomodoro: Pomodoro = field(default_factory=Pomodoro)
    focus: Focus = field(default_factory=Focus)
    rules_seeded: bool = False
    rules_version: int = 0        # exemplos atualizados (ver automation.upgrade_rules)


@dataclass
class Config:
    lamps: List[Lamp] = field(default_factory=list)
    scenes: List[Scene] = field(default_factory=list)
    routines: List[Routine] = field(default_factory=list)
    groups: List[Group] = field(default_factory=list)
    rules: List[Rule] = field(default_factory=list)
    settings: Settings = field(default_factory=Settings)

    # ----------------------------------------------------------- helpers ---
    def lamp(self, lamp_id: str) -> Optional[Lamp]:
        return next((l for l in self.lamps if l.id == lamp_id), None)

    def scene(self, scene_id: str) -> Optional[Scene]:
        return next((s for s in self.scenes if s.id == scene_id), None)

    def group(self, group_id: str) -> Optional[Group]:
        return next((g for g in self.groups if g.id == group_id), None)

    def resolve_targets(self, targets: List[str]) -> List[Lamp]:
        if ROOM in targets:  # ambiente deste PC
            targets = [t for t in targets if t != ROOM] + [t for t in self.settings.room if t != ROOM]
        if "*" in targets:
            return list(self.lamps)
        ids = set(targets)
        for g in self.groups:
            if g.id in ids:
                ids.update(g.members)
        return [l for l in self.lamps if l.id in ids]

    def target_name(self, targets: List[str], all_label: str, room_label: str = "") -> str:
        if ROOM in targets:
            inner = self.target_name(self.settings.room, all_label)
            return f"{room_label} ({inner})" if room_label else inner
        if "*" in targets:
            return all_label
        names = []
        for t in targets:
            item = self.group(t) or self.lamp(t)
            if item:
                names.append(item.name)
        return ", ".join(names) or all_label

    def forget(self, item_id: str) -> None:
        """Tira uma lâmpada/grupo removido de grupos, rotinas, regras e recursos."""
        for g in self.groups:
            g.members = [m for m in g.members if m != item_id]
        s = self.settings
        for holder in [*self.routines, *self.rules, s.circadian, s.music, s.pomodoro, s.focus]:
            holder.targets = [t for t in holder.targets if t != item_id] or ["*"]
        if s.last_selected == item_id:
            s.last_selected = "*"
        s.room = [t for t in s.room if t != item_id] or ["*"]

    # ------------------------------------------------------ serialização ---
    def to_dict(self) -> dict:
        return {"schema": 1, **asdict(self)}

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        def one(kind, item):
            names = kind.__dataclass_fields__.keys()
            return kind(**{k: v for k, v in (item or {}).items() if k in names})

        def build(kind, items):
            return [one(kind, it) for it in items or []]

        s = data.get("settings") or {}
        loc = s.get("location") or {}
        settings = Settings(
            language=s.get("language", ""),
            autostart=bool(s.get("autostart", False)),
            location=Location(**{k: loc[k] for k in ("label", "latitude", "longitude") if k in loc}),
            last_selected=s.get("last_selected", "*"),
            room=[t for t in (s.get("room") or ["*"]) if t != ROOM] or ["*"],
            room_asked=bool(s.get("room_asked", False)),
            theme=s.get("theme") if s.get("theme") in ("dark", "light") else "dark",
            reduce_transparency=bool(s.get("reduce_transparency", False)),
            discord_mode=bool(s.get("discord_mode", False)),
            pause_until=s.get("pause_until") or "",
            countdown_pending=bool(s.get("countdown_pending", False)),
            circadian=one(Circadian, s.get("circadian")),
            music=one(Music, s.get("music")),
            pomodoro=one(Pomodoro, s.get("pomodoro")),
            focus=one(Focus, s.get("focus")),
            rules_seeded=bool(s.get("rules_seeded", False)),
            rules_version=int(s.get("rules_version", 0) or 0),
        )
        return cls(
            lamps=build(Lamp, data.get("lamps")),
            scenes=build(Scene, data.get("scenes")),
            routines=build(Routine, data.get("routines")),
            groups=build(Group, data.get("groups")),
            rules=build(Rule, data.get("rules")),
            settings=settings,
        )


def default_scenes(tr) -> List[Scene]:
    return [
        Scene(tr("scene.reading"), "white", 90, 55),
        Scene(tr("scene.relax"), "white", 45, 0),
        Scene(tr("scene.focus"), "white", 100, 100),
        Scene(tr("scene.night"), "colour", 10, 0, [255, 120, 30]),
        Scene(tr("scene.ambilight"), "screen", 100, 50),
        Scene(tr("scene.music"), "cover", 100, 50),
    ]


class Store:
    """Carrega/salva a configuração criptografada em %APPDATA%."""

    def __init__(self, path=None):
        self.path = path or config_file()
        self._lock = threading.Lock()
        self.config = Config()
        self.load_error: Optional[str] = None

    def load(self) -> Config:
        if not self.path.exists():
            return self.config
        try:
            raw = crypto.decrypt(self.path.read_bytes())
            self.config = Config.from_dict(json.loads(raw.decode("utf-8")))
        except Exception as exc:  # arquivo corrompido ou de outro usuário
            backup = self.path.with_name(f"{self.path.stem}.unreadable-{int(time.time())}.dat")
            shutil.copy2(self.path, backup)
            self.load_error = str(exc)
            log.error("Não foi possível ler a configuração (%s). Backup em %s", exc, backup.name)
            self.config = Config()
        return self.config

    def save(self) -> None:
        with self._lock:
            payload = json.dumps(self.config.to_dict(), ensure_ascii=False).encode("utf-8")
            blob = crypto.encrypt(payload)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_bytes(blob)
            tmp.replace(self.path)
