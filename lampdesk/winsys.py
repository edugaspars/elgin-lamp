"""Leituras do sistema usadas pelas automações (quase tudo só existe no Windows).

Cada função tem um caminho seguro: fora do Windows, ou se a chamada falhar, retorna um
valor neutro ("não bloqueado", "sem tela cheia", nenhuma notificação…). Nada aqui usa Qt.

Não testado localmente (o desenvolvimento roda no Linux): bloqueio de tela, tela cheia,
leitura das notificações, atalhos globais e mídia do Windows. A tela de Diagnóstico
(Configurações › Automações) mostra o que o app está enxergando.
"""

import logging
import os
import sqlite3
import sys
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

WINDOWS = sys.platform == "win32"


def _api():
    import ctypes
    from ctypes import wintypes
    return ctypes, wintypes


# ---------------------------------------------------------- tela e uso ---
def is_locked() -> bool:
    """Tela bloqueada (Win+L) ou tela de segurança (Ctrl+Alt+Del) à frente."""
    if not WINDOWS:
        return False
    try:
        ctypes, wintypes = _api()
        user32 = ctypes.windll.user32
        user32.OpenInputDesktop.restype = wintypes.HANDLE
        h = user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
        if not h:
            return True  # a área de trabalho de entrada não é a nossa: bloqueado
        try:
            buf = ctypes.create_unicode_buffer(64)
            ok = user32.GetUserObjectInformationW(wintypes.HANDLE(h), 2, buf, ctypes.sizeof(buf), None)  # UOI_NAME
            return bool(ok) and buf.value.casefold() != "default"
        finally:
            user32.CloseDesktop(wintypes.HANDLE(h))
    except Exception:  # noqa: BLE001
        log.debug("is_locked falhou", exc_info=True)
        return False


def idle_seconds() -> float:
    """Tempo desde o último uso do teclado/mouse."""
    if not WINDOWS:
        return 0.0
    try:
        ctypes, wintypes = _api()

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        now = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
        return ((now - info.dwTime) & 0xFFFFFFFF) / 1000.0
    except Exception:  # noqa: BLE001
        return 0.0


def uptime_seconds() -> Optional[float]:
    """Há quanto tempo o PC ligou (para o "ao ligar o PC" não disparar em qualquer abertura do app)."""
    try:
        if WINDOWS:
            ctypes, _ = _api()
            k = ctypes.windll.kernel32
            k.GetTickCount64.restype = ctypes.c_ulonglong
            return k.GetTickCount64() / 1000.0
        with open("/proc/uptime", encoding="ascii") as f:
            return float(f.read().split()[0])
    except Exception:  # noqa: BLE001
        return None


_SHELL_CLASSES = {"progman", "workerw", "shell_traywnd", "shell_secondarytraywnd"}


def foreground() -> Tuple[str, bool]:
    """(nome do executável em primeiro plano, se está em tela cheia)."""
    if not WINDOWS:
        return "", False
    try:
        ctypes, wintypes = _api()
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        raw = user32.GetForegroundWindow()
        if not raw:
            return "", False
        hwnd = wintypes.HWND(raw)  # handle de 64 bits: não deixar o ctypes converter para int de 32
        exe = _process_name(hwnd)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if cls.value.casefold() in _SHELL_CLASSES:
            return exe, False
        return exe, _covers_monitor(hwnd) or _busy_state()
    except Exception:  # noqa: BLE001
        log.debug("foreground falhou", exc_info=True)
        return "", False


def _process_name(hwnd) -> str:
    ctypes, wintypes = _api()
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    k = ctypes.windll.kernel32
    k.OpenProcess.restype = wintypes.HANDLE
    h = k.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if k.QueryFullProcessImageNameW(wintypes.HANDLE(h), 0, buf, ctypes.byref(size)):
            return Path(buf.value).name.casefold()
        return ""
    finally:
        k.CloseHandle(wintypes.HANDLE(h))


def _covers_monitor(hwnd) -> bool:
    ctypes, wintypes = _api()
    user32 = ctypes.windll.user32

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    mon = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not mon or not user32.GetMonitorInfoW(wintypes.HMONITOR(mon), ctypes.byref(info)):
        return False
    m = info.rcMonitor
    return covers((rect.left, rect.top, rect.right, rect.bottom), (m.left, m.top, m.right, m.bottom))


FULLSCREEN_TOLERANCE_PX = 3


def covers(window: Tuple[int, int, int, int], monitor: Tuple[int, int, int, int],
           tolerance: int = FULLSCREEN_TOLERANCE_PX) -> bool:
    """A janela (left, top, right, bottom) cobre o monitor inteiro? Vale para tela cheia com ou sem bordas.

    Alguns jogos e players deixam a janela sem bordas 1–2 px menor que o monitor (para o Windows não
    tratar como tela cheia exclusiva): a tolerância cobre isso. Uma janela maximizada não conta,
    porque a barra de tarefas tira bem mais que isso.
    """
    wl, wt, wr, wb = window
    ml, mt, mr, mb = monitor
    t = tolerance
    return wl <= ml + t and wt <= mt + t and wr >= mr - t and wb >= mb - t


def _busy_state() -> bool:
    """O Windows também avisa quando um jogo (Direct3D) ou apresentação está em tela cheia."""
    ctypes, _ = _api()
    state = ctypes.c_int(0)
    if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
        return False
    return state.value in (2, 3, 4)  # BUSY, RUNNING_D3D_FULL_SCREEN, PRESENTATION_MODE


# --------------------------------------------------------- notificações ---
def notifications_db() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Microsoft" / "Windows" / "Notifications" / "wpndatabase.db"


