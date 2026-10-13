import datetime as dt

from lampdesk import rules as R
from lampdesk.storage import Config, Group, Lamp, Location, Rule

TZ = dt.timezone(dt.timedelta(hours=-3))
SP = Location("São Paulo - SP", -23.5505, -46.6333)


def at(hh, mm, day=12):
    return dt.datetime(2026, 10, day, hh, mm, tzinfo=TZ)  # 12/10/2026 é segunda


def test_time_window_crosses_midnight():
    assert R.in_window(at(23, 30), "22:00", "06:00")
    assert R.in_window(at(5, 59), "22:00", "06:00")
    assert not R.in_window(at(12, 0), "22:00", "06:00")
    assert R.in_window(at(12, 0), "09:00", "18:00")
    assert not R.in_window(at(18, 0), "09:00", "18:00")
    assert R.in_window(at(3, 0), "", "")  # sem janela: qualquer hora


def test_conditions():
    r = Rule("x", days=[0], window_from="08:00", window_to="20:00")
    assert R.conditions_ok(r, at(10, 0), SP)
    assert not R.conditions_ok(r, at(21, 0), SP)
    assert not R.conditions_ok(r, at(10, 0, day=13), SP)  # terça
    r.enabled = False
    assert not R.conditions_ok(r, at(10, 0), SP)


def test_only_dark_uses_sunset():
    r = Rule("x", only_dark=True)
    assert not R.conditions_ok(r, at(12, 0), SP)
    assert R.conditions_ok(r, at(22, 0), SP)
    assert R.conditions_ok(r, at(22, 0), Location())  # sem localização: 18h–6h


def test_mode_condition():
    r = Rule("x", mode="discord")
    assert not R.conditions_ok(r, at(12, 0), SP, modes=set())
    assert R.conditions_ok(r, at(12, 0), SP, modes={"discord"})


def test_vacation_pause():
    assert R.paused("2026-10-20", dt.date(2026, 10, 20))
    assert not R.paused("2026-10-20", dt.date(2026, 10, 21))
    assert not R.paused("", dt.date(2026, 10, 21))
    assert not R.paused("lixo", dt.date(2026, 10, 21))


def test_notification_matching():
    from lampdesk.automation import CALL_WORDS
    msg = Rule("msg", trigger="notification", apps=["discord"], exclude=CALL_WORDS)
    call = Rule("call", trigger="notification", apps=["discord"], text=CALL_WORDS)
    app = "com.squirrel.Discord.Discord"
    assert R.notification_matches(msg, app, "Ana · oi, tudo bem?")
    assert not R.notification_matches(call, app, "Ana · oi, tudo bem?")
    assert R.notification_matches(call, app, "Ana está te ligando")
    assert not R.notification_matches(msg, app, "Ana está te ligando")
    assert not R.notification_matches(msg, "Microsoft.Teams", "oi")


def test_toast_text():
    xml = ('<toast><visual><binding template="ToastGeneric"><text>Ana</text>'
           '<text hint-maxLines="2">oi &amp; tchau</text></binding></visual></toast>')
    assert R.toast_text(xml) == "Ana · oi & tchau"
    assert R.toast_text("") == ""


def test_circadian_curve():
    night = R.circadian_look(at(2, 0), SP, night_brightness=30)
    noon = R.circadian_look(at(12, 30), SP, night_brightness=30)
    evening = R.circadian_look(at(20, 30), SP, night_brightness=30)
    assert night[0] < 15 and night[1] == 30          # quente e fraca de madrugada
    assert noon[0] > 85 and noon[1] == 100           # fria e forte ao meio-dia
    assert evening[0] < noon[0] and evening[1] < noon[1]
    morning = [R.circadian_level(at(h, 0), SP) for h in range(5, 12)]
    assert morning == sorted(morning)                # a manhã só esfria, sem saltos


def test_vivid_color():
    red = [(220, 30, 30)] * 50 + [(20, 20, 20)] * 50 + [(200, 200, 200)] * 50
    r, g, b = R.vivid_color(red)
    assert r == 255 and g < 100 and b < 100
    assert R.vivid_color([(30, 30, 30)] * 100) is None  # sem cor: mantém a anterior
    assert R.vivid_color([]) is None


