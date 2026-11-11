"""Meeting analysis: exact stats + notes per chunk + one merge, all on the local LLM.

Files: jobs/<id>/analysis.json (result) and jobs/<id>/analysis/parts/<n>.json (notes per chunk,
reused on a rerun when the chunk text is the same). Progress lives in job["analysis"].
"""
from __future__ import annotations

import hashlib
import json
import math
import queue
import re
import threading
import time
import traceback

from . import store

CHUNK_TOKENS = 3000
MERGE_TOKENS = 6000
VERSION = 2
SHORT_SECONDS = 60  # a recording this short (or with fewer lines) gets no score and no person review
SHORT_LINES = 6

# ---------------- schemas ----------------
_S, _I, _N = {"type": "string"}, {"type": "integer"}, {"type": "number"}
_T = {"type": "string", "minLength": 20}  # a sentence, not a one-word rating


def _obj(**props):
    return {"type": "object", "properties": props, "required": list(props)}


def _arr(item):
    return {"type": "array", "items": item}


def _cap(item, n, least=0):  # upper bounds stop a small model from looping on a list
    return {**_arr(item), "maxItems": n, **({"minItems": least} if least else {})}


NOTES_SCHEMA = _obj(
    topics=_cap(_obj(title=_S, summary=_S, line=_I), 8, 1),
    decisions=_cap(_obj(text=_S, line=_I), 12),
    tasks=_cap(_obj(owner=_S, task=_S, due=_S, line=_I), 12),
    questions=_cap(_obj(asker=_S, text=_S, answered={"type": "boolean"}, line=_I), 10),
    people=_cap(_obj(name=_S, did=_S, got=_S), 10),
)
MERGE_SCHEMA = _obj(
    summary={"type": "string", "minLength": 40},
    people=_cap(_obj(name=_S, contribution=_T, gained=_T, evidence=_cap(_I, 6)), 12, 1),
    score=_obj(comment=_S, tips=_cap(_S, 3)),
)


def merge_schema(n: int) -> dict:
    """Exactly one people entry per speaker, so nobody is skipped."""
    people = {**MERGE_SCHEMA["properties"]["people"], "minItems": max(1, n), "maxItems": max(1, n)}
    return {**MERGE_SCHEMA, "properties": {**MERGE_SCHEMA["properties"], "people": people}}


DECISIONS_SCHEMA = _obj(decisions=_cap(_obj(text=_S, line=_I), 10))
DECISIONS_PROMPT = {
    "tr": """Aşağıda bir toplantı dökümünün bir bölümü var. Yalnızca KARARLARI çıkar.
- Karar: bir konuda netleşen, kesinleşen sonuçtur. Örnekler: "bildirimler dar kapsamlı olsun", "offline mod 2.5'e kaldı", "tarih iki hafta sonra Cuma", "tasarım değişikliği yok".
- Ertelenen ya da vazgeçilen şeyler de karardır.
- Birine iş vermek karar değil görevdir: onları yazma. Fikir, soru ve endişe de karar değildir.
- text: kararın kısa ve tam bir cümlesi. line: kararın verildiği satırın numarası.
Emin değilsen yazma.

Döküm:
{transcript}""",
    "en": """Below is one part of a meeting transcript. Extract only the DECISIONS.
- A decision is something that was settled. Examples: "keep notifications narrow", "offline mode moves to 2.5", "release date is Friday in two weeks", "no redesign".
- Things that were postponed or dropped are decisions too.
- Giving someone work is a task, not a decision: leave those out. Ideas, questions and worries are not decisions either.
- text: one short, complete sentence. line: the number of the line where it was decided.
Leave it out when unsure.

Transcript:
{transcript}""",
}

QUESTIONS_SCHEMA = _obj(results=_cap(_obj(line=_I, answered={"type": "boolean"}), 12))
QUESTIONS_PROMPT = {
    "tr": """Aşağıda bir toplantıdan sorular ve her sorudan hemen sonra konuşulan satırlar var.
Her soru için karar ver: sonraki satırlarda biri bu soruya net bir cevap verdi mi?
- answered = true: cevap verildi, ya da bu aslında bir soru değil (laf arası, onay isteme, görev verme).
- answered = false: gerçek bir soru ve cevapsız kaldı, geçiştirildi ya da "sonra bakarız" dendi.
line = sorunun satır numarası.

{blocks}""",
    "en": """Below are questions from a meeting, each followed by the lines spoken right after it.
Decide for each: did someone clearly answer it in the following lines?
- answered = true: it was answered, or it is not really a question (filler, asking for agreement, giving a task).
- answered = false: a real question that stayed unanswered, was brushed aside or postponed.
line = the line number of the question.

{blocks}""",
}

