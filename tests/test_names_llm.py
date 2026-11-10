import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import bridge, names_llm, store  # noqa: E402
from backend.names_llm import candidates, combine, suggest, title  # noqa: E402

MEETING = Path(__file__).parent / "data" / "meeting_tr.txt"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MEETTRANSCRIBER_HOME", str(tmp_path))


def seg(i, spk, text):
    return {"id": i, "speaker": spk, "text_edited": text, "text_original": text}


def talk(*pairs):
    return [seg(i + 1, s, t) for i, (s, t) in enumerate(pairs)]


class Fake:
    def __init__(self, answer=None):
        self.answer = answer or {"speakers": []}
        self.prompts = []

    def __call__(self, prompt, schema=None, system=None, **kw):
        self.prompts.append(prompt)
        return self.answer


def entry(spk, name, conf="high", line=1):
    return {"speaker": spk, "name": name, "confidence": conf, "line": line, "reason": ""}


def idx(groups):
    return {i for g in groups for i in g}


# ---------------------------------------------------------------- candidates
def test_candidates_take_neighbours():
    segs = talk(*[(i % 2, "bir iki üç dört") for i in range(12)])
    segs[5]["text_edited"] = "Elif sen ne dersin?"
    assert candidates(segs) == [[4, 5, 6, 7]]  # 1 before, 2 after


def test_candidates_intro_and_thanks_patterns():
    segs = talk(*[(0, "düz konuşma") for _ in range(30)])
    segs[2]["text_edited"] = "Merhaba, ben Deniz."
    segs[20]["text_edited"] = "teşekkürler Burak"
    got = idx(candidates(segs))
    assert {2, 20} <= got and 10 not in got
    assert len(candidates(segs)) == 2


def test_candidates_none_without_names():
    assert candidates(talk((0, "bugün hava güzel."), (1, "Evet. Tamam."))) == []


def test_candidates_respect_cap():
    segs = talk(*[(i % 2, f"bence Android sürümü {'x' * 200} Ankara") for i in range(200)])
    total = sum(len(segs[i]["text_edited"]) for i in idx(candidates(segs)))
    assert 0 < total < names_llm.MAX_TOKENS * 3


# ---------------------------------------------------------------- prompt
def test_prompt_uses_neutral_labels():
    segs = talk((0, "Ben Deniz, merhaba."), (1, "Selam."), (2, "Selam."))
    fake = Fake()
    suggest(segs, {"0": "Mehmet", "1": "Ayşe", "2": "Speaker 3"}, fake)
    p = fake.prompts[0]
    assert "[1] Konuşmacı 1: Ben Deniz" in p and "Konuşmacı 3:" in p
    assert "Mehmet" not in p and "Ayşe" not in p


def test_prompt_english():
    segs = talk((0, "Hi, I'm Ana."), (1, "Hello."))
    fake = Fake()
    suggest(segs, {"0": "Speaker 1", "1": "Speaker 2"}, fake, lang="en")
    assert "[1] Speaker 1: Hi, I'm Ana." in fake.prompts[0] and "previous" in fake.prompts[0].lower()


def test_no_candidates_no_call():
    fake = Fake()
    assert suggest(talk((0, "evet"), (1, "hayır")), {"0": "Speaker 1"}, fake) == []
    assert fake.prompts == []


# ---------------------------------------------------------------- post-processing
def run_post(entries, segs=None):
    segs = segs or talk((0, "Ben Deniz."), (1, "Ha, tamam. Elif sen?"), (2, "Evet. Ece, Işıl ve İrem de burada."))
    return suggest(segs, {"0": "Speaker 1", "1": "Speaker 2", "2": "Speaker 3"}, Fake({"speakers": entries}))


def test_post_drops_invalid():
    got = run_post([
        entry(1, "Deniz", line=1),
        entry(9, "Ghost", line=1),   # unknown speaker
        entry(2, "Burak", line=99),  # missing line
        entry(3, "Tamam", line=3),   # stop word
        entry(2, "bir iki üç dört", line=2),  # not a name
    ])
    assert got == [{"speaker": 0, "name": "Deniz", "confidence": 0.9, "line": 1}]


def test_post_duplicate_name_and_best_entry():
    got = run_post([
        entry(1, "Deniz", "medium", 1), entry(1, "Deniz", "high", 1),
        entry(2, "DENİZ", "low", 2), entry(3, "Elif", "low", 3), entry(3, "Ece", "medium", 3),
    ])
    assert [(e["speaker"], e["name"], e["confidence"]) for e in got] == [(0, "Deniz", 0.9), (2, "Ece", 0.6)]


def test_turkish_casing():
    assert title("ıŞIL") == "Işıl" and title("İREM") == "İrem" and title("iPEK") == "İpek"
    assert title("ayşe nur") == "Ayşe Nur"
    got = run_post([entry(1, "ıŞIL"), entry(2, "İREM", "medium", 2)])
    assert [e["name"] for e in got] == ["Işıl", "İrem"]


# ---------------------------------------------------------------- combine
def L(spk, name, conf=0.9, line=1):
    return {"speaker": spk, "name": name, "confidence": conf, "line": line}


def test_combine_voice_match_left_alone():
    auto, sug = combine({0: "Deniz"}, [L(0, "Deniz")], {"voice_matches": {"0": {"name": "Selim"}}})
    assert auto == {} and sug == []


def test_combine_agree_is_auto_ignoring_case_and_diacritics():
    auto, sug = combine({0: "Işıl"}, [L(0, "IŞIL", 0.3)], {})
    assert auto == {0: "Işıl"} and sug == []
    assert combine({0: "Ipek"}, [L(0, "İpek", 0.3)], {})[0] == {0: "Ipek"}