def test_parse_hotkey():
    assert R.parse_hotkey("Ctrl+Alt+L") == (R.MOD_CONTROL | R.MOD_ALT, ord("L"))
    assert R.parse_hotkey("Meta+Shift+F5") == (R.MOD_WIN | R.MOD_SHIFT, 0x74)
    assert R.parse_hotkey("Ctrl++") == (R.MOD_CONTROL, 0xBB)
    assert R.parse_hotkey("") is None
    assert R.parse_hotkey("Ctrl+Alt") is None
    assert R.parse_hotkey("Ctrl+Nada") is None


def test_groups_resolve_and_forget():
    cfg = Config(lamps=[Lamp("A", "1", "192.0.2.1", "k", id="a"), Lamp("B", "2", "192.0.2.2", "k", id="b"),
                        Lamp("C", "3", "192.0.2.3", "k", id="c")])
    cfg.groups.append(Group("Escritório", ["a", "b"], id="g"))
    cfg.rules.append(Rule("r", targets=["g"]))
    assert [l.id for l in cfg.resolve_targets(["g"])] == ["a", "b"]
    assert [l.id for l in cfg.resolve_targets(["g", "c"])] == ["a", "b", "c"]
    assert cfg.target_name(["g"], "Todas") == "Escritório"
    cfg.forget("a")
    assert cfg.groups[0].members == ["b"]
    cfg.groups.clear()
    cfg.forget("g")
    assert cfg.rules[0].targets == ["*"]


def test_new_config_fields_roundtrip():
    cfg = Config()
    cfg.groups.append(Group("Escritório", ["a"]))
    cfg.rules.append(Rule("r", trigger="hotkey", hotkey="Ctrl+Alt+L", action="toggle"))
    cfg.settings.discord_mode = True
    cfg.settings.circadian.enabled = True
    cfg.settings.music.source = "screen"
    cfg.settings.pomodoro.focus_min = 50
    cfg.settings.pause_until = "2026-12-24"
    back = Config.from_dict(cfg.to_dict())
    assert back.groups[0].members == ["a"]
    assert back.rules[0].hotkey == "Ctrl+Alt+L"
    assert back.settings.discord_mode and back.settings.circadian.enabled
    assert back.settings.music.source == "screen"
    assert back.settings.pomodoro.focus_min == 50
    assert back.settings.pause_until == "2026-12-24"
    old = Config.from_dict({"lamps": [], "settings": {"theme": "light"}})  # configuração de versões antigas
    assert old.rules == [] and old.groups == [] and not old.settings.rules_seeded
    assert Config.from_dict({"rules": [{"name": "x", "campo_novo": 1}]}).rules[0].name == "x"


def test_screen_mood():
    colourful = [(30, 200, 60)] * 60 + [(10, 10, 10)] * 40
    kind, rgb = R.screen_mood(colourful)
    assert kind == "colour" and rgb[1] == 255
    assert R.screen_mood([(250, 250, 255)] * 100)[0] == "white"
    cold = R.screen_mood([(210, 225, 255)] * 100)
    warm = R.screen_mood([(255, 235, 200)] * 100)
    assert cold[0] == warm[0] == "white" and cold[1] > 50 > warm[1]
    assert R.screen_mood([(15, 15, 20)] * 100) == ("dark", 0)       # cena escura / créditos
    assert R.screen_mood([(110, 110, 110)] * 100) == ("dark", 0)    # menu cinza
    logo = [(255, 0, 0)] * 3 + [(120, 120, 120)] * 97                # logo pequeno num menu cinza
    assert R.screen_mood(logo)[0] == "dark"
    assert R.screen_mood([]) == ("dark", 0)


def test_room_target_resolves_to_this_pcs_room():
    from lampdesk.storage import ROOM
    cfg = Config(lamps=[Lamp("A", "1", "192.0.2.1", "k", id="a"), Lamp("B", "2", "192.0.2.2", "k", id="b")])
    cfg.groups.append(Group("Escritório", ["a"], id="g"))
    assert [l.id for l in cfg.resolve_targets([ROOM])] == ["a", "b"]  # sem ambiente: todas
    cfg.settings.room = ["g"]
    assert [l.id for l in cfg.resolve_targets([ROOM])] == ["a"]
    assert cfg.target_name([ROOM], "Todas", "Ambiente deste PC") == "Ambiente deste PC (Escritório)"
    assert Rule("r").targets == [ROOM]  # automações novas nascem no ambiente
    cfg.forget("g")
    assert cfg.settings.room == ["*"]
    back = Config.from_dict({"settings": {"room": ["g", ROOM]}})
    assert back.settings.room == ["g"]  # o ambiente nunca aponta para si mesmo
