import re
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import analysis, bridge, store  # noqa: E402

DATA = Path(__file__).parent / "data" / "meeting_tr.txt"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MEETTRANSCRIBER_HOME", str(tmp_path))


def seg(i, spk, a, b, text):
    return {"id": i, "start": a, "end": b, "speaker": spk, "text_edited": text, "text_original": text, "words": []}


def make_job(segments, speakers=None, language="tr"):
    job_id = store.create_job("m.mp3")
    n = len({s["speaker"] for s in segments})
    speakers = speakers or {str(i): f"Speaker {i + 1}" for i in range(n)}
    store.update_job(job_id, status="done", segments=segments, speakers=speakers, language=language)
    return job_id


def hand_made():
    return [seg(1, 0, 0, 10, "Merhaba, başlayalım mı?"), seg(2, 0, 10, 40, "Bugün plan var."),
            seg(3, 1, 40, 50, "Tamam."), seg(4, 0, 50, 60, "Kim yapacak? Ne zaman?"),
            seg(5, 1, 60, 70, "Ben yaparım")]


def parse_meeting():
    out = []
    for ln in DATA.read_text("utf-8").splitlines():
        m = re.match(r"\[(\d+)\] \[(\d+):(\d+)-(\d+):(\d+)\] Konuşmacı (\d+): (.*)", ln)
        if m:
            i, a1, a2, b1, b2, spk, text = m.groups()
            out.append(seg(int(i), int(spk) - 1, int(a1) * 60 + int(a2), int(b1) * 60 + int(b2), text))
    return out


class Fake:
    def __init__(self, merge=None, notes=None):
        self.calls, self.merge, self.notes = [], merge, notes

    def __call__(self, prompt, schema=None, **kw):
        self.calls.append((prompt, schema, kw))
        if schema is analysis.MERGE_SCHEMA:
            return self.merge if self.merge is not None else {"summary": "ozet"}
        return self.notes if self.notes is not None else {"topics": [], "decisions": []}

    def count(self, schema):
        return sum(1 for c in self.calls if c[1] is schema)


# ---------- stats ----------
def test_stats_known_numbers():
    st = analysis.stats(hand_made(), {"0": "Ali", "1": "Veli"})
    assert st["duration"] == 70.0
    a, v = st["speakers"]
    assert (a["name"], a["seconds"], a["turns"], a["questions"], a["longest_turn"]) == ("Ali", 50.0, 2, 2, 40.0)
    assert (v["seconds"], v["turns"], v["questions"], v["words"]) == (20.0, 2, 0, 3)
    assert a["share"] == 0.714 and a["words"] == 10
    assert 0.8 < st["balance"] < 0.9


def test_stats_balance_edges():
    one = analysis.stats([seg(1, 0, 0, 5, "a")], {"0": "A"})
    assert one["balance"] == 1.0
    even = analysis.stats([seg(1, 0, 0, 5, "a"), seg(2, 1, 5, 10, "b")], {})
    assert even["balance"] == 1.0
    skew = analysis.stats([seg(1, 0, 0, 1000, "a"), seg(2, 1, 1000, 1001, "b")], {})
    assert skew["balance"] < 0.05


def test_stats_on_test_meeting():
    segs = parse_meeting()
    assert len(segs) == 76
    st = analysis.stats(segs, {"0": "A", "1": "B", "2": "C"})
    assert len(st["speakers"]) == 3
    assert sum(s["questions"] for s in st["speakers"]) == sum("?" in s["text_edited"] for s in segs)
    assert sum(s["turns"] for s in st["speakers"]) >= 3
    assert 0 < st["balance"] <= 1


# ---------- rendering and chunking ----------
def test_render_format():
    lines = analysis.render(hand_made(), {"0": "Ali", "1": "Veli"})
    assert lines[0] == "[1] [00:00-00:10] Ali: Merhaba, başlayalım mı?"