def test_combine_llm_alone():
    assert combine({}, [L(1, "Burak", 0.9)], {}) == ({1: "Burak"}, [])
    auto, sug = combine({}, [L(1, "Burak", 0.6)], {})
    assert auto == {} and [(s["name"], s["source"]) for s in sug] == [("Burak", "llm")]


def test_combine_rule_alone_and_conflict():
    auto, sug = combine({0: "Deniz"}, [], {})
    assert auto == {} and [(s["name"], s["source"]) for s in sug] == [("Deniz", "rule")]
    auto, sug = combine({0: "Deniz"}, [L(0, "Burak", 0.9)], {})
    assert auto == {} and {(s["name"], s["source"]) for s in sug} == {("Deniz", "rule"), ("Burak", "llm")}


def test_combine_non_default_label_untouched():
    sp = {"0": "Mehmet", "1": "Speaker 2", "2": "Konuşmacı 3"}
    auto, sug = combine({0: "Deniz", 1: "Burak"}, [L(0, "Deniz"), L(2, "Elif")], {}, sp)
    assert auto == {2: "Elif"}
    assert [(s["speaker"], s["name"], s["source"]) for s in sug] == [(1, "Burak", "rule")]  # nothing for speaker 0


def test_combine_name_already_taken():
    sp = {"0": "Deniz", "1": "Speaker 2", "2": "Speaker 3"}
    auto, sug = combine({1: "deniz"}, [L(1, "Deniz"), L(2, "Burak"), ], {}, sp)
    assert auto == {2: "Burak"} and sug == []
    auto, sug = combine({}, [L(1, "Elif"), L(2, "Elif", 0.95)], {}, {"0": "x", "1": "Speaker 2", "2": "Speaker 3"})
    assert len(auto) == 1 and sug == []


# ---------------------------------------------------------------- real-looking meeting
def load_meeting():
    segs = []
    for line in MEETING.read_text("utf-8").splitlines():
        m = re.match(r"\[(\d+)\] \[[\d:-]+\] Konuşmacı (\d): (.*)", line)
        if m:
            segs.append(seg(int(m[1]), int(m[2]) - 1, m[3]))
    return segs


def test_meeting_candidates_reveal_names():
    segs = load_meeting()
    assert len(segs) > 60
    shown = {segs[i]["id"] for i in idx(candidates(segs))}
    assert 1 in shown                  # "Ben Deniz"
    assert {6, 7} <= shown             # "Elif sen ne dersin" + Elif's reply
    assert {37, 38} <= shown           # "Burak sen" + Burak's reply
    text = " ".join(segs[i]["text_edited"] for i in idx(candidates(segs)))
    assert all(n in text for n in ("Deniz", "Burak", "Elif"))


def test_meeting_suggest_end_to_end():
    segs = load_meeting()
    fake = Fake({"speakers": [entry(1, "DENİZ", line=1), entry(3, "Elif", "medium", 6), entry(2, "Burak", "high", 37)]})
    got = suggest(segs, {"0": "Speaker 1", "1": "Speaker 2", "2": "Speaker 3"}, fake)
    assert {e["speaker"]: e["name"] for e in got} == {0: "Deniz", 1: "Burak", 2: "Elif"}
    assert max(len(fake.prompts[0]), 0) < names_llm.MAX_TOKENS * 3 + 3000


# ---------------------------------------------------------------- bridge
def make_job():
    jid = store.create_job("m.mp3")
    segs = talk((0, "Ben Deniz."), (1, "Tamam."))
    store.update_job(jid, segments=segs, speakers={"0": "Speaker 1", "1": "Speaker 2"}, status="done")
    return jid


def test_accept_name_suggestion_renames_and_cleans_analysis():
    jid = make_job()
    path = store.job_path(jid) / "analysis.json"
    path.write_text(json.dumps({"summary": "x", "name_suggestions": [
        {"speaker": 1, "name": "Burak", "confidence": 0.6, "line": 2, "source": "llm"},
        {"speaker": 0, "name": "Deniz", "confidence": 0.6, "line": 1, "source": "rule"}]}), "utf-8")
    job = bridge.Api().accept_name_suggestion(jid, 1, " Burak ")
    assert job["speakers"] == {"0": "Speaker 1", "1": "Burak"}
    assert store.read_transcript(jid)["speakers"]["1"] == "Burak"
    data = json.loads(path.read_text("utf-8"))
    assert [s["speaker"] for s in data["name_suggestions"]] == [0] and data["summary"] == "x"


def test_accept_name_suggestion_without_analysis_file():
    jid = make_job()
    assert bridge.Api().accept_name_suggestion(jid, 0, "Deniz")["speakers"]["0"] == "Deniz"
    with pytest.raises(ValueError):
        bridge.Api().accept_name_suggestion(jid, 0, "  ")
    with pytest.raises(ValueError):
        bridge.Api().accept_name_suggestion("nope", 0, "X")


def test_name_that_is_never_said_is_rejected():
    segs = [{"id": 1, "speaker": 0, "start": 0, "end": 1, "text_original": "Good morning everyone, thanks Maria.", "text_edited": "Good morning everyone, thanks Maria."},
            {"id": 2, "speaker": 1, "start": 1, "end": 2, "text_original": "Thanks.", "text_edited": "Thanks."}]
    gen = lambda *a, **k: {"speakers": [{"speaker": 1, "name": "Elif", "confidence": "high", "line": 1, "reason": ""},
                                        {"speaker": 2, "name": "Maria", "confidence": "high", "line": 1, "reason": ""}]}
    out = names_llm.suggest(segs, {"0": "Speaker 1", "1": "Speaker 2"}, gen, lang="en")
    assert [(e["speaker"], e["name"]) for e in out] == [(1, "Maria")]
