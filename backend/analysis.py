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
VERSION = 1

# ---------------- schemas ----------------
_S, _I, _N = {"type": "string"}, {"type": "integer"}, {"type": "number"}
_T = {"type": "string", "minLength": 20}  # a sentence, not a one-word rating


def _obj(**props):
    return {"type": "object", "properties": props, "required": list(props)}


def _arr(item):
    return {"type": "array", "items": item}


NOTES_SCHEMA = _obj(
    topics={**_arr(_obj(title=_S, summary=_S, line=_I)), "minItems": 1},
    decisions=_arr(_obj(text=_S, line=_I)),
    tasks=_arr(_obj(owner=_S, task=_S, due=_S, line=_I)),
    questions=_arr(_obj(asker=_S, text=_S, answered={"type": "boolean"}, line=_I)),
    people=_arr(_obj(name=_S, did=_S, got=_S)),
)
MERGE_SCHEMA = _obj(
    summary=_S,
    people={**_arr(_obj(name=_S, contribution=_T, gained=_T, evidence=_arr(_I))), "minItems": 1},
    score=_obj(decisions=_I, focus=_I, repetition=_I, comment=_S, tips=_arr(_S)),
)

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
- decisions: net verilen kararlar (text, line)
- tasks: üstlenilen işler (owner: işi alan kişinin adı tam olarak dökümdeki gibi, bilinmiyorsa ""; task; due: söylenen tarih/süre, yoksa ""; line)
- questions: sorulan sorular (asker: soran kişinin adı; text; answered: bu bölümde cevaplandı mı; line)
- people: bu bölümde konuşan herkes için did (ne katkı yaptı) ve got (bu bölümden ne aldı: aldığı cevaplar, netleşen şeyler ya da hiçbir şey; yoksa "")

Yalnızca dökümde geçenleri yaz. Emin değilsen listeyi boş bırak.

Döküm:
{transcript}""",
    "en": """Below is one part of a meeting transcript. Each line: [line no] [time] Speaker: text.

