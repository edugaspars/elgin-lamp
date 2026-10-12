import re
from pathlib import Path

from elgin_lamp import geo
from elgin_lamp.i18n import STRINGS

PKG = Path(__file__).resolve().parents[1] / "elgin_lamp"


def test_languages_have_same_keys():
    assert set(STRINGS["pt"]) == set(STRINGS["en"])


def test_every_used_key_exists():
    used = set()
    for f in PKG.rglob("*.py"):
        used |= set(re.findall(r"""\btr\(\s*["']([a-z_.]+)["']""", f.read_text(encoding="utf-8")))
    # chaves montadas dinamicamente
    used |= {f"general.gps_{k}" for k in ("denied", "unknown", "unsupported")}
    missing = sorted(k for k in used if k not in STRINGS["pt"])
    assert not missing, missing


def test_placeholders_match():
    for key, text in STRINGS["pt"].items():
        assert set(re.findall(r"{(\w+)}", text)) == set(re.findall(r"{(\w+)}", STRINGS["en"][key])), key


def test_days_have_seven_entries():
    for lang in STRINGS:
        assert len(STRINGS[lang]["days.short"].split(",")) == 7


def test_city_search_ignores_accents():
    assert geo.search("sao paulo")[0][0] == "São Paulo - SP"


def test_parse_coords():
    assert geo.parse_coords("-23.55, -46.63") == (-23.55, -46.63)
    assert geo.parse_coords("abc") is None
    assert geo.parse_coords("100, 0") is None
