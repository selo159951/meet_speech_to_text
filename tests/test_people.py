import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import people, store  # noqa: E402

SR = 16000


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MEETTRANSCRIBER_HOME", str(tmp_path))
    monkeypatch.setattr(people, "_lang", lambda: "en")
    monkeypatch.setattr(people, "_model_name", lambda: "fake")
    return tmp_path


def unit(v):
    v = np.asarray(v, np.float32)
    return v / np.linalg.norm(v)


def voice(i, dim=16, noise=0.0, seed=0):
    """A fake voice print: voice i points along axis i (plus noise)."""
    v = np.zeros(dim, np.float32); v[i] = 1
    v += noise * np.random.default_rng(seed).normal(size=dim).astype(np.float32)
    return unit(v)


def fake_windows(monkeypatch, vec, n=12):
    monkeypatch.setattr(people, "window_embeddings", lambda speech, max_seconds=people.MAX_USED:
                        np.stack([vec] * min(n, int(len(speech) / SR / people.WIN))))


def tone(seconds, amp=0.3):
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


# ---------------- storage ----------------
def test_person_storage(home):
    p = people.create_person("  Selim ")
    assert p["name"] == "Selim" and p["seconds"] == 0 and not p["has_voice"]
    assert (home / "people" / p["id"] / "person.json").exists()
    assert people.rename_person(p["id"], "Selim O.")["name"] == "Selim O."
    assert [x["name"] for x in people.list_people()] == ["Selim O."]
    people.delete_person(p["id"])
    assert people.list_people() == []
    with pytest.raises(ValueError):
        people.create_person("  ")
    with pytest.raises(ValueError):
        people.rename_person("nope", "x")


# ---------------- sample length rules ----------------
def test_sample_too_short_names_the_seconds(monkeypatch):
    p = people.create_person("A")
    fake_windows(monkeypatch, voice(0))
    with pytest.raises(ValueError, match=r"Only 20 s"):
        people._enroll(p["id"], tone(20), "test", people.MIN_SPEECH)
    assert people.get_person(p["id"])["samples"] == 0


def test_sample_accepted_and_capped(monkeypatch, home):
    p = people.create_person("A")
    fake_windows(monkeypatch, voice(0))
    r = people._enroll(p["id"], tone(90), "test", people.MIN_SPEECH)
    assert r["seconds"] == people.MAX_USED and r["has_voice"] and not r["weak"]
    wavs = list((home / "people" / p["id"] / "samples").glob("*.wav"))
    assert len(wavs) == 1
    saved = json.loads((home / "people" / p["id"] / "person.json").read_text("utf-8"))
    assert saved["samples"][0]["seconds"] == 60.0 and len(saved["embedding"]) == 16


def test_weak_sample_is_marked(monkeypatch):
    p = people.create_person("A")
    fake_windows(monkeypatch, voice(0))
    r = people._enroll(p["id"], tone(12), "job:x:0", 3.0)  # allowed for speakers from a recording
    assert r["weak"] and r["seconds"] == 12.0
    r = people._enroll(p["id"], tone(30), "file", people.MIN_SPEECH)
    assert not r["weak"] and r["samples"] == 2


def test_person_embedding_is_mean_of_samples(monkeypatch):
    p = people.create_person("A")
    fake_windows(monkeypatch, voice(0))
    people._enroll(p["id"], tone(40), "a", 30)
    fake_windows(monkeypatch, voice(1))
    people._enroll(p["id"], tone(40), "b", 30)
    e = np.array(people._read(p["id"])["embedding"])
    assert abs(np.linalg.norm(e) - 1) < 1e-4 and abs(e[0] - e[1]) < 1e-3


# ---------------- quality ----------------
def test_quality_flags():
    E = np.stack([voice(0)] * 8)
    assert people.quality(tone(10, 0.3), E) == []
    assert "too_quiet" in people.quality(tone(10, 0.0005), E)
    loud = np.clip(tone(10, 3.0), -1, 1)
    assert "clipping" in people.quality(loud, E)


def test_multiple_voices_detected():
    two = np.stack([voice(0, noise=0.1, seed=i) for i in range(6)] + [voice(1, noise=0.1, seed=9 + i) for i in range(5)])
    one = np.stack([voice(0, noise=0.1, seed=i) for i in range(11)])
    assert people._multiple_voices(two) and not people._multiple_voices(one)
    mostly = np.stack([voice(0, noise=0.1, seed=i) for i in range(11)] + [voice(1)])
    assert not people._multiple_voices(mostly)  # one stray window is not a second speaker


# ---------------- assignment ----------------
def test_assign_thresholds():
    m, s = people.assign({0: {"a": 0.80, "b": 0.10}, 1: {"a": 0.20, "b": 0.42}})
    assert m == {0: ("a", 0.80)} and s == {1: ("b", 0.42)}
    m, s = people.assign({0: {"a": 0.30}})
    assert m == {} and s == {}


