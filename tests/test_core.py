import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import export, store  # noqa: E402
from backend.merge import Turn, Word, build_segments  # noqa: E402


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MEETTRANSCRIBER_HOME", str(tmp_path))


def W(s, e, t):
    return Word(s, e, t)


def test_split_on_speaker_change():
    words = [W(0, .5, " Hello"), W(.5, 1, " there"), W(1.1, 1.6, " Hi"), W(1.6, 2, " all")]
    turns = [Turn(0, 1.05, 0), Turn(1.05, 2, 1)]
    segs = build_segments(words, turns)
    assert [(s["speaker"], s["text_original"]) for s in segs] == [(0, "Hello there"), (1, "Hi all")]
    assert [s["id"] for s in segs] == [0, 1]


def test_split_on_long_pause_and_no_turns():
    words = [W(0, 1, " a"), W(5, 6, " b")]
    segs = build_segments(words, [])
    assert len(segs) == 2 and all(s["speaker"] == 0 for s in segs)


def test_word_in_gap_goes_to_nearest_turn():
    segs = build_segments([W(3.0, 3.2, " x")], [Turn(0, 1, 0), Turn(3.5, 5, 1)])
    assert segs[0]["speaker"] == 1


def test_sentences_split_on_punct_and_pause():
    from backend.merge import sentences

    ws = [W(0, .5, " Bir."), W(.6, 1, " iki"), W(3, 3.5, " üç"), W(3.6, 4, " dört?")]
    assert sentences(ws) == [(0, 1), (1, 2), (2, 4)]


def _seg_words(text_words, t=0.0, dur=0.5):
    words = []
    for w in text_words:
        words.append(W(t, t + dur, w)); t += dur
    return words


def test_split_uses_word_times():
    words = _seg_words([" Benim", " durumum", " iyi.", " Bakalım", " kaç", " ses?"])
    seg = build_segments(words, [Turn(0, 10, 2)])[0]
    text = seg["text_edited"]
    a = text.index("Bakalım")
    from backend.merge import split_segment

    parts = split_segment(seg, a + 2, len(text), 1, next_id=9)  # mid-word selection snaps
    assert [p["text_edited"] for p in parts] == ["Benim durumum iyi.", "Bakalım kaç ses?"]
    assert [p["speaker"] for p in parts] == [2, 1]
    assert [p["id"] for p in parts] == [seg["id"], 9]
    assert parts[1]["start"] == 1.5 and parts[1]["end"] == 3.0
    assert parts[1]["text_original"] == "Bakalım kaç ses?"
    assert len(parts[0]["words"]) == 3 and len(parts[1]["words"]) == 3


def test_split_edited_text_interpolates():
    from backend.merge import split_segment

    seg = {"id": 0, "start": 0.0, "end": 10.0, "speaker": 0, "text_original": "aaaa bbbb",
           "text_edited": "AAAA BBBB", "words": []}
    parts = split_segment(seg, 0, 4, 1, next_id=1)
    assert [(p["text_edited"], p["text_original"], p["speaker"]) for p in parts] == \
        [("AAAA", "aaaa", 1), ("BBBB", "bbbb", 0)]
    assert parts[0]["end"] == parts[1]["start"]


def test_detect_names():
    from backend.names import detect_names

    segs = [
        {"speaker": 0, "text_edited": "Merhaba ben Selim."},
        {"speaker": 1, "text_edited": "Ben de konuşmacı olarak Bahadır ekstra bir şey söylüyorum. Umut sen de bir şey söylesene."},
        {"speaker": 2, "text_edited": "Benim psikolojim çok bozuk."},
    ]
    default = {"0": "Speaker 1", "1": "Speaker 2", "2": "Speaker 3"}
    assert detect_names(segs, default) == {0: "Selim", 1: "Bahadır", 2: "Umut"}
    segs2 = [dict(s) for s in segs]
    segs2[1] = {"speaker": 1, "text_edited": "Ben Bahadır. Umut sen bir şey söylesene."}
    assert detect_names(segs2, default)[2] == "Umut"
    # a speaker renamed by the user is never overwritten
    assert detect_names(segs, {**default, "0": "Ali"}) == {1: "Bahadır", 2: "Umut"}
    # place names with a suffix are not names; English intro works
    assert detect_names([{"speaker": 0, "text_edited": "Ben Ankara'da yaşıyorum."},
                         {"speaker": 1, "text_edited": "Hi, my name is Anna."}], default) == {1: "Anna"}


