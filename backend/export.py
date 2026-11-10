"""Export transcripts as txt / md / srt / json / docx.

"original" = what the model produced (frozen at transcription time),
"edited"   = the transcript after all user changes.
"""
from __future__ import annotations

import io
import json
import re


def ts(sec: float, srt: bool = False) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}" + (f",{ms:03d}" if srt else "")


LABELS = {
    "en": {"speaker": "Speaker", "edited": "Edited transcript", "original": "Original model output", "lines": "lines"},
    "tr": {"speaker": "Konuşmacı", "edited": "Düzenlenmiş metin", "original": "Modelin orijinal çıktısı", "lines": "satır"},
}


def _name(data: dict, spk: int, lang: str = "en") -> str:
    name = data["speakers"].get(str(spk)) or f"Speaker {spk + 1}"
    m = re.fullmatch(r"(?:Speaker|Konuşmacı) (\d+)", name)  # default label -> export language
    return f"{LABELS[lang]['speaker']} {m.group(1)}" if m else name


def rows(data: dict, version: str, lang: str = "en") -> list[dict]:
    """[{start, end, speaker(name), text}] for the chosen version, empty lines dropped."""
    if version == "original":
        src = data.get("original_segments") or data["segments"]  # older jobs have no snapshot
        items = [(s["start"], s["end"], s["speaker"], s["text_original"]) for s in src]
    else:
        items = [(s["start"], s["end"], s["speaker"], s["text_edited"]) for s in data["segments"]]
    return [{"start": a, "end": b, "speaker": _name(data, k, lang), "text": t.strip()}
            for a, b, k, t in items if t and t.strip()]


ANALYSIS_LABELS = {
    "en": {
        "disclaimer": "AI-generated, may contain mistakes",
        "score": "Meeting score", "overall": "Overall", "comment": "Comment", "tips": "Tips",
        "sub_decisions": "Decisions", "sub_focus": "Focus", "sub_repetition": "Repetition",
        "sub_balance": "Balance", "summary": "Summary", "topics": "Topics", "decisions": "Decisions",
        "tasks": "Tasks", "open_questions": "Open questions", "people": "People",
        "owner": "Owner", "due": "Due", "asker": "Asked by",
        "share": "talk time", "turns": "turns", "words": "words", "questions": "questions",
        "contribution": "Contribution", "gained": "Gained",
    },
    "tr": {
        "disclaimer": "Yapay zekâ yorumudur, hata içerebilir",
        "score": "Toplantı puanı", "overall": "Genel", "comment": "Yorum", "tips": "İpuçları",
        "sub_decisions": "Kararlar", "sub_focus": "Odak", "sub_repetition": "Tekrar",
        "sub_balance": "Denge", "summary": "Özet", "topics": "Konular", "decisions": "Kararlar",
        "tasks": "Görevler", "open_questions": "Açık sorular", "people": "Kişiler",
        "owner": "Sorumlu", "due": "Vade", "asker": "Soruyu soran",
        "share": "konuşma payı", "turns": "sıra", "words": "kelime", "questions": "soru",
        "contribution": "Katkısı", "gained": "Kazanımı",
    },
}


def _spk(job: dict, spk, lang: str = "en") -> str:
    """Speaker id -> name from job["speakers"]; None (unknown) becomes an em dash."""
    return "—" if spk is None else _name(job, int(spk), lang)


def _line_stamp(job: dict, line, lang: str = "en") -> str:
    """' [hh:mm:ss]' for the transcript line an analysis item refers to, or ''."""
    if line is None:
        return ""
    seg = next((s for s in job.get("segments") or [] if s.get("id") == line), None)
    return f" [{ts(seg['start'])}]" if seg else ""


def _pct(share: float, lang: str) -> str:
    n = round(share * 100)
    return f"%{n}" if lang == "tr" else f"{n}%"


def _analysis_blocks(job: dict, analysis: dict, lang: str) -> list[tuple[str, str]]:
    """(kind, text) blocks: h1, h2, muted, p, bullet, sub. Shared by md / txt / docx."""
    L = ANALYSIS_LABELS[lang]
    blocks: list[tuple[str, str]] = [("h1", job.get("filename", "")), ("muted", L["disclaimer"])]

    score = analysis.get("score") or {}
    if score:
        blocks.append(("h2", L["score"]))
        if score.get("overall") is not None:
            blocks.append(("p", f"{L['overall']}: {score['overall']}"))
        for key, field in (("sub_decisions", "decisions"), ("sub_focus", "focus"),
                           ("sub_repetition", "repetition"), ("sub_balance", "balance")):
            if score.get(field) is not None:
                blocks.append(("bullet", f"{L[key]}: {score[field]}"))
        if score.get("comment"):
            blocks.append(("p", f"{L['comment']}: {score['comment']}"))
        tips = score.get("tips") or []
        if tips:
            blocks.append(("p", L["tips"]))
            blocks += [("bullet", str(t)) for t in tips]

    if analysis.get("summary"):
        blocks += [("h2", L["summary"]), ("p", analysis["summary"])]

    topics = analysis.get("topics") or []
    if topics:
        blocks.append(("h2", L["topics"]))
        for t in topics:
            rng = ""
            if t.get("start") is not None and t.get("end") is not None:
                rng = f"[{ts(t['start'])} – {ts(t['end'])}] "
            blocks.append(("bullet", f"{rng}{t.get('title', '')}"))
            if t.get("summary"):
                blocks.append(("sub", t["summary"]))

    decisions = analysis.get("decisions") or []
    if decisions:
        blocks.append(("h2", L["decisions"]))
        blocks += [("bullet", f"{d.get('text', '')}{_line_stamp(job, d.get('line'), lang)}")
                   for d in decisions]

    tasks = analysis.get("tasks") or []
    if tasks:
        blocks.append(("h2", L["tasks"]))
        for t in tasks:
            line = f"{_spk(job, t.get('owner'), lang)}: {t.get('task', '')}"
            if t.get("due"):
                line += f" ({L['due']}: {t['due']})"
            blocks.append(("bullet", line + _line_stamp(job, t.get("line"), lang)))

    questions = analysis.get("open_questions") or []
    if questions:
        blocks.append(("h2", L["open_questions"]))
        for q in questions:
            blocks.append(("bullet", f"{_spk(job, q.get('asker'), lang)}: {q.get('text', '')}"
                                      f"{_line_stamp(job, q.get('line'), lang)}"))

    speakers = (analysis.get("stats") or {}).get("speakers") or []
    if speakers:
        people = {p.get("id"): p for p in analysis.get("people") or []}
        blocks.append(("h2", L["people"]))
        for s in speakers:
            parts = [_pct(s["share"], lang) + " " + L["share"]] if s.get("share") is not None else []
            for field, label in (("turns", "turns"), ("words", "words"), ("questions", "questions")):
                if s.get(field) is not None:
                    parts.append(f"{s[field]} {L[label]}")
            blocks.append(("bullet", f"{_spk(job, s.get('id'), lang)} — " + " · ".join(parts)))
            p = people.get(s.get("id")) or {}
            if p.get("contribution"):
                blocks.append(("sub", f"{L['contribution']}: {p['contribution']}"))
            if p.get("gained"):
                blocks.append(("sub", f"{L['gained']}: {p['gained']}"))
    return blocks


