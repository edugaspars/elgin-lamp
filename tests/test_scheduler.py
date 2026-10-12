import datetime as dt

from lampdesk import scheduler
from lampdesk.storage import Location, Routine

TZ = dt.timezone(dt.timedelta(hours=-3))
SP = Location("São Paulo - SP", -23.5505, -46.6333)


def at(y, m, d, hh, mm):
    return dt.datetime(y, m, d, hh, mm, tzinfo=TZ)


def test_fixed_time_fires_once():
    r = Routine("Acordar", time="07:00", days=list(range(7)))
    fired = {}
    assert scheduler.due([r], at(2026, 10, 12, 6, 59), SP, fired) == []
    assert scheduler.due([r], at(2026, 10, 12, 7, 0), SP, fired) == [r]
    assert scheduler.due([r], at(2026, 10, 12, 7, 1), SP, fired) == []  # não repete
    assert scheduler.due([r], at(2026, 10, 13, 7, 0), SP, fired) == [r]  # dia seguinte


def test_grace_period_after_sleep():
    r = Routine("Acordar", time="07:00")
    assert scheduler.due([r], at(2026, 10, 12, 7, 9), SP, {}) == [r]
    assert scheduler.due([r], at(2026, 10, 12, 7, 30), SP, {}) == []


def test_weekday_filter():
    r = Routine("Semana", time="08:00", days=[0, 1, 2, 3, 4])
    assert dt.date(2026, 10, 17).weekday() == 5  # sábado
    assert scheduler.due([r], at(2026, 10, 17, 8, 0), SP, {}) == []
    assert scheduler.due([r], at(2026, 10, 16, 8, 0), SP, {}) == [r]


def test_disabled_routine_never_fires():
    r = Routine("Off", time="08:00", enabled=False)
    assert scheduler.due([r], at(2026, 10, 12, 8, 0), SP, {}) == []


def test_sunset_with_offset():
    r = Routine("Anoitecer", trigger="sunset", offset_min=-15)
    when = scheduler.occurrence(r, dt.date(2026, 10, 12), SP, TZ)
    # pôr do sol em São Paulo em outubro: por volta de 18h10
    assert 17 <= when.hour <= 18
    assert scheduler.due([r], when, SP, {}) == [r]


def test_sun_trigger_without_location_is_skipped():
    r = Routine("Nascer", trigger="sunrise")
    assert scheduler.occurrence(r, dt.date(2026, 10, 12), Location(), TZ) is None


def test_next_occurrence():
    r = Routine("Noite", time="22:00", days=[6])  # domingo
    nxt = scheduler.next_occurrence(r, at(2026, 10, 12, 12, 0), SP)  # segunda
    assert nxt.weekday() == 6 and nxt.hour == 22


def test_invalid_time_is_ignored():
    r = Routine("Ruim", time="25:99")
    assert scheduler.due([r], at(2026, 10, 12, 8, 0), SP, {}) == []
