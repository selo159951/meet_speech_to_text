import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import export  # noqa: E402


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SESDEFTERI_HOME", str(tmp_path))


JOB = {
    "id": "abc123",
    "filename": "toplanti.mp3",
    "language": "tr",
    "speakers": {"0": "Deniz", "1": "Burak", "2": "Ceren"},
    "segments": [
        {"id": 1, "start": 0.0, "end": 10.0, "speaker": 0, "text_edited": "Merhaba", "text_original": "Merhaba"},
        {"id": 23, "start": 65.0, "end": 70.0, "speaker": 1, "text_edited": "Bütçe", "text_original": "Bütçe"},
        {"id": 40, "start": 121.0, "end": 128.0, "speaker": 1, "text_edited": "Rapor", "text_original": "Rapor"},
        {"id": 55, "start": 300.0, "end": 305.0, "speaker": 2, "text_edited": "Ne zaman?", "text_original": "Ne zaman?"},
    ],
}

ANALYSIS = {
    "version": 1,
    "summary": "Kısa bir toplantı özeti.",
    "topics": [{"title": "Bütçe", "summary": "Bütçe konuşuldu.", "start": 0.0, "end": 181.0, "line": 1}],
    "decisions": [{"text": "Yeni bütçe onaylandı.", "line": 23}],
    "tasks": [
        {"owner": 1, "task": "Raporu yaz", "due": "Cuma", "line": 40},
        {"owner": None, "task": "Sahipsiz iş", "due": "", "line": 40},
    ],
    "open_questions": [{"asker": 2, "text": "Ne zaman toplanıyoruz?", "line": 55}],
    "stats": {
        "duration": 912.4,
        "speakers": [
            {"id": 0, "name": "Deniz", "seconds": 430.1, "share": 0.52, "turns": 31,
             "words": 980, "questions": 7, "longest_turn": 48.0},
            {"id": 1, "name": "Burak", "share": 0.48, "turns": 20, "words": 700, "questions": 2},
        ],
    },
    "people": [
        {"id": 0, "contribution": "Bütçeyi açıkladı.", "gained": "Plan netleşti.", "evidence": [1]},
        {"id": 1, "contribution": "Görev aldı.", "gained": "", "evidence": []},
    ],
    "score": {"overall": 68, "decisions": 70, "tasks": 60, "questions": 80, "repetition": 75, "balance": 55,
              "comment": "Verimli bir toplantı.", "tips": ["Daha kısa konuşun."]},
}

EMPTY = {"summary": "", "topics": [], "decisions": [], "tasks": [], "open_questions": [],
         "people": [], "stats": {"speakers": []}, "score": {}}


def test_markdown_export_resolves_names_and_line_times():
    out = export.render_analysis(JOB, ANALYSIS, "md")
    assert out.startswith("# toplanti.mp3")
    assert "AI-generated, may contain mistakes" in out
    assert "Meeting score" in out and "Overall: 68" in out and "Balance: 55" in out
    assert "Summary" in out and "Kısa bir toplantı özeti." in out
    assert "[00:00:00 – 00:03:01] Bütçe" in out
    assert "Yeni bütçe onaylandı. [00:01:05]" in out
    assert "Burak: Raporu yaz (Due: Cuma) [00:02:01]" in out
    assert "—: Sahipsiz iş [00:02:01]" in out  # null owner
    assert "Ceren: Ne zaman toplanıyoruz? [00:05:00]" in out
    assert "Deniz — 52% talk time · 31 turns · 980 words · 7 questions" in out
    assert "Contribution: Bütçeyi açıkladı." in out
    assert "Gained: Plan netleşti." in out
    assert "Daha kısa konuşun." in out


def test_text_export_turkish_headings():
    out = export.render_analysis(JOB, ANALYSIS, "txt", "tr")
    assert "Yapay zekâ yorumudur, hata içerebilir" in out
    for heading in ("TOPLANTI PUANI", "ÖZET", "KONULAR", "KARARLAR", "GÖREVLER",
                    "AÇIK SORULAR", "KIŞILER"):
        assert heading in out
    assert "Genel: 68" in out
    assert "Deniz — %52 konuşma payı · 31 sıra · 980 kelime · 7 soru" in out
    assert "Vade: Cuma" in out


def test_json_export_is_the_analysis_itself():
    out = export.render_analysis(JOB, ANALYSIS, "json")
    assert json.loads(out) == ANALYSIS


def test_docx_export_is_a_real_document():
    blob = export.render_analysis(JOB, ANALYSIS, "docx")
    assert isinstance(blob, bytes) and blob.startswith(b"PK")
    from docx import Document

    text = "\n".join(p.text for p in Document(io.BytesIO(blob)).paragraphs)
    assert "toplanti.mp3" in text and "Deniz" in text and "—: Sahipsiz iş" in text


def test_empty_analysis_does_not_crash():
    for fmt in ("md", "txt", "json", "docx"):
        out = export.render_analysis(JOB, EMPTY, fmt)
        assert out
    assert JOB["filename"] in export.render_analysis(JOB, EMPTY, "md")
    assert json.loads(export.render_analysis(JOB, EMPTY, "json")) == EMPTY


def test_unknown_format_is_rejected():
    with pytest.raises(ValueError):
        export.render_analysis(JOB, ANALYSIS, "pdf")