def _job():
    jid = store.create_job("meet.mp3")
    segs = build_segments([W(0, 1, " hello"), W(2.5, 3, " world")], [Turn(0, 3, 0)], max_gap=1)
    store.update_job(jid, status="done", segments=segs, speakers={"0": "Speaker 1"})
    return jid


def test_edits_never_touch_original():
    jid = _job()
    store.save_edits(jid, {0: "HELLO!"}, {0: "Ayse"}, {1: 1})
    d = store.read_transcript(jid)
    assert d["segments"][0]["text_original"] == "hello"
    assert d["segments"][0]["text_edited"] == "HELLO!"
    assert d["segments"][1]["speaker"] == 1
    assert d["speakers"]["0"] == "Ayse"


def test_export_versions_and_formats():
    jid = _job()
    store.save_edits(jid, {0: "HELLO!"}, {0: "Ayse"})
    d = store.read_transcript(jid)
    assert "HELLO!" in export.render(d, "edited", "txt")
    assert "HELLO!" not in export.render(d, "original", "txt")
    assert "Ayse" in export.render(d, "original", "md")
    srt = export.render(d, "edited", "srt")
    assert "00:00:00,000 --> 00:00:01,000" in srt
    assert json.loads(export.render(d, "edited", "json"))["segments"][0]["speaker"] == "Ayse"
    with pytest.raises(ValueError):
        export.render(d, "edited", "pdf")


def test_replace_transcript_protects_original_and_exports():
    jid = _job()
    d = store.read_transcript(jid)
    d["original_segments"] = [{k: s[k] for k in ("start", "end", "speaker", "text_original")} for s in d["segments"]]
    store.write_transcript(jid, d)
    # client: delete line 1, edit line 0 (and try to tamper with the original), add a new line
    segs = [{"id": 0, "start": 0, "end": 1, "speaker": 0, "text_edited": "hi", "text_original": "HACK"},
            {"id": 7, "start": 1, "end": 2, "speaker": 1, "text_edited": "new line"}]
    out = store.replace_transcript(jid, segs, {"0": "Ayse", "1": "Mehmet"})
    assert [s["text_original"] for s in out["segments"]] == ["hello", ""]
    assert out["speakers"] == {"0": "Ayse", "1": "Mehmet"}
    edited = export.render(out, "edited", "txt")
    assert "new line" in edited and "world" not in edited
    original = export.render(out, "original", "txt")  # model output, unaffected by deletes
    assert "hello" in original and "world" in original and "new line" not in original
    with pytest.raises(ValueError):
        store.replace_transcript(jid, segs + [segs[0]], {})
    # undo of a delete: the line comes back with its model text
    back = store.replace_transcript(jid, segs + [{"id": 1, "start": 2.5, "end": 3, "speaker": 0,
                                                  "text_edited": "world", "text_original": "world"}], {})
    assert [s["text_original"] for s in back["segments"]] == ["hello", "", "world"]


def test_docx_export():
    import io
    from docx import Document

    jid = _job()
    blob = export.render(store.read_transcript(jid), "edited", "docx")
    text = "\n".join(p.text for p in Document(io.BytesIO(blob)).paragraphs)
    assert "hello" in text and "Speaker 1" in text


def test_list_search_and_rename():
    jid = _job()
    store.save_edits(jid, {0: "Bütçe İstanbul toplantısı"}, {0: "Ayşe"})
    other = store.create_job("other.mp3")
    assert {j["id"] for j in store.list_jobs()} == {jid, other}
    hit = store.list_jobs("istanbul")  # İ/i forgiving
    assert [j["id"] for j in hit] == [jid]
    assert hit[0]["matches"][0]["speaker"] == "Ayşe" and hit[0]["matches"][0]["seg"] == 0
    assert hit[0]["count"] == 1 and not hit[0]["name_match"]
    by_spk = store.list_jobs("ayşe")  # speaker name
    assert [j["id"] for j in by_spk] == [jid] and by_spk[0]["speaker_match"] == ["Ayşe"]
    by_name = store.list_jobs("meet")  # file name, but the word is also in no line
    assert by_name[0]["name_match"] and by_name[0]["matches"] == []
    assert store.list_jobs("zzz") == []
    store.rename_job(jid, "  Pazartesi toplantısı ")
    assert store.read_transcript(jid)["filename"] == "Pazartesi toplantısı"
    with pytest.raises(ValueError):
        store.rename_job(jid, "   ")


