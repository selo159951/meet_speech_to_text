"""First-run tour: persisted flags, strings in both languages, wiring, and no emoji or symbols."""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FRONT = ROOT / "frontend"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MEETTRANSCRIBER_HOME", str(tmp_path))


def _blocks():
    src = (FRONT / "i18n.js").read_text(encoding="utf-8")
    en_at, tr_at = src.index("\n  en: {"), src.index("\n  tr: {")
    return src[en_at:tr_at], src[tr_at:]


def _tour_strings(block):
    return dict(re.findall(r'\b(tour_\w+)\s*:\s*"((?:[^"\\]|\\.)*)"', block))


def test_bridge_flags_default_false_and_round_trip():
    from backend.bridge import Api

    api = Api()
    s = api.get_settings()
    assert s["tour_home_done"] is False and s["tour_job_done"] is False
    s = api.set_settings({"tour_home_done": True})
    assert s["tour_home_done"] is True and s["tour_job_done"] is False
    s = api.set_settings({"tour_job_done": True})
    assert s["tour_home_done"] is True and s["tour_job_done"] is True
    s = api.set_settings({"tour_job_done": False})
    assert s["tour_home_done"] is True and s["tour_job_done"] is False
    assert Api().get_settings()["tour_home_done"] is True  # survives a new Api (a restart)


def test_tour_keys_in_both_languages():
    en, tr = (_tour_strings(b) for b in _blocks())
    assert en and set(en) == set(tr)
    for k in ("tour_back", "tour_next", "tour_skip", "tour_finish", "tour_restart", "tour_step"):
        assert k in en
    js = (FRONT / "tour.js").read_text(encoding="utf-8")
    for k in re.findall(r'k: "(tour_\w+)"', js):
        assert k + "_t" in en and k + "_b" in en, k


def test_app_name_not_hard_coded():
    for block in _blocks():
        for k, v in _tour_strings(block).items():
            assert "Kâtip" not in v and "Katip" not in v, k


def test_index_includes_tour_and_restart_button():
    html = (FRONT / "index.html").read_text(encoding="utf-8")
    assert '<script src="tour.js"></script>' in html
    assert html.index("analysis.js") < html.index("tour.js")
    assert 'id="tourRestart"' in html


def _bad_chars(text):
    return [c for c in text if 0x2190 <= ord(c) <= 0x2BFF or 0x1F000 <= ord(c) <= 0x1FAFF or 0x2600 <= ord(c) <= 0x27BF]


def test_no_emoji_or_symbols():
    assert _bad_chars((FRONT / "tour.js").read_text(encoding="utf-8")) == []
    for block in _blocks():
        for k, v in _tour_strings(block).items():
            assert _bad_chars(v) == [], k