Extract:
- topics: what was discussed in this part (title short, summary 1 sentence, line: the line where the topic starts)
- decisions: decisions that were clearly made (text, line)
- tasks: work someone took on (owner: the person's name exactly as written in the transcript, "" if unknown; task; due: the date/time said, "" if none; line)
- questions: questions that were asked (asker: name of who asked; text; answered: whether it was answered in this part; line)
- people: for everyone who speaks in this part, did (what they contributed) and got (what they took away from this part: answers they got, things clarified, or nothing; "" if none)

Write only what appears in the transcript. When unsure, leave the list empty.

Transcript:
{transcript}""",
}
MERGE_PROMPT = {
    "tr": """Aşağıda bir toplantının bölüm notları (JSON) ve kesin istatistikleri var. Toplantının genel analizini yaz.

- summary: 3-6 cümlelik özet
- people: her konuşmacı için tam olarak bir kayıt. contribution: toplantıya ne kattığı, 1-2 cümleyle (puan ya da tek kelime değil). gained: bu kişinin toplantıdan ne aldığı (aldığı cevaplar, netleşen şeyler ya da hiçbir şey). evidence: bunu gösteren satır numaraları
- score: decisions (kararlar ne kadar net, 0-100), focus (konuda kalma, 0-100), repetition (tekrarın azlığı, 100 = hiç tekrar yok), comment (1-2 cümle), tips (en çok 3 kısa öneri)

Yalnızca notlara dayan. Adları notlardaki gibi yaz.

Konuşmacılar: {names}

İstatistikler:
{stats}

Notlar:
{notes}""",
    "en": """Below are the part notes (JSON) of a meeting and its exact statistics. Write the overall analysis.

- summary: 3-6 sentences
- people: exactly one entry per speaker. contribution: what they added to the meeting, in 1-2 sentences (not a rating or a single word). gained: what this person took away from the meeting (answers they got, things clarified, or nothing). evidence: line numbers that show it
- score: decisions (how clear the decisions are, 0-100), focus (staying on topic, 0-100), repetition (how little repetition, 100 = none), comment (1-2 sentences), tips (at most 3 short tips)

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


def postprocess(raw: dict, segments: list[dict], st: dict, names: dict[str, int]) -> dict:
    """Repair what small models get wrong: bad line ids, names, scores, missing people."""
    by_id = {s["id"]: s for s in segments}
    ids = set(by_id)
    valid = {d["id"] for d in st["speakers"]}

    def line(x):
        try:
            x = int(x)
        except (TypeError, ValueError):
            return None
        return x if x in ids else None

    def rows(key):
        return [r for r in (raw.get(key) or []) if isinstance(r, dict)]

    topics = []
    for t in rows("topics"):
        ln = line(t.get("line"))
        if ln is not None and str(t.get("title", "")).strip():
            topics.append({"title": str(t["title"]).strip(), "summary": str(t.get("summary", "")).strip(),
                           "start": by_id[ln]["start"], "end": 0.0, "line": ln})
    topics = sorted(_dedupe(topics, "title"), key=lambda t: t["start"])
    for i, t in enumerate(topics):
        t["end"] = topics[i + 1]["start"] if i + 1 < len(topics) else st["duration"]

    decisions = _dedupe([{"text": str(d.get("text", "")).strip(), "line": line(d.get("line"))}
                         for d in rows("decisions")], "text")
    decisions = [d for d in decisions if d["line"] is not None]
    tasks = _dedupe([{"owner": _to_id(t.get("owner"), names, valid), "task": str(t.get("task", "")).strip(),
                      "due": str(t.get("due", "") or "").strip(), "line": line(t.get("line"))}
                     for t in rows("tasks")], "task")
    tasks = [t for t in tasks if t["line"] is not None]
    oq = _dedupe([{"asker": _to_id(q.get("asker"), names, valid), "text": str(q.get("text", "")).strip(),
                   "line": line(q.get("line"))} for q in rows("open_questions")], "text")
    oq = [q for q in oq if q["line"] is not None]

    found = {}
    for p in rows("people"):
        spk = _to_id(p.get("name"), names, valid)
        if spk is not None and spk not in found:
            found[spk] = p
    people = []
    for d in st["speakers"]:
        p = found.get(d["id"], {})
        people.append({"id": d["id"], "contribution": str(p.get("contribution", "")).strip(),
                       "gained": str(p.get("gained", "")).strip(), "evidence": _ints(p.get("evidence"), ids)})

    sc = raw.get("score") if isinstance(raw.get("score"), dict) else {}
    score = {"decisions": _clamp(sc.get("decisions")), "focus": _clamp(sc.get("focus")),
             "repetition": _clamp(sc.get("repetition")), "balance": round(st["balance"] * 100)}
    score["overall"] = round(sum(score[k] for k in ("decisions", "focus", "repetition", "balance")) / 4)
    score["comment"] = str(sc.get("comment", "")).strip()
    score["tips"] = [str(t).strip() for t in (sc.get("tips") or []) if str(t).strip()][:5]
    return {"summary": str(raw.get("summary", "")).strip(), "topics": topics, "decisions": decisions,
            "tasks": tasks, "open_questions": oq, "people": people, "score": score}


# ---------------- the run ----------------
def _set(job_id: str, **fields) -> None:
    job = store.read_transcript(job_id)
    store.update_job(job_id, analysis={**(job.get("analysis") or {}), **fields})


def _compact(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def collect(notes: list[dict]) -> dict:
    """Lists are taken from the part notes as they are: a small model drops rows when asked to copy them."""
    out = {"topics": [], "decisions": [], "tasks": [], "open_questions": []}
    for n in notes:
        if not isinstance(n, dict):
            continue
        for k in ("topics", "decisions", "tasks"):
            out[k] += [r for r in (n.get(k) or []) if isinstance(r, dict)]
        out["open_questions"] += [q for q in (n.get("questions") or [])
                                  if isinstance(q, dict) and q.get("answered") is False]
    return out


def digest(notes: list[dict]) -> str:
    """What the final call reads. Shortened when a long meeting would not fit."""
    c = collect(notes)

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

    job = store.read_transcript(job_id)
    segments, speakers = job.get("segments") or [], dict(job.get("speakers") or {})
    if not segments:
        raise ValueError("no speech to analyse")
    LANG = _lang(job)
    ana_dir = store.job_path(job_id) / "analysis"
    (ana_dir / "parts").mkdir(parents=True, exist_ok=True)

    _set(job_id, state="running", stage="stats", progress=0.0, part=0, parts=0, error="")
    suggestions = []
    _set(job_id, stage="names")
    try:
        from . import names, names_llm

        check()
        gen = lambda *a, **k: generate(*a, **{**k, "cancel": cancel})  # noqa: E731
        llm_found = names_llm.suggest(segments, speakers, gen)
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
    total = len(chunks) + 1  # notes parts + final call
    _set(job_id, stage="notes", parts=len(chunks), progress=0.0)

    notes = []
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
        if saved and saved.get("hash") == h:
            notes.append(saved["notes"])
        else:
            n = call(NOTES_PROMPT[LANG].format(transcript=text), NOTES_SCHEMA, max_tokens=3000)
            f.write_text(json.dumps({"hash": h, "notes": n}, ensure_ascii=False), "utf-8")
            notes.append(n)
        _set(job_id, part=i + 1, progress=round((i + 1) / total, 3))

    _set(job_id, stage="merge")
    shown = ", ".join(sp["name"] for sp in st["speakers"])
    merge_stats = {"duration": st["duration"], "balance": st["balance"],
                   "speakers": [{k: sp[k] for k in ("name", "share", "turns", "words", "questions")}
                                for sp in st["speakers"]]}
    raw = call(MERGE_PROMPT[LANG].format(names=shown, stats=_compact(merge_stats), notes=digest(notes)),
               MERGE_SCHEMA)
    names_map = _name_map(speakers, job.get("speakers") or {})
    result = postprocess({**(raw if isinstance(raw, dict) else {}), **collect(notes)}, segments, st, names_map)

    model = device = ""
    try:
        from . import llm

        p = llm.plan()
        model, device = p.get("model", ""), p.get("device", "")
    except Exception:
        pass
    result = {"version": VERSION, "model": model, "device": device, "lang": LANG, "created": time.time(),
              "seconds": round(time.time() - t0, 1), "transcript_hash": transcript_hash(segments),
              "stats": st, **result, "name_suggestions": suggestions}
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