def test_desktop_save_export(tmp_path, monkeypatch):
    import sys
    import types

    from backend import bridge

    jid = _job()
    calls = []

    class FakeWin:
        def create_file_dialog(self, kind, **kw):
            calls.append((kind, kw))
            return str(tmp_path / "chosen") if kind == "save" else (str(tmp_path),)

    fake = types.SimpleNamespace(FileDialog=types.SimpleNamespace(SAVE="save", FOLDER="folder", OPEN="open"))
    monkeypatch.setitem(sys.modules, "webview", fake)
    api = bridge.Api(window_getter=FakeWin)
    r = api.save_export(jid, "edited", "txt")
    assert r["paths"] == [str(tmp_path / "chosen.txt")] and "hello" in (tmp_path / "chosen.txt").read_text("utf-8")
    assert calls[0][1]["save_filename"] == "meet.edited.txt"
    r = api.save_export(jid, "both", "docx")  # both -> folder dialog, two files
    assert sorted(Path(p).name for p in r["paths"]) == ["meet.edited.docx", "meet.original.docx"]
    assert api._last_dir() == str(tmp_path)  # remembers the folder
    FakeWin.create_file_dialog = lambda self, kind, **kw: None
    assert api.save_export(jid, "edited", "txt") == {"cancelled": True}


def test_export_language_for_default_names():
    jid = _job()  # speaker 0 still has the default label "Speaker 1"
    d = store.read_transcript(jid)
    assert "Konuşmacı 1:" in export.render(d, "edited", "txt", "tr")
    assert "Speaker 1:" in export.render(d, "edited", "txt", "en")
    store.save_edits(jid, speakers={0: "Ayşe"})
    assert "Ayşe:" in export.render(store.read_transcript(jid), "edited", "txt", "tr")
    from backend.names import detect_names  # "Konuşmacı 1" still counts as unnamed
    assert detect_names([{"speaker": 0, "text_edited": "Ben Selim."}], {"0": "Konuşmacı 1"}) == {0: "Selim"}


def test_job_id_traversal_rejected():
    with pytest.raises(ValueError):
        store.job_path("../x")


def test_bridge_roundtrip():
    from backend.bridge import Api

    api = Api(window_getter=lambda: None)
    jid = _job()
    assert api.get_job(jid)["filename"] == "meet.mp3"
    api.save_edits(jid, {"0": "fixed"})  # keys arrive as strings from JS
    assert api.get_job(jid)["segments"][0]["text_edited"] == "fixed"
    assert api.get_job(jid)["segments"][0]["text_original"] == "hello"
    with pytest.raises(ValueError):
        api.get_job("doesnotexist")
    with pytest.raises(ValueError):
        api.split(jid, 0, 0, 2, 99)
    assert api.rename_job(jid, "x")["filename"] == "x"
    assert [j["id"] for j in api.list_jobs("fixed")] == [jid]
    assert api.delete_job(jid) == {"ok": True} and api.list_jobs() == []
    assert not [n for n in dir(api) if not n.startswith("_") and n in ("_window", "_last_dir")]


def test_start_job_never_deletes_the_users_file(tmp_path, monkeypatch):
    from backend import bridge, pipeline

    src = tmp_path / "my meeting.m4a"
    src.write_bytes(b"not really audio")
    done = []
    real = pipeline.run_job
    monkeypatch.setattr(bridge, "run_job", lambda *a, **kw: (real(*a, **kw), done.append(1)))
    r = bridge.Api(window_getter=lambda: None).start_job(str(src))
    import time
    for _ in range(100):
        if done:
            break
        time.sleep(0.05)
    assert done and src.exists()  # the job failed (not audio) but the file is untouched
    assert store.read_transcript(r["id"])["status"] == "error"
    with pytest.raises(ValueError):
        bridge.Api().start_job(str(tmp_path / "missing.mp3"))


def test_choose_cuts_only_in_pauses():
    from backend.chunking import choose_cuts

    # someone talks non-stop except short pauses every 20 s; total 12 minutes
    speech, t = [], 0.0
    while t < 720:
        speech.append((t, t + 19.6))  # 0.4 s pause after each 19.6 s of speech
        t += 20
    parts = choose_cuts(720.0, speech)
    assert parts[0][0] == 0 and parts[-1][1] == 720.0
    for (a, b), (c, _) in zip(parts, parts[1:]):
        assert b == c                      # parts touch, nothing lost
        assert 270 <= b - a <= 300         # 4:30 .. 5:00
        assert any(e <= b <= s2 for (_, e), (s2, _) in zip(speech, speech[1:]))  # cut is inside a pause
    assert all(b - a <= 300 for a, b in parts)


