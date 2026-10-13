"""Leituras do Windows que dá para conferir fora dele (o resto tem caminho seguro)."""

import sqlite3

from lampdesk import winsys


def _db(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE NotificationHandler (RecordId INTEGER PRIMARY KEY, PrimaryId TEXT)")
    con.execute("CREATE TABLE Notification (Id INTEGER PRIMARY KEY, HandlerId INTEGER, Type TEXT, Payload BLOB)")
    con.execute("INSERT INTO NotificationHandler VALUES (1, 'com.squirrel.Discord.Discord')")
    con.execute("INSERT INTO Notification VALUES (1, 1, 'toast', ?)", (b"<toast><text>antiga</text></toast>",))
    con.commit()
    return con


def test_notification_reader_only_returns_new_toasts(tmp_path):
    path = tmp_path / "wpndatabase.db"
    con = _db(path)
    reader = winsys.NotificationReader(path)
    assert reader.poll() == []  # primeira leitura só marca onde está (não dispara pelo histórico)
    con.execute("INSERT INTO Notification VALUES (2, 1, 'toast', ?)", ("<toast><text>Ana</text></toast>".encode(),))
    con.execute("INSERT INTO Notification VALUES (3, 1, 'tile', ?)", (b"<tile/>",))  # bloco do menu Iniciar: ignora
    con.commit()
    assert reader.poll() == [("com.squirrel.Discord.Discord", "<toast><text>Ana</text></toast>")]
    assert reader.poll() == []
    assert reader.error == ""


def test_notification_reader_missing_db(tmp_path):
    reader = winsys.NotificationReader(tmp_path / "nao-existe.db")
    assert reader.poll() == [] and reader.error == "missing"


def test_safe_defaults_outside_windows(monkeypatch):
    monkeypatch.setattr(winsys, "WINDOWS", False)
    assert winsys.is_locked() is False
    assert winsys.idle_seconds() == 0.0
    assert winsys.foreground() == ("", False)
    assert winsys.media_now() is None
    assert not winsys.media_available()
    t = winsys.HotkeyThread({1: (2, ord("L"))}, lambda _h: None)
    t.start()
    t.join(1)
    assert t.failed == [1]