class NotificationReader:
    """Lê as notificações novas do banco que o próprio Windows mantém.

    O Discord (e outros apps) não oferecem um jeito aberto de avisar programas de fora;
    as notificações que aparecem no canto da tela ficam registradas aqui.
    """

    QUERY = ("SELECT n.Id, h.PrimaryId, n.Payload FROM Notification n "
             "JOIN NotificationHandler h ON n.HandlerId = h.RecordId "
             "WHERE n.Id > ? AND n.Type = 'toast' ORDER BY n.Id")

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else notifications_db()
        self.last_id: Optional[int] = None
        self.error = ""

    def available(self) -> bool:
        return self.path.exists()

    def poll(self) -> List[Tuple[str, str]]:
        """[(app_id, xml)] das notificações que chegaram desde a última chamada."""
        if not self.path.exists():
            self.error = "missing"
            return []
        try:
            con = sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True, timeout=1)
            try:
                if self.last_id is None:  # primeira leitura: só marca onde estamos
                    row = con.execute("SELECT MAX(Id) FROM Notification").fetchone()
                    self.last_id = int(row[0] or 0)
                    self.error = ""
                    return []
                rows = con.execute(self.QUERY, (self.last_id,)).fetchall()
            finally:
                con.close()
        except Exception as exc:  # noqa: BLE001 - banco ocupado, formato diferente…
            self.error = str(exc)
            return []
        self.error = ""
        out = []
        for nid, app, payload in rows:
            self.last_id = max(self.last_id, int(nid))
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8", "replace")
            out.append((app or "", payload or ""))
        return out


# ------------------------------------------------------- atalhos globais ---
class HotkeyThread(threading.Thread):
    """Registra atalhos globais (RegisterHotKey) numa thread com laço de mensagens próprio."""

    WM_HOTKEY, WM_QUIT = 0x0312, 0x0012

    def __init__(self, keys: Dict[int, Tuple[int, int]], on_hotkey: Callable[[int], None]):
        super().__init__(daemon=True, name="hotkeys")
        self.keys = keys
        self.on_hotkey = on_hotkey
        self.failed: List[int] = []
        self._tid = 0
        self._ready = threading.Event()

    def run(self):
        if not WINDOWS:
            self.failed = list(self.keys)
            self._ready.set()
            return
        try:
            ctypes, wintypes = _api()
            user32 = ctypes.windll.user32
            self._tid = ctypes.windll.kernel32.GetCurrentThreadId()
            for hid, (mods, vk) in self.keys.items():
                if not user32.RegisterHotKey(None, hid, mods | 0x4000, vk):  # MOD_NOREPEAT
                    self.failed.append(hid)  # combinação já usada por outro programa
            self._ready.set()
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == self.WM_HOTKEY:
                    try:
                        self.on_hotkey(int(msg.wParam))
                    except Exception:  # noqa: BLE001
                        log.exception("Atalho %s", msg.wParam)
            for hid in self.keys:
                user32.UnregisterHotKey(None, hid)
        except Exception:  # noqa: BLE001
            log.warning("Atalhos globais indisponíveis", exc_info=True)
            self.failed = list(self.keys)
            self._ready.set()

    def wait_ready(self, timeout: float = 1.0):
        self._ready.wait(timeout)

    def stop(self):
        if WINDOWS and self._tid:
            try:
                ctypes, _ = _api()
                ctypes.windll.user32.PostThreadMessageW(self._tid, self.WM_QUIT, 0, 0)
            except Exception:  # noqa: BLE001
                pass


# ------------------------------------------------------------------ mídia ---
def media_available() -> bool:
    if not WINDOWS:
        return False
    try:
        import importlib.util
        return importlib.util.find_spec("winrt.windows.media.control") is not None
    except Exception:  # noqa: BLE001
        return False


def media_now(want_cover: Callable[[str], bool] = lambda _key: True):
    """O que o controle de mídia do Windows mostra agora: (estado, "título - artista", bytes da capa).

    Estado: "playing", "paused" (pausado, parado ou nada aberto) ou "busy" (o player está trocando de
    faixa: não é pausa). A capa só é lida quando `want_cover(chave)` pede, para não ler a mesma
    imagem a cada segundo. Usa os mesmos controles do volume na barra de tarefas: Spotify, YouTube
    no navegador, players… Bloqueante: chamar fora da thread da interface.
    """
    if not WINDOWS:
        return "paused", "", None
    import asyncio
    try:
        return asyncio.run(_media_async(want_cover))
    except Exception:  # noqa: BLE001
        log.debug("Mídia indisponível", exc_info=True)
        return "paused", "", None


async def _media_async(want_cover):
    from winrt.windows.media.control import \
        GlobalSystemMediaTransportControlsSessionManager as Manager
    manager = await Manager.request_async()
    session = manager.get_current_session()
    if session is None:
        return "paused", "", None
    status = int(session.get_playback_info().playback_status)
    if status in (1, 2):  # Opened / Changing: pulando de faixa
        return "busy", "", None
    if status != 4:       # Closed, Stopped, Paused
        return "paused", "", None
    props = await session.try_get_media_properties_async()
    key = f"{props.title} - {props.artist}"
    if props.thumbnail is None or not want_cover(key):
        return "playing", key, None
    from winrt.windows.storage.streams import DataReader
    stream = await props.thumbnail.open_read_async()
    size = int(stream.size)
    reader = DataReader(stream.get_input_stream_at(0))
    await reader.load_async(size)
    try:
        data = bytes(memoryview(reader.read_buffer(size)))
    except TypeError:  # versões antigas do pywinrt
        buf = bytearray(size)
        reader.read_bytes(buf)
        data = bytes(buf)
    return "playing", key, data