def test_choose_cuts_prefers_longest_pause_and_falls_back_to_quiet():
    from backend.chunking import choose_cuts

    speech = [(0, 280), (280.3, 290), (292.0, 600)]  # 0.3 s pause at 280, 2 s pause at 290..292
    parts = choose_cuts(600.0, speech)
    assert parts[0] == (0.0, 291.0)  # middle of the longest pause in 4:30..5:00
    # no pause at all -> the quietest moment decides
    parts = choose_cuts(400.0, [(0, 400)], quietest=lambda a, b: 288.5)
    assert parts == [(0.0, 288.5), (288.5, 400.0)]
    assert choose_cuts(200.0, [(0, 200)]) == [(0.0, 200.0)]  # short file: one part


def test_mark_interrupted_and_resume_guard():
    from backend.bridge import Api

    jid = store.create_job("long.m4a")
    store.update_job(jid, status="running", stage="transcribing")
    assert store.mark_interrupted() == [jid]
    assert store.read_transcript(jid)["status"] == "interrupted"
    with pytest.raises(ValueError):  # no audio.mp3 saved yet -> cannot resume
        Api(window_getter=lambda: None).resume_job(jid)


def test_every_file_dialog_filter_is_valid_for_pywebview():
    from webview.util import parse_file_type

    from backend import bridge

    for f in (*bridge.MEDIA_TYPES, *bridge.EXPORT_TYPES.values()):
        parse_file_type(f)  # raises ValueError for e.g. a "/" in the description


def _make_video(path, seconds=2, fmt="mp4", vcodec="mpeg4", acodec="aac"):
    """A tiny real video file: black frames plus a 440 Hz tone."""
    import av
    import numpy as np

    with av.open(str(path), "w", format=fmt) as out:
        v = out.add_stream(vcodec, rate=10)
        v.width, v.height, v.pix_fmt = 64, 48, "yuv420p"
        a = out.add_stream(acodec, rate=16000)
        a.layout = "mono"
        for i in range(seconds * 10):
            f = av.VideoFrame.from_ndarray(np.zeros((48, 64, 3), np.uint8), format="rgb24")
            f.pts = i
            for p in v.encode(f.reformat(format="yuv420p")):
                out.mux(p)
        for p in v.encode(None):
            out.mux(p)
        t = np.arange(seconds * 16000) / 16000
        pcm = (np.sin(2 * np.pi * 440 * t) * 12000).astype(np.int16).reshape(1, -1)
        for k in range(0, pcm.shape[1], 1024):
            fr = av.AudioFrame.from_ndarray(pcm[:, k:k + 1024], format="s16", layout="mono")
            fr.sample_rate = 16000
            fr.pts = k
            for p in a.encode(fr):
                out.mux(p)
        for p in a.encode(None):
            out.mux(p)


@pytest.mark.parametrize("fmt,vcodec,acodec,name", [("mp4", "mpeg4", "aac", "a.mp4"), ("matroska", "mpeg4", "aac", "a.mkv")])
def test_video_files_are_processed_by_their_audio_only(tmp_path, fmt, vcodec, acodec, name):
    from backend import audio

    src = tmp_path / name
    _make_video(src, fmt=fmt, vcodec=vcodec, acodec=acodec)
    mp3 = tmp_path / "play.mp3"
    pcm, dur = audio.convert(src, mp3)
    assert 1.8 < dur < 2.3 and pcm.dtype.name == "float32" and abs(pcm).max() > 0.1  # the tone, not silence
    assert mp3.stat().st_size > 1000  # playback is the extracted audio


def test_file_without_audio_track_gives_a_clear_error(tmp_path):
    import av
    import numpy as np
    from backend import audio

    src = tmp_path / "mute.mp4"
    with av.open(str(src), "w", format="mp4") as out:
        v = out.add_stream("mpeg4", rate=10)
        v.width, v.height, v.pix_fmt = 64, 48, "yuv420p"
        for i in range(5):
            f = av.VideoFrame.from_ndarray(np.zeros((48, 64, 3), np.uint8), format="rgb24")
            f.pts = i
            for p in v.encode(f.reformat(format="yuv420p")):
                out.mux(p)
        for p in v.encode(None):
            out.mux(p)
    with pytest.raises(ValueError, match="no audio"):
        audio.convert(src, None)
