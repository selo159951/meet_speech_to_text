import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import store  # noqa: E402


@pytest.fixture(autouse=True)
def no_home_env(monkeypatch):
    # tests/test_core.py has an autouse fixture setting MEETTRANSCRIBER_HOME;
    # these tests must not inherit it (or a developer's real setting).
    monkeypatch.delenv("KATIP_HOME", raising=False)
    monkeypatch.delenv("MEETTRANSCRIBER_HOME", raising=False)


def test_data_dir_katip_home_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("MEETTRANSCRIBER_HOME", str(tmp_path / "old_home"))
    monkeypatch.setenv("KATIP_HOME", str(tmp_path / "katip_home"))
    assert store.data_dir() == tmp_path / "katip_home"
    assert (tmp_path / "katip_home").is_dir()


def test_data_dir_meettranscriber_home_still_honoured(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("MEETTRANSCRIBER_HOME", str(tmp_path / "old_home"))
    assert store.data_dir() == tmp_path / "old_home"


def test_data_dir_defaults_to_katip(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    d = store.data_dir()
    if os.name == "nt":
        assert d == tmp_path / "appdata" / "Katip"
    else:
        assert d.name == "Katip"
    assert d.is_dir()


def test_migrate_copies_old_data_and_keeps_it(tmp_path, monkeypatch):
    appdata = tmp_path / "appdata"
    old = appdata / "MeetTranscriber"
    (old / "jobs" / "abc").mkdir(parents=True)
    (old / "jobs" / "abc" / "transcript.json").write_text("{}", "utf-8")
    (old / "app.log").write_text("log", "utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))

    assert store.migrate_old_data() is True
    new = appdata / "Katip"
    assert (new / "jobs" / "abc" / "transcript.json").read_text("utf-8") == "{}"
    assert (new / "app.log").read_text("utf-8") == "log"
    assert not (appdata / "Katip.tmp").exists()
    # the old folder is never deleted or changed
    assert (old / "jobs" / "abc" / "transcript.json").exists()
    assert (old / "app.log").read_text("utf-8") == "log"
    # and it only happens once
    assert store.migrate_old_data() is False


def test_migrate_does_nothing_when_new_folder_exists(tmp_path, monkeypatch):
    appdata = tmp_path / "appdata"
    old = appdata / "MeetTranscriber"
    old.mkdir(parents=True)
    (old / "old.txt").write_text("old", "utf-8")
    new = appdata / "Katip"
    new.mkdir()
    (new / "new.txt").write_text("new", "utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))

    assert store.migrate_old_data() is False
    assert sorted(p.name for p in new.iterdir()) == ["new.txt"]


def test_migrate_without_old_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    assert store.migrate_old_data() is False
    assert not (tmp_path / "appdata" / "Katip").exists()


def test_migrate_skips_webview_folder(tmp_path, monkeypatch):
    appdata = tmp_path / "appdata"
    old = appdata / "MeetTranscriber"
    (old / "webview").mkdir(parents=True)
    (old / "webview" / "cache.bin").write_bytes(b"x")
    (old / "keep.txt").write_text("keep", "utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))

    assert store.migrate_old_data() is True
    new = appdata / "Katip"
    assert (new / "keep.txt").read_text("utf-8") == "keep"
    assert not (new / "webview").exists()
    assert (old / "webview" / "cache.bin").exists()


def test_migrate_removes_leftover_tmp(tmp_path, monkeypatch):
    appdata = tmp_path / "appdata"
    old = appdata / "MeetTranscriber"
    old.mkdir(parents=True)
    (old / "a.txt").write_text("a", "utf-8")
    tmp = appdata / "Katip.tmp"
    tmp.mkdir()
    (tmp / "stale.txt").write_text("stale", "utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))

    assert store.migrate_old_data() is True
    assert not tmp.exists()
    assert (appdata / "Katip" / "a.txt").read_text("utf-8") == "a"
    assert not (appdata / "Katip" / "stale.txt").exists()


def test_migrate_skipped_when_home_env_is_set(tmp_path, monkeypatch):
    appdata = tmp_path / "appdata"
    (appdata / "MeetTranscriber").mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("KATIP_HOME", str(tmp_path / "elsewhere"))
    assert store.migrate_old_data() is False
    assert not (appdata / "Katip").exists()
