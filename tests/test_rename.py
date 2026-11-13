import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import store  # noqa: E402


@pytest.fixture(autouse=True)
def no_home_env(monkeypatch):
    # other test files set a home folder with an autouse fixture;
    # these tests must not inherit it (or a developer's real setting).
    for k in store.HOME_ENVS:
        monkeypatch.delenv(k, raising=False)


def test_data_dir_sesdefteri_home_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("MEETTRANSCRIBER_HOME", str(tmp_path / "oldest_home"))
    monkeypatch.setenv("KATIP_HOME", str(tmp_path / "katip_home"))
    monkeypatch.setenv("SESDEFTERI_HOME", str(tmp_path / "home"))
    assert store.data_dir() == tmp_path / "home"
    assert (tmp_path / "home").is_dir()


def test_data_dir_older_home_variables_still_honoured(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("MEETTRANSCRIBER_HOME", str(tmp_path / "oldest_home"))
    assert store.data_dir() == tmp_path / "oldest_home"
    monkeypatch.setenv("KATIP_HOME", str(tmp_path / "katip_home"))
    assert store.data_dir() == tmp_path / "katip_home"


def test_data_dir_defaults_to_sesdefteri(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    d = store.data_dir()
    if os.name == "nt":
        assert d == tmp_path / "appdata" / "SesDefteri"
    else:
        assert d.name == "SesDefteri"
    assert d.is_dir()


def test_migrate_renames_the_katip_folder(tmp_path, monkeypatch):
    appdata = tmp_path / "appdata"
    old = appdata / "Katip"
    (old / "jobs" / "abc").mkdir(parents=True)
    (old / "jobs" / "abc" / "transcript.json").write_text("{}", "utf-8")
    (old / "models" / "big.bin").parent.mkdir(parents=True)
    (old / "models" / "big.bin").write_bytes(b"m")
    monkeypatch.setenv("APPDATA", str(appdata))

    assert store.migrate_old_data() is True
    new = appdata / "SesDefteri"
    assert (new / "jobs" / "abc" / "transcript.json").read_text("utf-8") == "{}"
    assert (new / "models" / "big.bin").read_bytes() == b"m"
    assert not old.exists()  # moved, not copied
    assert store.migrate_old_data() is False  # only once


def test_migrate_prefers_katip_over_the_oldest_folder(tmp_path, monkeypatch):
    appdata = tmp_path / "appdata"
    (appdata / "Katip").mkdir(parents=True)
    (appdata / "Katip" / "which.txt").write_text("katip", "utf-8")
    (appdata / "MeetTranscriber").mkdir()
    (appdata / "MeetTranscriber" / "which.txt").write_text("oldest", "utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))

    assert store.migrate_old_data() is True
    assert (appdata / "SesDefteri" / "which.txt").read_text("utf-8") == "katip"
    assert (appdata / "MeetTranscriber" / "which.txt").exists()


def test_migrate_copies_katip_when_it_cannot_be_renamed(tmp_path, monkeypatch):
    appdata = tmp_path / "appdata"
    old = appdata / "Katip"
    (old / "webview").mkdir(parents=True)
    (old / "webview" / "cache.bin").write_bytes(b"x")
    (old / "keep.txt").write_text("keep", "utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))
    real_rename = Path.rename

    def busy(self, target):
        if self == old:
            raise PermissionError("in use")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", busy)
    assert store.migrate_old_data() is True
    new = appdata / "SesDefteri"
    assert (new / "keep.txt").read_text("utf-8") == "keep"
    assert not (new / "webview").exists()
    assert (old / "keep.txt").exists()  # the copy leaves the old folder as it was


def test_migrate_copies_the_oldest_folder_and_keeps_it(tmp_path, monkeypatch):
    appdata = tmp_path / "appdata"
    old = appdata / "MeetTranscriber"
    (old / "jobs" / "abc").mkdir(parents=True)
    (old / "jobs" / "abc" / "transcript.json").write_text("{}", "utf-8")
    (old / "webview").mkdir()
    (old / "webview" / "cache.bin").write_bytes(b"x")
    monkeypatch.setenv("APPDATA", str(appdata))

    assert store.migrate_old_data() is True
    new = appdata / "SesDefteri"
    assert (new / "jobs" / "abc" / "transcript.json").read_text("utf-8") == "{}"
    assert not (new / "webview").exists()
    assert not (appdata / "SesDefteri.tmp").exists()
    assert (old / "jobs" / "abc" / "transcript.json").exists()
    assert store.migrate_old_data() is False


def test_migrate_does_nothing_when_new_folder_exists(tmp_path, monkeypatch):
    appdata = tmp_path / "appdata"
    (appdata / "Katip").mkdir(parents=True)
    (appdata / "Katip" / "old.txt").write_text("old", "utf-8")
    new = appdata / "SesDefteri"
    new.mkdir()
    (new / "new.txt").write_text("new", "utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))

    assert store.migrate_old_data() is False
    assert sorted(p.name for p in new.iterdir()) == ["new.txt"]
    assert (appdata / "Katip" / "old.txt").exists()


def test_migrate_without_old_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    assert store.migrate_old_data() is False
    assert not (tmp_path / "appdata" / "SesDefteri").exists()


def test_migrate_removes_leftover_tmp(tmp_path, monkeypatch):
    appdata = tmp_path / "appdata"
    old = appdata / "MeetTranscriber"
    old.mkdir(parents=True)
    (old / "a.txt").write_text("a", "utf-8")
    tmp = appdata / "SesDefteri.tmp"
    tmp.mkdir()
    (tmp / "stale.txt").write_text("stale", "utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))

    assert store.migrate_old_data() is True
    assert not tmp.exists()
    assert (appdata / "SesDefteri" / "a.txt").read_text("utf-8") == "a"
    assert not (appdata / "SesDefteri" / "stale.txt").exists()


@pytest.mark.parametrize("env", ["SESDEFTERI_HOME", "KATIP_HOME", "MEETTRANSCRIBER_HOME"])
def test_migrate_skipped_when_a_home_variable_is_set(tmp_path, monkeypatch, env):
    appdata = tmp_path / "appdata"
    (appdata / "Katip").mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv(env, str(tmp_path / "elsewhere"))
    assert store.migrate_old_data() is False
    assert (appdata / "Katip").exists()
    assert not (appdata / "SesDefteri").exists()