def _as_markdown(blocks: list[tuple[str, str]]) -> str:
    lines: list[str] = []
    for kind, text in blocks:
        if kind in ("h1", "h2") and lines and lines[-1] != "":
            lines.append("")
        if kind == "h1":
            lines += [f"# {text}", ""]
        elif kind == "h2":
            lines.append(f"## {text}")
        elif kind == "muted":
            lines += [f"*{text}*", ""]
        elif kind == "bullet":
            lines.append(f"- {text}")
        elif kind == "sub":
            lines.append(f"  {text}")
        else:
            lines.append(text)
    return "\n".join(lines)


def _as_text(blocks: list[tuple[str, str]]) -> str:
    out: list[str] = []
    for kind, text in blocks:
        if kind == "h1":
            out += [text, ""]
        elif kind == "h2":
            if out and out[-1] != "":
                out.append("")
            out.append(text.upper())
        elif kind == "muted":
            out += [text, ""]
        elif kind == "bullet":
            out.append(f"- {text}")
        elif kind == "sub":
            out.append(f"  {text}")
        else:
            out.append(text)
    return "\n".join(out).rstrip() + "\n"


def render_analysis(job: dict, analysis: dict, fmt: str, lang: str = "en") -> str | bytes:
    """Render jobs/<id>/analysis.json for export (md / txt / docx / json)."""
    lang = lang if lang in ANALYSIS_LABELS else "en"
    if fmt == "json":
        return json.dumps(analysis, ensure_ascii=False, indent=2)
    blocks = _analysis_blocks(job, analysis, lang)
    if fmt == "md":
        return _as_markdown(blocks)
    if fmt == "txt":
        return _as_text(blocks)
    if fmt == "docx":
        from docx import Document
        from docx.shared import Pt, RGBColor

        doc = Document()
        for kind, text in blocks:
            if kind == "h1":
                doc.add_heading(text, level=1)
            elif kind == "h2":
                doc.add_heading(text, level=2)
            elif kind == "muted":
                r = doc.add_paragraph().add_run(text)
                r.italic = True
                r.font.size = Pt(9)
                r.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
            elif kind == "bullet":
                doc.add_paragraph(text, style="List Bullet")
            elif kind == "sub":
                p = doc.add_paragraph(text)
                p.paragraph_format.left_indent = Pt(18)
            else:
                doc.add_paragraph(text)
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()
    raise ValueError(f"unknown format {fmt}")


def render(data: dict, version: str, fmt: str, lang: str = "en") -> str | bytes:
    lang = lang if lang in LABELS else "en"
    L = LABELS[lang]
    segs = rows(data, version, lang)
    if fmt == "json":
        return json.dumps({"filename": data["filename"], "language": data.get("language"),
                           "version": version, "segments": segs}, ensure_ascii=False, indent=2)
    if fmt == "srt":
        return "\n".join(
            f"{i}\n{ts(s['start'], True)} --> {ts(s['end'], True)}\n{s['speaker']}: {s['text']}\n"
            for i, s in enumerate(segs, 1))
    if fmt == "md":
        lines = [f"# {data['filename']} ({version})", ""]
        for s in segs:
            lines += [f"**{s['speaker']}** `[{ts(s['start'])} – {ts(s['end'])}]`  ", s["text"], ""]
        return "\n".join(lines)
    if fmt == "txt":
        return "\n\n".join(f"[{ts(s['start'])} - {ts(s['end'])}] {s['speaker']}:\n{s['text']}"
                           for s in segs) + "\n"
    if fmt == "docx":
        from docx import Document
        from docx.shared import Pt, RGBColor

        doc = Document()
        doc.add_heading(f"{data['filename']}", level=1)
        doc.add_paragraph(f"{L[version]} · {len(segs)} {L['lines']}").runs[0].italic = True
        for s in segs:
            p = doc.add_paragraph()
            r = p.add_run(f"{s['speaker']}  ")
            r.bold = True
            t = p.add_run(f"[{ts(s['start'])} – {ts(s['end'])}]")
            t.font.size = Pt(8)
            t.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
            doc.add_paragraph(s["text"])
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()
    raise ValueError(f"unknown format {fmt}")