# ---------------- prompts ----------------
SYSTEM = {
    "tr": ("Sen bir toplantı analiz asistanısın. Yalnızca verilen konuşma dökümüne dayan; "
           "dökümde olmayan hiçbir şeyi uydurma. Satır numaralarını köşeli parantezdeki sayıdan al. "
           "Kısa ve net yaz. Cevabı Türkçe yaz."),
    "en": ("You are a meeting analysis assistant. Rely only on the given transcript; "
           "never invent anything that is not in it. Take line numbers from the number in square brackets. "
           "Write short and plain. Answer in English."),
}
NOTES_PROMPT = {
    "tr": """Aşağıda bir toplantının bir bölümünün dökümü var. Her satır: [satır no] [zaman] Konuşmacı: metin.

Şunları çıkar:
- topics: bu bölümde konuşulan konular (title kısa, summary 1 cümle, line: konunun başladığı satır no)
- decisions: net verilen kararlar. "olsun", "yapalım", "alıyoruz", "bırakalım", "ertelendi", "kesinleşti", "o zaman şöyle" gibi bir kapanışla bağlanan her karar; ertelenenler de karardır (text kısa ve tam, line)
- tasks: üstlenilen işler (owner: işi alan kişinin adı tam olarak dökümdeki gibi, bilinmiyorsa ""; task; due: söylenen tarih/süre, yoksa ""; line)
- questions: yalnızca önemli, gerçek sorular (laf arası "değil mi?", "tamam mı?" gibi olanları yazma). asker: soran kişinin adı; text: sorunun kendisi, kısa; answered: sonraki satırlarda biri net bir cevap verdiyse true, soru geçiştirildiyse ya da "sonra bakarız" dendiyse false; line
- people: bu bölümde konuşan herkes için did (ne katkı yaptı) ve got (bu bölümden ne aldı: aldığı cevaplar, netleşen şeyler ya da hiçbir şey; yoksa "")

Yalnızca dökümde geçenleri yaz. Emin değilsen listeyi boş bırak.

Döküm:
{transcript}""",
    "en": """Below is one part of a meeting transcript. Each line: [line no] [time] Speaker: text.

Extract:
- topics: what was discussed in this part (title short, summary 1 sentence, line: the line where the topic starts)
- decisions: every decision that was clearly made, including things postponed or dropped ("let's do", "we'll take", "push to", "agreed"); text short and complete, line
- tasks: work someone took on (owner: the person's name exactly as written in the transcript, "" if unknown; task; due: the date/time said, "" if none; line)
- questions: only real, important questions (skip fillers like "right?" or "ok?"). asker: name of who asked; text: the question itself, short; answered: true if someone gave a clear answer in the following lines, false if it was brushed aside or postponed; line
- people: for everyone who speaks in this part, did (what they contributed) and got (what they took away from this part: answers they got, things clarified, or nothing; "" if none)

Write only what appears in the transcript. When unsure, leave the list empty.

Transcript:
{transcript}""",
}
MERGE_PROMPT = {
    "tr": """Aşağıda bir toplantının bölüm notları (JSON) ve kesin istatistikleri var. Toplantının genel analizini yaz.

- summary: 3-6 cümlelik özet
- people: her konuşmacı için tam olarak bir kayıt. contribution: toplantıya ne kattığı, 1-2 cümleyle (puan ya da tek kelime değil). gained: bu kişinin kendisi için toplantıdan ne aldığı (sorduğu sorulara aldığı cevaplar, onun için netleşen şeyler, üstüne aldığı işler; sorusu cevapsız kaldıysa bunu yaz). Her kişi için farklı ve o kişiye özel yaz, aynı cümleyi tekrarlama. evidence: bunu gösteren satır numaraları
- score: comment (toplantının nasıl geçtiğine dair 1-2 cümle; sayı verme), tips (bir dahaki toplantı için en çok 3 kısa, somut öneri)

Yalnızca notlara dayan. Adları notlardaki gibi yaz.

Konuşmacılar: {names}

İstatistikler:
{stats}

Notlar:
{notes}""",
    "en": """Below are the part notes (JSON) of a meeting and its exact statistics. Write the overall analysis.

- summary: 3-6 sentences
- people: exactly one entry per speaker. contribution: what they added to the meeting, in 1-2 sentences (not a rating or a single word). gained: what this person personally took away (answers to their own questions, what became clear for them, work they took on; say so if their question stayed unanswered). Write it specifically for each person, never the same sentence twice. evidence: line numbers that show it
- score: comment (1-2 sentences on how the meeting went; give no numbers), tips (at most 3 short, concrete tips for the next meeting)

Rely only on the notes. Write names as in the notes.

Speakers: {names}

Statistics:
{stats}

Notes:
{notes}""",
}


