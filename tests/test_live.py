"""Conexão ao vivo (LiveBulb) contra uma lâmpada Tuya 3.3 simulada por TCP."""

import threading
import time

import pytest

from elgin_lamp.lamp import LampState, LiveBulb
from elgin_lamp.storage import Lamp
from fake_tuya import DEV_ID, KEY, FakeTuyaBulb


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.005)
    return False


@pytest.fixture
def setup():
    created = []

    def make(**sim_kwargs):
        sim = FakeTuyaBulb(**sim_kwargs)
        states = []
        live = LiveBulb(Lamp("Sala", DEV_ID, "127.0.0.1", KEY, "3.3"), states.append, port=sim.port)
        live.start()
        created.append((sim, live))
        assert wait_for(lambda: states and states[-1].online), "não conectou"
        return sim, live, states

    yield make
    for sim, live in created:
        live.stop()
        sim.close()


def test_command_is_fast_even_when_bulb_only_acks(setup):
    sim, live, _ = setup(accept_delay=0.3)
    sim._push = lambda *a: None  # lâmpada que só manda a confirmação vazia (o caso lento)
    for on in (False, True, False):
        n = len(sim.received)
        t = time.monotonic()
        live.command("power", on, LampState())
        assert wait_for(lambda: len(sim.received) > n, 1.0)
        assert sim.received[-1][0] - t < 0.3  # antes: ~3,3 s por comando
    assert sim.connections == 1  # uma conexão só, reaproveitada


def test_external_change_arrives_in_real_time(setup):
    sim, live, states = setup()
    sim.external_set({"20": False})  # "Alexa, desligar a sala"
    assert wait_for(lambda: states[-1].is_on is False, 1.0)
    sim.external_set({"20": True, "22": 1000})
    assert wait_for(lambda: states[-1].is_on and states[-1].brightness == 100, 1.0)


def test_stale_report_does_not_undo_new_command(setup):
    sim, live, states = setup()
    live.command("brightness", 30, LampState(mode="white"))
    assert wait_for(lambda: sim.dps["22"] == 300)
    sim.external_set({"22": 500})  # a lâmpada ainda reporta o valor antigo
    time.sleep(0.2)
    assert states[-1].brightness == 30


def test_slider_burst_is_coalesced(setup):
    sim, live, _ = setup()
    n = len(sim.received)
    for v in range(1, 31):
        live.command("brightness", v * 3, LampState(mode="white"))
        time.sleep(0.01)
    assert wait_for(lambda: sim.dps["22"] == 900)
    sent = len(sim.received) - n
    assert sent < 15, sent  # ~12/s no máximo, sempre terminando no último valor


def test_reconnects_after_connection_drop(setup):
    sim, live, states = setup()
    sim.drop_clients()
    assert wait_for(lambda: not states[-1].online, 3.0)
    assert wait_for(lambda: states[-1].online, 5.0)
    live.command("power", False, LampState())
    assert wait_for(lambda: sim.dps["20"] is False, 2.0)


def test_command_while_offline_is_sent_after_reconnect(setup):
    sim, live, states = setup()
    sim.drop_clients()
    live.command("power", False, LampState())
    assert wait_for(lambda: sim.dps["20"] is False, 5.0)


def test_offline_bulb_reports_error():
    states = []
    ev = threading.Event()

    def on_state(st):
        states.append(st)
        ev.set()
    live = LiveBulb(Lamp("X", DEV_ID, "127.0.0.1", KEY, "3.3"), on_state, port=1)
    live.start()
    try:
        assert ev.wait(5)
        assert not states[-1].online and states[-1].error
    finally:
        live.stop()


def test_end_to_end_through_service(monkeypatch):
    """Clique no app → lâmpada (TCP) e Alexa → painel, pelo mesmo caminho do app real."""
    import functools
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from elgin_lamp import service as service_mod
    from elgin_lamp.service import LampService
    from elgin_lamp.storage import Store

    app = QApplication.instance() or QApplication([])
    sim = FakeTuyaBulb(accept_delay=0.2)
    sim._push = lambda *a: None  # o caso lento: só confirmação vazia
    monkeypatch.setattr(service_mod, "LiveBulb", functools.partial(LiveBulb, port=sim.port))

    store = Store(None)
    store.config.lamps = [Lamp("Sala", DEV_ID, "127.0.0.1", KEY, "3.3")]
    svc = LampService(store)
    lid = store.config.lamps[0].id

    def pump(cond, timeout=3.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            app.processEvents()
            if cond():
                return True
            time.sleep(0.005)
        return False

    try:
        assert pump(lambda: svc.state(lid).online)
        t = time.monotonic()
        svc.set_power([lid], False)
        assert svc.state(lid).is_on is False  # a tela muda na hora (otimista)
        assert wait_for(lambda: sim.dps["20"] is False, 1.0)
        assert time.monotonic() - t < 0.3

        del sim._push  # volta a avisar mudanças
        # Alexa liga logo após o clique: cai na janela de "valor antigo" e é
        # descartada, mas o app confere o estado real quando a janela termina
        sim.external_set({"20": True})
        assert pump(lambda: svc.state(lid).is_on, 2.5)
        time.sleep(1.1)
        sim.external_set({"20": False})  # fora da janela: chega na hora
        assert pump(lambda: svc.state(lid).is_on is False, 0.5)
    finally:
        svc.shutdown()
        sim.close()
