"""Align Whisper words with diarization turns and build transcript segments."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Word:
    start: float
    end: float
    text: str
    prob: float = 1.0  # how sure the speech model was about this word (0-1)


@dataclass
class Turn:
    start: float
    end: float
    speaker: int  # 0-based


def _speaker_for(word: Word, turns: list[Turn]) -> int:
    """Speaker with max time overlap; falls back to the nearest turn."""
    best, best_ov = None, 0.0
    for t in turns:
        ov = min(word.end, t.end) - max(word.start, t.start)
        if ov > best_ov:
            best, best_ov = t.speaker, ov
    if best is not None:
        return best
    if not turns:
        return 0
    mid = (word.start + word.end) / 2
    return min(turns, key=lambda t: min(abs(mid - t.start), abs(mid - t.end))).speaker


def assign_speakers(words: list[Word], turns: list[Turn]) -> list[int]:
    return [_speaker_for(w, turns) for w in words]


def sentences(words: list[Word], max_gap: float = 0.7, max_len: float = 12.0) -> list[tuple[int, int]]:
    """Word index ranges [i, j) of sentences: split on . ? ! , long pauses or max length."""
    out, i = [], 0
    for k, w in enumerate(words):
        last = k == len(words) - 1
        end_punct = w.text.strip()[-1:] in ".?!…"
        gap = not last and words[k + 1].start - w.end > max_gap
        too_long = w.end - words[i].start > max_len
        if last or end_punct or gap or too_long:
            out.append((i, k + 1))
            i = k + 1
    return out


def build_segments(
    words: list[Word],
    turns: list[Turn],
    max_gap: float = 1.5,
    max_len: float = 30.0,
    speakers: list[int] | None = None,
    margins: list[float] | None = None,
) -> list[dict]:
    """Group words into segments; split on speaker change, long pause or max length.
    margins: per word, how sure the speaker decision was (see diarize.refine_by_sentence)."""
    if speakers is None:
        speakers = assign_speakers(words, turns)
    segments: list[dict] = []
    cur: dict | None = None
    for n, (w, spk) in enumerate(zip(words, speakers)):
        if (
            cur is None
            or spk != cur["speaker"]
            or w.start - cur["end"] > max_gap
            or w.end - cur["start"] > max_len
        ):
            cur = {"start": w.start, "end": w.end, "speaker": spk, "text": "", "words": [], "margins": []}
            segments.append(cur)
        cur["text"] += w.text
        cur["end"] = w.end
        cur["words"].append([round(w.start, 2), round(w.end, 2), w.text, round(w.prob, 2)])
        if margins is not None and n < len(margins) and margins[n] < 1.0:
            cur["margins"].append(margins[n])
    out = []
    for i, s in enumerate(segments):
        text = s["text"].strip()
        if not text:
            continue
        probs = [(w[1] - w[0], w[3]) for w in s["words"] if len(w) > 3]
        tot = sum(d for d, _ in probs)
        out.append(
            {
                "id": i,
                "start": round(s["start"], 2),
                "end": round(s["end"], 2),
                "speaker": s["speaker"],
                "text_original": text,
                "text_edited": text,
                "words": s["words"],  # [start, end, text, probability] - used to time a split precisely
                # text confidence: time-weighted mean word probability, and how many words were doubtful
                **({"conf": round(sum(d * p for d, p in probs) / tot, 3) if tot > 0 else 1.0,
                    "low_words": sum(1 for w in s["words"] if len(w) > 3 and w[3] < 0.25 and len(w[2].strip()) > 3)} if probs else {}),
                # speaker confidence: the smallest margin in the line (small or negative = another voice was as close)
                **({"spk_conf": round(min(s["margins"]), 3)} if s["margins"] else {}),
            }
        )
    for i, s in enumerate(out):
        s["id"] = i
    return out


def _snap(text: str, i: int) -> int:
    """Move a char offset to the nearest word boundary."""
    i = max(0, min(len(text), i))
    if i in (0, len(text)) or text[i - 1].isspace() or text[i].isspace():
        return i
    left = text.rfind(" ", 0, i)
    right = text.find(" ", i)
    left = 0 if left < 0 else left
    right = len(text) if right < 0 else right
    return left if i - left <= right - i else right


def _word_spans(seg: dict) -> list[tuple[int, int, float, float]] | None:
    """Char spans of each word inside text_original, or None if unavailable."""
    words = seg.get("words")
    if not words:
        return None
    raw = "".join(w[2] for w in words)
    lead = len(raw) - len(raw.lstrip())
    spans, pos = [], 0
    for w in words:
        ws, we, wt = w[0], w[1], w[2]
        spans.append((pos - lead, pos - lead + len(wt), ws, we))
        pos += len(wt)
    return spans


def split_segment(seg: dict, a: int, b: int, speaker: int, next_id: int) -> list[dict]:
    """Split seg so that text_edited[a:b] becomes its own segment for `speaker`.

    Times come from word timestamps when the text is unedited, otherwise they are
    interpolated by character position. The original (model) text is split the same way.
    """
    text = seg["text_edited"]
    a, b = _snap(text, a), _snap(text, b)
    if b <= a:
        return [seg]
    unedited = text == seg["text_original"]
    spans = _word_spans(seg) if unedited else None
    dur = seg["end"] - seg["start"]

    def t_at(ci: int) -> float:
        if spans:
            for s0, s1, ws, we in spans:
                if ci < s1:
                    return ws if ci <= s0 or ci - s0 < s1 - ci else we
            return seg["end"]
        return seg["start"] + dur * ci / max(len(text), 1)

    def orig_slice(c0: int, c1: int) -> str:
        if unedited:
            return text[c0:c1]
        o = seg["text_original"]
        r = len(o) / max(len(text), 1)
        return o[_snap(o, round(c0 * r)):_snap(o, round(c1 * r))]

    out = []
    for c0, c1, spk in ((0, a, seg["speaker"]), (a, b, speaker), (b, len(text), seg["speaker"])):
        part = text[c0:c1].strip()
        if not part:
            continue
        t0 = seg["start"] if c0 == 0 else t_at(c0)
        t1 = seg["end"] if c1 == len(text) else t_at(c1)
        words = [w for (s0, s1, *_), w in zip(spans or [], seg.get("words") or [])
                 if c0 <= (s0 + s1) / 2 < c1]
        out.append({
            "id": None, "start": round(t0, 2), "end": round(max(t1, t0), 2), "speaker": spk,
            "text_original": orig_slice(c0, c1).strip(), "text_edited": part, "words": words,
        })
    out[0]["id"] = seg["id"]
    for s in out[1:]:
        s["id"] = next_id
        next_id += 1
    return out