def test_chunking_never_splits_a_line():
    lines = [f"[{i}] [00:00-00:01] A: " + "kelime " * (10 + i) for i in range(60)]
    chunks = analysis.chunk_lines(lines, limit=200)
    assert [ln for c in chunks for ln in c] == lines
    assert len(chunks) > 3
    assert all(sum(len(x) // 3 + 1 for x in c[:-1]) <= 200 for c in chunks)
    assert analysis.chunk_lines(lines, limit=10**6) == [lines]
    assert analysis.chunk_lines(["x" * 900], limit=10) == [["x" * 900]]


# ---------- run ----------
def test_run_done_shape_and_files():
    jid = make_job(hand_made(), {"0": "Ali", "1": "Veli"})
    fake = Fake()
    a = analysis.run(jid, generate=fake)
    assert a["state"] == "done"
    assert fake.count(analysis.NOTES_SCHEMA) == 1 and fake.count(analysis.MERGE_SCHEMA) == 1
    assert "[1] [00:00-00:10] Ali:" in fake.calls[0][0]
    assert (store.job_path(jid) / "analysis.json").exists()
    assert (store.job_path(jid) / "analysis" / "parts" / "0.json").exists()
    s = analysis.status(jid)
    assert s["state"] == "done" and s["analysis"]["summary"] == "ozet" and "llm_ready" in s


def test_parts_reused_and_redone_when_text_changes(monkeypatch):
    monkeypatch.setattr(analysis, "CHUNK_TOKENS", 30)
    segs = [seg(i, i % 2, i, i + 1, "bu bir deneme cümlesi numara %d" % i) for i in range(1, 9)]
    jid = make_job(segs)
    f1 = Fake()
    analysis.run(jid, generate=f1)
    parts = f1.count(analysis.NOTES_SCHEMA)
    assert parts > 2
    f2 = Fake()
    analysis.run(jid, generate=f2)
    assert f2.count(analysis.NOTES_SCHEMA) == 0 and f2.count(analysis.MERGE_SCHEMA) == 1
    store.save_edits(jid, {8: "tamamen başka bir şey"})
    f3 = Fake()
    analysis.run(jid, generate=f3)
    assert 0 < f3.count(analysis.NOTES_SCHEMA) < parts


def test_long_meeting_digest_is_shortened(monkeypatch):
    notes = [{"topics": [{"title": "t", "summary": "s" * 500, "line": 1}], "decisions": [{"text": "d", "line": 1}],
              "questions": [{"asker": "A", "text": "q1", "answered": False, "line": 1},
                            {"asker": "A", "text": "q2", "answered": True, "line": 2}],
              "people": [{"name": "A", "did": "x" * 500, "got": "y" * 500}]}] * 4
    assert [q["text"] for q in analysis.collect(notes)["open_questions"]] == ["q1"] * 4
    long = analysis.digest(notes)
    monkeypatch.setattr(analysis, "MERGE_TOKENS", 200)
    short = analysis.digest(notes)
    assert len(short) < len(long) and '"d"' in short


def test_postprocess():
    jid = make_job(hand_made(), {"0": "Ali", "1": "Veli"})
    notes = {
        "topics": [{"title": "B", "summary": "", "line": 4}, {"title": "A", "summary": "x", "line": 1},
                   {"title": "bad", "summary": "", "line": 99}],
        "decisions": [{"text": "Plan.", "line": 2}, {"text": "plan", "line": 3}, {"text": "x", "line": 77}],
        "tasks": [{"owner": "veli", "task": "Yap", "due": "yarın", "line": 5},
                  {"owner": "Konuşmacı 1", "task": "Bak", "due": "", "line": 4},
                  {"owner": "Zeynep", "task": "Başka", "due": "", "line": 5},
                  {"owner": "Ali", "task": "Hatalı", "due": "", "line": 500}],
        "questions": [{"asker": "Speaker 2", "text": "Ne zaman?", "answered": False, "line": 4},
                      {"asker": "Ali", "text": "Başlayalım mı?", "answered": True, "line": 1}],
    }
    merge = {
        "summary": " s ",
        "people": [{"name": "VELİ", "contribution": "c", "gained": "g", "evidence": [3, 999, 5]}],
        "score": {"decisions": 150, "focus": -5, "repetition": 60, "comment": "k", "tips": ["a", "b"]},
    }
    a = analysis.run(jid, generate=Fake(merge=merge, notes=notes))
    r = analysis.status(jid)["analysis"]
    assert a["state"] == "done"
    assert [t["line"] for t in r["topics"]] == [1, 4]
    assert r["topics"][0]["start"] == 0 and r["topics"][0]["end"] == 50 and r["topics"][1]["end"] == 70
    assert [d["line"] for d in r["decisions"]] == [2]
    assert [(t["owner"], t["line"]) for t in r["tasks"]] == [(1, 5), (0, 4), (None, 5)]
    assert r["open_questions"] == [{"asker": 1, "text": "Ne zaman?", "line": 4}]
    assert [p["id"] for p in r["people"]] == [0, 1]
    assert r["people"][0] == {"id": 0, "contribution": "", "gained": "", "evidence": []}
    assert r["people"][1]["evidence"] == [3, 5]
    sc = r["score"]
    assert (sc["decisions"], sc["focus"], sc["repetition"]) == (100, 0, 60)
    assert sc["balance"] == round(r["stats"]["balance"] * 100)
    assert sc["overall"] == round((100 + 0 + 60 + sc["balance"]) / 4)


def test_cancel_between_parts(monkeypatch):
    monkeypatch.setattr(analysis, "CHUNK_TOKENS", 30)
    segs = [seg(i, 0, i, i + 1, "bu bir deneme cümlesi numara %d" % i) for i in range(1, 9)]
    jid = make_job(segs)
    ev = threading.Event()
    fake = Fake()

    def gen(prompt, schema=None, **kw):
        r = fake(prompt, schema, **kw)
        ev.set()
        return r

    a = analysis.run(jid, cancel=ev, generate=gen)
    assert a["state"] == "cancelled" and len(fake.calls) == 1
    assert not (store.job_path(jid) / "analysis.json").exists()


def test_generate_error_gives_error_state():
    jid = make_job(hand_made())

    def boom(prompt, schema=None, **kw):
        raise RuntimeError("model crashed")

    a = analysis.run(jid, generate=boom)
    assert a["state"] == "error" and "model crashed" in a["error"]
    assert analysis.status(jid)["state"] == "error"


def test_names_stage_is_applied_only_to_default_labels(monkeypatch):
    import types

    mod = types.ModuleType("backend.names_llm")
    mod.suggest = lambda segs, spk, gen: [{"speaker": 1, "name": "Burak", "confidence": 0.9, "line": 3}]
    mod.combine = lambda rule, llm, voice: ({0: "Mehmet", 1: "Burak"}, [{"speaker": 1, "name": "Burak", "line": 3}])
    monkeypatch.setitem(sys.modules, "backend.names_llm", mod)
    monkeypatch.setattr("backend.names_llm", mod, raising=False)
    jid = make_job(hand_made(), {"0": "Ali", "1": "Speaker 2"})
    merge = {"summary": "s", "people": [{"name": "Burak", "contribution": "c", "gained": "", "evidence": []}]}
    assert analysis.run(jid, generate=Fake(merge=merge))["state"] == "done"
    assert store.read_transcript(jid)["speakers"] == {"0": "Ali", "1": "Burak"}
    r = analysis.status(jid)["analysis"]
    assert r["name_suggestions"][0]["name"] == "Burak" and r["people"][1]["contribution"] == "c"


# ---------- status / bridge / hook ----------
def test_status_none_and_stale():
    jid = make_job(hand_made())
    assert analysis.status(jid)["state"] == "none"
    analysis.run(jid, generate=Fake())
    assert analysis.status(jid)["state"] == "done"
    store.save_edits(jid, {1: "değişti"})
    s = analysis.status(jid)
    assert s["state"] == "stale" and s["analysis"] is not None


def test_bridge_get_analysis_shape():
    jid = make_job(hand_made())
    api = bridge.Api(lambda: None)
    s = api.get_analysis(jid)
    assert set(s) == {"state", "stage", "progress", "part", "parts", "error", "analysis", "llm_ready"}
    assert s["state"] == "none" and s["analysis"] is None
    assert api.cancel_analysis(jid) == {"ok": True}
    with pytest.raises(ValueError):
        api.get_analysis("nope")


def test_start_refuses_without_llm_and_queues_with_it(monkeypatch):
    jid = make_job(hand_made())
    monkeypatch.setattr(analysis, "llm_ready", lambda: False)
    assert analysis.start(jid)["ok"] is False
    assert analysis.status(jid)["state"] == "none"
    done = threading.Event()
    monkeypatch.setattr(analysis, "llm_ready", lambda: True)
    monkeypatch.setattr(analysis, "run", lambda job_id, cancel=None, generate=None: done.set())
    assert bridge.Api(lambda: None).analyze_job(jid) == {"ok": True}
    assert done.wait(5)


def test_meeting_mode_setting_and_hook(monkeypatch):
    from backend import asr, pipeline

    api = bridge.Api(lambda: None)
    assert api.get_settings()["meeting_mode"] is False
    assert api.set_settings({"meeting_mode": True})["meeting_mode"] is True
    started = []
    monkeypatch.setattr(analysis, "start", lambda job_id: started.append(job_id))
    monkeypatch.setattr("backend.diarize.refine_by_sentence", lambda s, w, spk, cb: spk)
    monkeypatch.setattr("backend.people.apply_to_job", lambda *a, **k: {})
    monkeypatch.setattr(asr, "transcribe", lambda *a, **k: ([], "tr"))
    jid = make_job([])
    jp = store.job_path(jid)
    st = {"stage": "", "progress": 0.0, "dprogress": 0.0}

    def finish():
        pipeline._transcribe_and_finish(jid, jp, {}, None, 10.0, [], "cpu", False, None,
                                        {"turns": [], "secs": 0.0}, lambda: None, lambda p: None,
                                        lambda **k: None, st, False, 0.0, 0.0)

    finish()
    assert started == [jid]
    api.set_settings({"meeting_mode": False})
    finish()
    assert started == [jid]


def test_mark_interrupted_cancels_leftover_analysis():
    jid = make_job(hand_made())
    store.update_job(jid, analysis={"state": "running", "stage": "notes"})
    store.mark_interrupted()
    assert store.read_transcript(jid)["analysis"]["state"] == "cancelled"