# ---------------- helpers ----------------
class _Cancelled(Exception):
    pass


def _is_cancel(e: Exception) -> bool:
    return isinstance(e, _Cancelled) or type(e).__name__ == "Cancelled"


def _tokens(text: str) -> int:
    try:
        from . import llm

        return llm.approx_tokens(text)
    except ImportError:
        return len(text) // 3


def _lang(job: dict) -> str:
    return "tr" if job.get("language") == "tr" else "en"


def _text(seg: dict) -> str:
    return (seg.get("text_edited") or seg.get("text_original") or "").strip()


def _clock(t: float) -> str:
    t = int(t)
    return f"{t // 60:02d}:{t % 60:02d}"


def transcript_hash(segments: list[dict]) -> str:
    raw = json.dumps([[s["id"], s["speaker"], _text(s)] for s in segments], ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def render(segments: list[dict], speakers: dict) -> list[str]:
    """One line per segment: [id] [mm:ss-mm:ss] Name: text."""
    return [f"[{s['id']}] [{_clock(s['start'])}-{_clock(s['end'])}] "
            f"{speakers.get(str(s['speaker']), 'Speaker ' + str(s['speaker'] + 1))}: {_text(s)}"
            for s in segments]


def chunk_lines(lines: list[str], limit: int | None = None) -> list[list[str]]:
    """Group lines into chunks of about `limit` tokens; a line is never split."""
    limit = limit or CHUNK_TOKENS
    chunks, cur, size = [], [], 0
    for ln in lines:
        n = _tokens(ln) + 1
        if cur and size + n > limit:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(ln)
        size += n
    if cur:
        chunks.append(cur)
    return chunks


def stats(segments: list[dict], speakers: dict) -> dict:
    per: dict[int, dict] = {}
    turns: list[tuple[int, float, float]] = []  # (speaker, start, end) of consecutive same-speaker runs
    for s in segments:
        spk = s["speaker"]
        d = per.setdefault(spk, {"id": spk, "name": speakers.get(str(spk), f"Speaker {spk + 1}"),
                                 "seconds": 0.0, "turns": 0, "words": 0, "questions": 0, "longest_turn": 0.0})
        d["seconds"] += max(0.0, s["end"] - s["start"])
        d["words"] += len(_text(s).split())
        d["questions"] += "?" in _text(s)
        if turns and turns[-1][0] == spk:
            turns[-1] = (spk, turns[-1][1], s["end"])
        else:
            turns.append((spk, s["start"], s["end"]))
    for spk, a, b in turns:
        per[spk]["turns"] += 1
        per[spk]["longest_turn"] = max(per[spk]["longest_turn"], b - a)
    total = sum(d["seconds"] for d in per.values())
    n = len(per)
    shares = [d["seconds"] / total for d in per.values()] if total else []
    if n < 2 or not total:
        balance = 1.0
    else:
        balance = -sum(p * math.log(p) for p in shares if p > 0) / math.log(n)
    out = []
    for spk in sorted(per):
        d = per[spk]
        d.update(share=round(d["seconds"] / total, 3) if total else 0.0,
                 seconds=round(d["seconds"], 1), longest_turn=round(d["longest_turn"], 1))
        out.append(d)
    return {"duration": round(max((s["end"] for s in segments), default=0.0), 1),
            "balance": round(balance, 3), "speakers": out}


def _norm(s: str) -> str:
    return re.sub(r"[\W_]+", " ", store._fold(str(s))).strip()


def _name_map(*speaker_dicts: dict) -> dict[str, int]:
    m: dict[str, int] = {}
    for sp in speaker_dicts:
        for k, v in sp.items():
            if v:
                m.setdefault(_norm(v), int(k))
    return m


def _to_id(name, names: dict[str, int], valid: set[int]):
    n = _norm(name or "")
    if not n:
        return None
    if n in names:
        return names[n]
    m = re.fullmatch(r"(?:speaker|konu[sş]maci)\s*(\d+)", n)
    if m and int(m.group(1)) - 1 in valid:
        return int(m.group(1)) - 1
    return None


def _clamp(v) -> int:
    try:
        return max(0, min(100, int(round(float(v)))))
    except (TypeError, ValueError):
        return 0


def _ints(v, ids: set[int]) -> list[int]:
    out = []
    for x in v or []:
        try:
            x = int(x)
        except (TypeError, ValueError):
            continue
        if x in ids and x not in out:
            out.append(x)
    return out


def _dedupe(items: list[dict], key: str) -> list[dict]:
    seen, out = set(), []
    for it in items:
        k = _norm(it[key])
        if k and k not in seen:
            seen.add(k)
            out.append(it)
    return out


def _words(text: str) -> set[str]:
    """Words of four letters or more, cut to five letters: Turkish endings (planı, planını, plana) then match."""
    return {w[:5] for w in re.findall(r"\w+", _norm(text)) if len(w) > 3}


def _snap(ln, text: str, segments: list[dict], pos: dict[int, int]):
    """Small models cite a line a few places off. Of the lines around the cited one, take the one that
    shares the most words with the item (the cited line wins a tie). Returns a segment id or None."""
    try:
        ln = int(ln)
    except (TypeError, ValueError):
        return None
    if ln not in pos:
        return None
    w = _words(text)
    if not w:
        return ln
    i, best, best_n = pos[ln], ln, len(w & _words(_text(segments[pos[ln]])))
    for j in range(max(0, i - 4), min(len(segments), i + 5)):
        n = len(w & _words(_text(segments[j])))
        if n > best_n:
            best, best_n = segments[j]["id"], n
    return best


_NUM = re.compile(r"\d+(?:[.,]\d+)+|\d{3,}")


def _numbers(text: str) -> set[str]:
    return {m.replace(",", ".") for m in _NUM.findall(text)}


def _grounded(text: str, known: set[str]) -> bool:
    """False when the text names a version / amount / year that is nowhere in the recording."""
    return _numbers(text) <= known


def _drop_ungrounded(text: str, known: set[str]) -> str:
    """Sentences that carry an invented number are removed (a small model once wrote "2.3" for "2.4")."""
    if _grounded(text, known):
        return text
    parts = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(x for x in parts if _grounded(x, known)).strip()


def repetition_score(segments: list[dict]):
    """100 = nothing is said twice. A line counts as a repeat when it shares most of its words with one of
    the previous 30 lines. None when the recording is too short to tell."""
    toks = [_words(_text(s)) for s in segments]
    seen = dup = 0
    for i, t in enumerate(toks):
        if len(t) < 4:
            continue
        seen += 1
        for u in toks[max(0, i - 30):i]:
            if len(u) >= 4 and len(t & u) / min(len(t), len(u)) >= 0.7:
                dup += 1
                break
    return round(100 * (1 - dup / seen)) if seen >= 5 else None


def compute_score(st: dict, segments: list[dict], decisions: list, tasks: list, open_qs: list, n_questions: int) -> dict:
    """The numbers come from the transcript, not from the model: a small model rates every meeting 85-98.
    Each part is 0-100 or None when there is nothing to judge."""
    minutes = max(st["duration"] / 60, 1 / 6)
    target = min(8, max(1, minutes / 5))  # about one decision per five minutes, at most eight expected
    parts = {"decisions": min(100, round(100 * len(decisions) / target))}
    parts["tasks"] = (round(100 * sum(0.6 * (t["owner"] is not None) + 0.4 * bool(t["due"]) for t in tasks) / len(tasks))
                      if tasks else None)
    parts["questions"] = round(100 * (1 - min(len(open_qs), n_questions) / n_questions)) if n_questions else None
    parts["repetition"] = repetition_score(segments)
    parts["balance"] = round(st["balance"] * 100) if len(st["speakers"]) > 1 else None
    have = [v for v in parts.values() if v is not None]
    parts["overall"] = round(sum(have) / len(have)) if have else None
    return parts


def _echo(text: str, templates: str) -> bool:
    """A small model sometimes copies the instruction instead of answering it."""
    n = _norm(text)
    return len(n) >= 8 and n in templates


def _from_notes(notes: list[dict], names: dict[str, int], valid: set[int], key: str, templates: str) -> dict[int, str]:
    """Per speaker, what the part notes say (did / got): used when the final call left a card empty."""
    out: dict[int, list[str]] = {}
    for n in notes:
        for p in (n.get("people") or []) if isinstance(n, dict) else []:
            spk = _to_id(p.get("name"), names, valid) if isinstance(p, dict) else None
            t = str(p.get(key, "")).strip() if spk is not None else ""
            if t and not _echo(t, templates) and t not in out.setdefault(spk, []):
                out[spk].append(t)
    return {k: " ".join(v[:4]) for k, v in out.items()}


def postprocess(raw: dict, segments: list[dict], st: dict, names: dict[str, int],
                notes: list[dict] | None = None, lang: str = "en") -> dict:
    """Repair what small models get wrong: bad line ids, names, scores, missing people, echoed instructions."""
    templates = _norm(" ".join((NOTES_PROMPT[lang], MERGE_PROMPT[lang], QUESTIONS_PROMPT[lang], SYSTEM[lang])))

    known: set[str] = set()

    def clean(v) -> str:
        v = str(v or "").strip()
        return "" if _echo(v, templates) else _drop_ungrounded(v, known)

    for key, field in (("decisions", "text"), ("tasks", "task"), ("open_questions", "text"), ("topics", "title")):
        raw = {**raw, key: [r for r in (raw.get(key) or []) if isinstance(r, dict) and clean(r.get(field))]}
    by_id = {s["id"]: s for s in segments}
    ids = set(by_id)
    valid = {d["id"] for d in st["speakers"]}

    pos = {sg["id"]: i for i, sg in enumerate(segments)}
    known |= _numbers(" ".join(_text(sg) for sg in segments)) | {f"{st['duration'] / 60:.1f}"}

    def line(x, text=""):
        return _snap(x, text, segments, pos)

    def keep(text: str) -> bool:
        return bool(text) and _grounded(text, known)

    def rows(key):
        return [r for r in (raw.get(key) or []) if isinstance(r, dict)]

    topics = []
    for t in rows("topics"):
        ln = line(t.get("line"), str(t.get("title", "")) + " " + str(t.get("summary", "")))
        if ln is not None and str(t.get("title", "")).strip():
            topics.append({"title": str(t["title"]).strip(), "summary": _drop_ungrounded(str(t.get("summary", "")).strip(), known),
                           "start": by_id[ln]["start"], "end": 0.0, "line": ln})
    topics = sorted(_dedupe(topics, "title"), key=lambda t: t["start"])
    if topics:  # the first topic covers the meeting from its start
        topics[0]["start"] = min(x["start"] for x in segments)
    for i, t in enumerate(topics):
        t["end"] = topics[i + 1]["start"] if i + 1 < len(topics) else st["duration"]

    decisions = _dedupe([{"text": str(d.get("text", "")).strip(), "line": line(d.get("line"), str(d.get("text", "")))}
                         for d in rows("decisions")], "text")
    decisions = [d for d in decisions if d["line"] is not None and keep(d["text"])]
    tasks = _dedupe([{"owner": _to_id(t.get("owner"), names, valid), "task": str(t.get("task", "")).strip(),
                      "due": str(t.get("due", "") or "").strip(),
                      "line": line(t.get("line"), str(t.get("task", "")))}
                     for t in rows("tasks")], "task")
    tasks = [t for t in tasks if t["line"] is not None and keep(t["task"])]
    oq = _dedupe([{"asker": _to_id(q.get("asker"), names, valid), "text": str(q.get("text", "")).strip(),
                   "line": line(q.get("line"), str(q.get("text", "")))} for q in rows("open_questions")], "text")
    oq = [q for q in oq if q["line"] is not None and keep(q["text"])]

    found = {}
    for p in rows("people"):
        spk = _to_id(p.get("name"), names, valid)
        if spk is not None and spk not in found:
            found[spk] = p
    did = _from_notes(notes or [], names, valid, "did", templates)
    got = _from_notes(notes or [], names, valid, "got", templates)
    people = []
    for d in st["speakers"]:
        p = found.get(d["id"], {})
        people.append({"id": d["id"], "contribution": clean(p.get("contribution")) or did.get(d["id"], ""),
                       "gained": clean(p.get("gained")) or got.get(d["id"], ""),
                       "evidence": _ints(p.get("evidence"), ids)})

    sc = raw.get("score") if isinstance(raw.get("score"), dict) else {}
    score = compute_score(st, segments, decisions, tasks, oq, int(raw.get("n_questions") or 0))
    score["comment"] = clean(sc.get("comment"))
    score["tips"] = [clean(t) for t in (sc.get("tips") or []) if clean(t)][:5]
    return {"summary": clean(raw.get("summary")), "topics": topics, "decisions": decisions,
            "tasks": tasks, "open_questions": oq, "people": people, "score": score}


# ---------------- the run ----------------
def _set(job_id: str, **fields) -> None:
    job = store.read_transcript(job_id)
    store.update_job(job_id, analysis={**(job.get("analysis") or {}), **fields})


def _compact(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def collect(notes: list[dict]) -> dict:
    """Lists are taken from the part notes as they are: a small model drops rows when asked to copy them."""
    out = {"topics": [], "decisions": [], "tasks": [], "open_questions": [], "n_questions": 0}
    for n in notes:
        if not isinstance(n, dict):
            continue
        for k in ("topics", "decisions", "tasks"):
            out[k] += [r for r in (n.get(k) or []) if isinstance(r, dict)]
        out["n_questions"] += len([q for q in (n.get("questions") or []) if isinstance(q, dict)])
        out["open_questions"] += [q for q in (n.get("questions") or [])
                                  if isinstance(q, dict) and q.get("answered") is False]
    return out


def verify_questions(open_qs: list[dict], segments: list[dict], speakers: dict, lang: str, call) -> list[dict]:
    """Second look at each 'unanswered' question with the lines that follow it: the part notes
    over-report them. Keeps a question when the check itself says nothing about it."""
    order = {s["id"]: i for i, s in enumerate(segments)}
    lines = render(segments, speakers)
    cands = [q for q in open_qs if q.get("line") in order][:30]
    verdict: dict[int, bool] = {}
    for i in range(0, len(cands), 10):
        blocks = []
        for q in cands[i:i + 10]:
            k = order[q["line"]]
            blocks.append("\n".join(lines[k:k + 7]))
        out = call(QUESTIONS_PROMPT[lang].format(blocks="\n\n---\n\n".join(blocks)), QUESTIONS_SCHEMA, max_tokens=600)
        for r in (out.get("results") if isinstance(out, dict) else None) or []:
            if isinstance(r, dict) and isinstance(r.get("answered"), bool):
                verdict[r.get("line")] = r["answered"]
    return [q for q in open_qs if not verdict.get(q.get("line"), False)]


def merge_decisions(a: list[dict], b: list[dict]) -> list[dict]:
    """Union of two decision lists; a decision that says nearly the same as one already there is skipped."""
    out = [d for d in a if isinstance(d, dict)]
    for d in b:
        if not isinstance(d, dict):
            continue
        w = _words(str(d.get("text", "")))
        if not w or any(len(w & _words(str(o.get("text", "")))) / min(len(w), len(_words(str(o.get("text", ""))) or w)) >= 0.6
                        for o in out):
            continue
        out.append(d)
    return out


def drop_task_like(decisions: list[dict], tasks: list[dict]) -> list[dict]:
    """A decision that only restates a task ("Test planı Deniz'e verildi") is a task, not a decision."""
    tw = [_words(str(t.get("task", ""))) for t in tasks]
    out = []
    for d in decisions:
        w = _words(d["text"])
        if w and any(t and len(w & t) / len(w) >= 0.5 for t in tw):
            continue
        out.append(d)
    return out


def digest(notes: list[dict], open_qs: list[dict] | None = None) -> str:
    """What the final call reads. Shortened when a long meeting would not fit."""
    c = collect(notes)
    if open_qs is not None:
        c["open_questions"] = open_qs

    def build(cut):
        d = {"topics": [t.get("title", "") + (": " + str(t.get("summary", ""))[:cut] if cut else "") for t in c["topics"]],
             "decisions": [[d.get("line"), d.get("text", "")] for d in c["decisions"]],
             "tasks": [[t.get("line"), t.get("owner", ""), t.get("task", "")] for t in c["tasks"]],
             "open_questions": [[q.get("line"), q.get("asker", ""), q.get("text", "")] for q in c["open_questions"]],
             "people": [[p.get("name", ""), str(p.get("did", ""))[:cut or 80], str(p.get("got", ""))[:cut or 80]]
                        for n in notes if isinstance(n, dict) for p in (n.get("people") or []) if isinstance(p, dict)]}
        return _compact(d)

    for cut in (400, 160, 0):
        text = build(cut)
        if _tokens(text) <= MERGE_TOKENS:
            break
    return text


def run(job_id: str, cancel: threading.Event | None = None, generate=None) -> dict:
    """Blocking. Returns the job's analysis state; never raises."""
    t0 = time.time()
    try:
        _run(job_id, cancel, generate, t0)
    except Exception as e:
        if _is_cancel(e) or (cancel is not None and cancel.is_set()):
            _set(job_id, state="cancelled", error="")
        else:
            traceback.print_exc()
            _set(job_id, state="error", error=(str(e) or type(e).__name__)[:300])
    return store.read_transcript(job_id).get("analysis") or {}


def _run(job_id: str, cancel, generate, t0: float) -> None:
    if generate is None:
        try:
            from . import llm
        except ImportError:
            raise RuntimeError("LLM engine is not available") from None
        generate = llm.generate

    def check():
        if cancel is not None and cancel.is_set():
            raise _Cancelled()

    def call(prompt, schema, max_tokens=2048):
        check()
        return generate(prompt, schema=schema, system=SYSTEM[LANG], max_tokens=max_tokens, cancel=cancel)

    try:  # the speech model sits on the card after a transcription; the analysis model needs that room
        from . import asr

        asr.release()
    except Exception:
        pass
    job = store.read_transcript(job_id)
    segments, speakers = job.get("segments") or [], dict(job.get("speakers") or {})
    if not segments:
        raise ValueError("no speech to analyse")
    LANG = _lang(job)
    ana_dir = store.job_path(job_id) / "analysis"
    (ana_dir / "parts").mkdir(parents=True, exist_ok=True)

    _set(job_id, state="running", stage="stats", progress=0.0, part=0, parts=0, error="")
    suggestions = []
    duration = max((sg["end"] for sg in segments), default=0.0) - min((sg["start"] for sg in segments), default=0.0)
    short = duration < SHORT_SECONDS or len(segments) < SHORT_LINES
    warnings: list[str] = []
    _set(job_id, stage="names")
    try:
        from . import names, names_llm

        check()
        if short or not any(names._is_default(speakers.get(str(k)), int(k)) for k in {sg["speaker"] for sg in segments}):
            raise ImportError  # nothing to look for (or too little speech to trust a guess)
        gen = lambda *a, **k: generate(*a, **{**k, "cancel": cancel})  # noqa: E731
        llm_found = names_llm.suggest(segments, speakers, gen, lang=LANG)
        rule = names.detect_names(segments, speakers)
        auto, suggestions = names_llm.combine(rule, llm_found, job.get("voice_matches") or {})
        for k, v in auto.items():
            if names._is_default(speakers.get(str(k)), int(k)):
                speakers[str(k)] = v
        if speakers != job.get("speakers"):
            store.update_job(job_id, speakers=speakers)
    except ImportError:
        pass
    except Exception as e:
        if _is_cancel(e):
            raise
        traceback.print_exc()  # names are a bonus: the analysis goes on without them
    check()

    st = stats(segments, speakers)
    chunks = chunk_lines(render(segments, speakers))
    total = len(chunks) + 2  # notes parts (+ decision pass) + question check + final call
    _set(job_id, stage="notes", parts=len(chunks), progress=0.0)

    notes = []
    extra_decisions: list[list] = []
    last_error = ""
    for i, ch in enumerate(chunks):
        check()
        text = "\n".join(ch)
        h = hashlib.sha1((LANG + text).encode("utf-8")).hexdigest()
        f = ana_dir / "parts" / f"{i}.json"
        saved = None
        if f.exists():
            try:
                saved = json.loads(f.read_text("utf-8"))
            except ValueError:
                pass
        if saved and saved.get("hash") == h and "decisions" in saved:
            notes.append(saved["notes"])
            extra_decisions.append(saved["decisions"])
        else:
            try:
                n = call(NOTES_PROMPT[LANG].format(transcript=text), NOTES_SCHEMA, max_tokens=3000)
            except Exception as e:
                if _is_cancel(e):
                    raise
                traceback.print_exc()
                warnings.append(f"part {i + 1}/{len(chunks)} could not be analysed")
                last_error = str(e).strip()[:300]
                n = {}
            else:
                dd: list = []
                try:  # a second, single-purpose look: small models miss decisions when asked for everything at once
                    got = call(DECISIONS_PROMPT[LANG].format(transcript=text), DECISIONS_SCHEMA, max_tokens=900)
                    dd = got.get("decisions") or [] if isinstance(got, dict) else []
                except Exception as e:
                    if _is_cancel(e):
                        raise
                    traceback.print_exc()
                f.write_text(json.dumps({"hash": h, "notes": n, "decisions": dd}, ensure_ascii=False), "utf-8")
                extra_decisions.append(dd)
            notes.append(n)
        _set(job_id, part=i + 1, progress=round((i + 1) / total, 3))

    if not any(notes):
        raise RuntimeError("the model could not analyse the recording: " + last_error)
    _set(job_id, stage="merge")
    found = collect(notes)
    for dd in extra_decisions:
        found["decisions"] = merge_decisions(found["decisions"], dd)
    try:
        found["open_questions"] = verify_questions(found["open_questions"], segments, speakers, LANG, call)
    except Exception as e:
        if _is_cancel(e):
            raise
        traceback.print_exc()  # keep the unchecked list
    _set(job_id, progress=round((len(chunks) + 1) / total, 3))
    shown = ", ".join(sp["name"] for sp in st["speakers"])
    merge_stats = {"duration": st["duration"], "balance": st["balance"],
                   "speakers": [{k: sp[k] for k in ("name", "share", "turns", "words", "questions")}
                                for sp in st["speakers"]]}
    try:
        raw = call(MERGE_PROMPT[LANG].format(names=shown, stats=_compact(merge_stats), notes=digest(notes, found["open_questions"])),
                   merge_schema(len(st["speakers"])))
    except Exception as e:
        if _is_cancel(e):
            raise
        traceback.print_exc()
        warnings.append("the summary could not be written")
        raw = {}
    names_map = _name_map(speakers, job.get("speakers") or {})
    raw = raw if isinstance(raw, dict) else {}
    if not str(raw.get("summary") or "").strip():  # fallback: the topic summaries, in order
        raw["summary"] = " ".join(str(t.get("summary", "")).strip() for t in found["topics"][:6] if isinstance(t, dict))[:700]
    result = postprocess({**raw, **found}, segments, st, names_map, notes, LANG)
    result["decisions"] = drop_task_like(result["decisions"], result["tasks"])
    result["score"] = {**result["score"], **{k: v for k, v in compute_score(
        st, segments, result["decisions"], result["tasks"], result["open_questions"], found["n_questions"]).items()}}
    if short:  # too little to judge: no score, no review of the people, only what was said
        result["score"] = {k: None for k in ("overall", "decisions", "tasks", "questions", "repetition", "balance")} | {"comment": "", "tips": []}
        for pp in result["people"]:
            pp["contribution"] = pp["gained"] = ""
            pp["evidence"] = []

    model = device = ""
    try:
        from . import llm

        p = llm.plan()
        model, device = p.get("model", ""), p.get("device", "")
    except Exception:
        pass
    result = {"version": VERSION, "model": model, "device": device, "lang": LANG, "created": time.time(),
              "seconds": round(time.time() - t0, 1), "transcript_hash": transcript_hash(segments),
              "stats": st, **result, "short": short, "warnings": warnings, "name_suggestions": suggestions}
    (store.job_path(job_id) / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
    _set(job_id, state="done", stage="merge", progress=1.0, error="")


# ---------------- background worker ----------------
_q: queue.Queue = queue.Queue()
_events: dict[str, threading.Event] = {}
_worker: threading.Thread | None = None
_wlock = threading.Lock()


def _loop() -> None:
    while True:
        job_id = _q.get()
        ev = _events.get(job_id) or threading.Event()
        try:
            run(job_id, ev)
        finally:
            _events.pop(job_id, None)


def llm_ready() -> bool:
    try:
        from . import llm

        return bool(llm.available())
    except Exception:
        return False


def start(job_id: str) -> dict:
    global _worker
    job = store.read_transcript(job_id)
    if not llm_ready():
        return {"ok": False, "error": "llm_not_ready"}
    if not job.get("segments"):
        return {"ok": False, "error": "no_speech"}
    with _wlock:
        if job_id in _events:  # already queued or running
            return {"ok": True}
        _events[job_id] = threading.Event()
        store.update_job(job_id, analysis={"state": "queued", "stage": "stats", "progress": 0.0,
                                           "part": 0, "parts": 0, "error": ""})
        _q.put(job_id)
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_loop, daemon=True)
            _worker.start()
    return {"ok": True}


def cancel(job_id: str) -> dict:
    ev = _events.get(job_id)
    if ev:
        ev.set()
    return {"ok": True}


def status(job_id: str) -> dict:
    job = store.read_transcript(job_id)
    a = job.get("analysis") or {}
    f = store.job_path(job_id) / "analysis.json"
    saved = None
    if f.exists():
        try:
            saved = json.loads(f.read_text("utf-8"))
        except ValueError:
            pass
    state = a.get("state") or ("done" if saved else "none")
    if state == "done" and saved and saved.get("transcript_hash") != transcript_hash(job.get("segments") or []):
        state = "stale"
    return {"state": state, "stage": a.get("stage", ""), "progress": a.get("progress", 0.0),
            "part": a.get("part", 0), "parts": a.get("parts", 0), "error": a.get("error", ""),
            "analysis": saved, "llm_ready": llm_ready()}
