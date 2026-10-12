"""Login por QR Code do Smart Life, com a nuvem da Tuya simulada."""

import os
import time
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from elgin_lamp import discovery  # noqa: E402

FAKE_KEY = "k3y!" * 4  # chave fictícia


class FakeControl:
    def __init__(self):
        self.polls = 0

    def qr_code(self, client_id, schema, user_code):
        assert client_id == discovery.SMARTLIFE_CLIENT_ID and user_code == "Ab1Cd2"
        return {"success": True, "result": {"qrcode": "tok123"}}

    def login_result(self, token, client_id, user_code):
        self.polls += 1
        if self.polls < 2:
            return False, {"msg": "not scanned"}
        return True, {"t": 1, "uid": "u", "expire_time": 7200, "access_token": "a",
                      "refresh_token": "r", "terminal_id": "term", "endpoint": "https://x"}


class FakeManager:
    unloaded = False

    def __init__(self, client_id, user_code, terminal_id, end_point, token):
        assert terminal_id == "term" and token["access_token"] == "a"
        self.device_map = {}

    def update_device_cache(self):
        self.device_map = {
            "ebcaaaa3": SimpleNamespace(id="ebcaaaa3", name="Quarto Mãe", local_key=FAKE_KEY,
                                        ip="200.1.2.3"),
            "hub1": SimpleNamespace(id="hub1", name="Hub", local_key=""),
        }

    def unload(self):
        FakeManager.unloaded = True


@pytest.fixture
def fake_tuya(monkeypatch):
    import tuya_sharing
    monkeypatch.setattr(tuya_sharing, "LoginControl", FakeControl)
    monkeypatch.setattr(tuya_sharing, "Manager", FakeManager)
    FakeManager.unloaded = False


def test_login_flow(fake_tuya):
    login = discovery.SmartLifeLogin("Ab1Cd2")
    assert login.start() == "tuyaSmart--qrLogin?token=tok123"
    assert login.poll() is None
    info = login.poll()
    found = login.fetch(info)
    assert [f.device_id for f in found] == ["ebcaaaa3"]  # sem Local Key fica de fora
    assert found[0].local_key == FAKE_KEY
    assert found[0].ip == ""  # IP público da nuvem nunca é usado
    assert FakeManager.unloaded  # sessão encerrada


def test_start_error(monkeypatch):
    import tuya_sharing

    class Bad(FakeControl):
        def qr_code(self, *a):
            return {"success": False, "msg": "user code invalid"}
    monkeypatch.setattr(tuya_sharing, "LoginControl", Bad)
    with pytest.raises(RuntimeError, match="user code invalid"):
        discovery.SmartLifeLogin("x").start()


def test_lamp_dialog_fills_key(fake_tuya, monkeypatch):
    from PySide6.QtWidgets import QApplication, QDialog
    from elgin_lamp.ui import settings as S

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(discovery, "scan_lan", lambda: [])
    S.SmartLifeDialog.TIMEOUT_S = 30

    dlg = S.LampDialog(None, demo=True)
    dlg.ip.setText("192.168.0.10")
    dlg.dev.setText("ebcaaaa3")

    def drive(sl):
        sl.poll_timer.setInterval(20)
        sl.code.setText("Ab1Cd2")
        sl.run()
        end = time.monotonic() + 5
        while sl.result() != QDialog.DialogCode.Accepted and time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)
        assert sl.qr.matrix  # QR foi desenhado
        return sl.result()

    monkeypatch.setattr(S.SmartLifeDialog, "exec", lambda self: drive(self))
    dlg.fetch_key()
    assert dlg.key.text() == FAKE_KEY
    assert dlg.ip.text() == "192.168.0.10"