def test_assign_one_person_per_speaker():
    # both speakers like "a" best; the pair maximising the total gives speaker 1 -> a
    m, s = people.assign({0: {"a": 0.70, "b": 0.60}, 1: {"a": 0.90, "b": 0.10}})
    assert m == {1: ("a", 0.90), 0: ("b", 0.60)}
    # nobody is used twice even when only one person exists
    m, s = people.assign({0: {"a": 0.60}, 1: {"a": 0.80}})
    assert m == {1: ("a", 0.80)} and s == {}


def test_match_prints_uses_stored_people(monkeypatch):
    for i, name in enumerate(["Selim", "Umut"]):
        p = people.create_person(name)
        fake_windows(monkeypatch, voice(i))
        people._enroll(p["id"], tone(40), "t", 30)
    prints = {0: voice(1, noise=0.3, seed=1), 1: voice(5)}
    r = people.match_prints(prints)
    assert r["matches"]["0"]["name"] == "Umut" and r["matches"]["0"]["score"] > 0.8
    assert "1" not in r["matches"] and "1" not in r["suggestions"]


# ---------------- job integration ----------------
def test_apply_to_job_without_people_is_free(monkeypatch):
    monkeypatch.setattr(people, "speaker_prints", lambda *a: pytest.fail("must not compute"))
    sp = {"0": "Speaker 1"}
    assert people.apply_to_job(np.zeros(10, np.float32), [], sp) == {"voice_matches": {}, "voice_suggestions": {}}
    assert sp == {"0": "Speaker 1"}


def make_job(segments, speakers):
    jid = store.create_job("x.m4a")
    store.update_job(jid, status="done", segments=segments, speakers=speakers)
    return jid


def test_apply_to_job_renames_and_keeps_user_labels(monkeypatch):
    for i, name in enumerate(["Selim", "Umut", "Ece"]):
        p = people.create_person(name)
        fake_windows(monkeypatch, voice(i))
        people._enroll(p["id"], tone(40), "t", 30)
    prints = {0: voice(0, noise=0.2), 1: voice(1, noise=0.1, seed=3), 2: voice(2, noise=0.2, seed=4)}
    monkeypatch.setattr(people, "speaker_prints", lambda samples, segs: prints)
    sp = {"0": "Speaker 1", "1": "Speaker 2", "2": "Speaker 3"}
    out = people.apply_to_job(np.zeros(10, np.float32), [], sp, keep={"2": "Boss"})
    assert sp == {"0": "Selim", "1": "Umut", "2": "Speaker 3"}  # the user's own label is not touched
    assert set(out["voice_matches"]) == {"0", "1", "2"} and out["voice_suggestions"] == {}


def test_accept_suggestion(monkeypatch):
    p = people.create_person("Selim")
    jid = make_job([{"start": 0, "end": 1, "speaker": 0}], {"0": "Speaker 1"})
    store.update_job(jid, voice_suggestions={"0": {"person_id": p["id"], "name": "Selim", "score": 0.4}})
    job = people.accept_suggestion(jid, 0, p["id"])
    assert job["speakers"]["0"] == "Selim" and job["voice_matches"]["0"]["person_id"] == p["id"]
    assert job["voice_suggestions"] == {}


def test_rematch_job_keeps_user_labels_replaces_old_matches(monkeypatch):
    from backend import audio

    p = people.create_person("Selim")
    fake_windows(monkeypatch, voice(0))
    people._enroll(p["id"], tone(40), "t", 30)
    segs = [{"start": 0, "end": 5, "speaker": 0}, {"start": 5, "end": 9, "speaker": 1}]
    jid = make_job(segs, {"0": "Speaker 1", "1": "Typed by user"})
    monkeypatch.setattr(audio, "decode", lambda path: (np.zeros(SR, np.float32), 1.0))
    monkeypatch.setattr(people, "speaker_prints", lambda s, g: {0: voice(0), 1: voice(3)})
    job = people.rematch_job(jid)
    assert job["speakers"] == {"0": "Selim", "1": "Typed by user"}
    assert job["voice_matches"]["0"]["name"] == "Selim"


def test_bridge_exposes_people_methods():
    from backend.bridge import Api

    for m in ("list_people", "create_person", "rename_person", "delete_person", "add_person_sample_file",
              "start_recording", "recording_status", "stop_recording", "cancel_recording",
              "save_speaker_as_person", "rematch_job", "accept_suggestion"):
        assert callable(getattr(Api, m))


def test_recording_status_when_idle():
    assert people.recording_status()["active"] is False
    assert people.cancel_recording() == {"ok": True}
    with pytest.raises(ValueError):
        people.stop_recording(None, "x")
