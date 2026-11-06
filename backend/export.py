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
