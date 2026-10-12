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
    mode: str = "white"           # "white" | "colour"
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


@dataclass
class Config:
    lamps: List[Lamp] = field(default_factory=list)
    scenes: List[Scene] = field(default_factory=list)
    routines: List[Routine] = field(default_factory=list)
    settings: Settings = field(default_factory=Settings)

    # ----------------------------------------------------------- helpers ---
    def lamp(self, lamp_id: str) -> Optional[Lamp]:
        return next((l for l in self.lamps if l.id == lamp_id), None)

    def scene(self, scene_id: str) -> Optional[Scene]:
        return next((s for s in self.scenes if s.id == scene_id), None)

    def resolve_targets(self, targets: List[str]) -> List[Lamp]:
        if "*" in targets:
            return list(self.lamps)
        return [l for l in self.lamps if l.id in targets]

    # ------------------------------------------------------ serialização ---
    def to_dict(self) -> dict:
        return {"schema": 1, **asdict(self)}

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        def build(kind, items):
            names = kind.__dataclass_fields__.keys()
            return [kind(**{k: v for k, v in it.items() if k in names}) for it in items or []]

        s = data.get("settings") or {}
        loc = s.get("location") or {}
        settings = Settings(
            language=s.get("language", ""),
            autostart=bool(s.get("autostart", False)),
            location=Location(**{k: loc[k] for k in ("label", "latitude", "longitude") if k in loc}),
            last_selected=s.get("last_selected", "*"),
        )
        return cls(
            lamps=build(Lamp, data.get("lamps")),
            scenes=build(Scene, data.get("scenes")),
            routines=build(Routine, data.get("routines")),
            settings=settings,
        )


def default_scenes(tr) -> List[Scene]:
    return [
        Scene(tr("scene.reading"), "white", 90, 55),
        Scene(tr("scene.relax"), "white", 45, 0),
        Scene(tr("scene.focus"), "white", 100, 100),
        Scene(tr("scene.night"), "colour", 10, 0, [255, 120, 30]),
        Scene(tr("scene.movie"), "colour", 25, 0, [90, 60, 255]),
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
