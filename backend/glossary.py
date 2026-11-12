"""Glossary: names and terms the speech model keeps getting wrong ("Koriersu" for "Koray Ersu", "Ivedik" for "İvedik").

Three things work together, all on this PC:
  1. terms     - words the user typed in, the names of the saved people, and every spelling the user corrected.
                 They are given to the speech model as hot words, so it writes them right in the first place.
  2. fixes     - "wrong spelling -> right spelling" pairs. Learned from the user's own corrections in the transcript
                 editor (and editable by hand). Applied to every new recording, always.
  3. fuzzy     - a word the model was unsure about that is spelled almost like a term is replaced by the term.
                 Never for words the model was sure about ("selam" is not turned into "Selim").
Stored in data_dir/glossary.json.
"""
from __future__ import annotations

import difflib
import json
import re
import threading
import time

from . import store

MAX_HOTWORDS = 60        # hot words handed to the model (most recent first)
FUZZY = 0.80             # similarity (folded spelling) needed for a fuzzy replacement
FUZZY_MAX_PROB = 0.60    # ... and only when the model itself was this unsure
LEARN_MIN_SIM = 0.45     # a user edit is learned as a spelling fix only when old and new look alike

_lock = threading.RLock()
_PUNCT = re.compile(r"^([^\w]*)(.*?)([^\w]*)$", re.S)
_TR = str.maketrans({"İ": "i", "I": "i", "ı": "i", "Ç": "c", "ç": "c", "Ş": "s", "ş": "s", "Ğ": "g", "ğ": "g",
                     "Ö": "o", "ö": "o", "Ü": "u", "ü": "u"})


def fold(s: str) -> str:
    """Spelling without case, Turkish letters or spaces: "Koray Ersu" and "korayersu" and "İvedik" / "Ivedik" match."""
    return re.sub(r"[^a-z0-9]", "", s.translate(_TR).lower())


def _path():
    return store.data_dir() / "glossary.json"


def _load() -> dict:
    try:
        g = json.loads(_path().read_text("utf-8"))
    except (OSError, ValueError):
        g = {}
    g.setdefault("terms", [])
    g.setdefault("fixes", {})
    return g


def _save(g: dict) -> None:
    f = _path()
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(g, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(f)


# ---------------------------------------------------------------- reading and editing
def get() -> dict:
    g = _load()
    return {"terms": list(g["terms"]),
            "fixes": [{"wrong": k, "right": v["right"], "count": v.get("count", 1), "manual": bool(v.get("manual"))}
                      for k, v in g["fixes"].items()]}


def set_terms(terms: list[str]) -> dict:
    clean, seen = [], set()
    for t in terms:
        t = " ".join(str(t).split())
        if t and fold(t) not in seen and len(t) <= 60:
            clean.append(t)
            seen.add(fold(t))
    with _lock:
        g = _load()
        g["terms"] = clean[:500]
        _save(g)
    return get()


def add_fix(wrong: str, right: str, count: int = 1, manual: bool = False) -> dict:
    wrong, right = " ".join(wrong.split()), " ".join(right.split())
    if not wrong or not right or wrong == right:
        return get()
    with _lock:
        g = _load()
        key = wrong.lower()
        old = g["fixes"].get(key, {})
        g["fixes"][key] = {"right": right, "count": old.get("count", 0) + count, "at": time.time(),
                           "manual": bool(manual or old.get("manual"))}
        _save(g)
    return get()


def remove_fix(wrong: str) -> dict:
    with _lock:
        g = _load()
        g["fixes"].pop(wrong.lower(), None)
        _save(g)
    return get()


def all_terms() -> list[str]:
    """Terms + the right-hand side of every learned fix + names of saved people; recent first, no duplicates."""
    g = _load()
    out = [v["right"] for v in sorted(g["fixes"].values(), key=lambda v: -v.get("at", 0))] + list(reversed(g["terms"]))
    try:
        from . import people

        out += [p["name"] for p in people.list_people()]
    except Exception:
        pass
    res, seen = [], set()
    for t in out:
        if fold(t) not in seen:
            res.append(t)
            seen.add(fold(t))
    return res


def hotwords() -> str | None:
    """Text for the speech model's hot words, e.g. "İvedik, Koray Ersu". None when there is nothing to say."""
    terms = all_terms()[:MAX_HOTWORDS]
    return ", ".join(terms) if terms else None


# ---------------------------------------------------------------- applying
def _split(text: str) -> tuple[str, str, str, str]:
    """(leading spaces, punctuation before, core, punctuation after) of a word token."""
    lead = text[:len(text) - len(text.lstrip())]
    m = _PUNCT.match(text.strip())
    return lead, m.group(1), m.group(2), m.group(3)


def _sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def apply(words: list) -> tuple[list, list[dict]]:
    """Correct a list of Word objects (start, end, text, prob). Returns (words, changes) where changes lists
    {"from", "to", "why"} for the report. Words keep their timing; a corrected word gets full confidence."""
    from .merge import Word

    g = _load()
    fixes = {fold(k): v for k, v in g["fixes"].items()}
    terms = [t for t in all_terms() if len(fold(t)) >= 4]
    if not fixes and not terms:
        return words, []
    folded_terms = [(fold(t), t) for t in terms]
    out: list[Word] = []
    changes: list[dict] = []
    i = 0
    n = len(words)
    while i < n:
        done = False
        for size in (3, 2, 1):  # a term can be heard as one word, or split over up to three
            if i + size > n:
                continue
            chunk = words[i:i + size]
            if any(w.text.rstrip()[-1:] in ".?!…" for w in chunk[:-1]):
                continue  # never glue words across the end of a sentence
            parts = [_split(w.text) for w in chunk]
            core = "".join(p[2] for p in parts)
            f = fold(core)
            if len(f) < 4 and size == 1 and f not in fixes:
                continue
            right, why = None, ""
            fx = fixes.get(f)
            # a respelling learned from ONE edit is only trusted where the model was unsure itself (a real word
            # like "selam" must not become "Selim" because it was misheard once); confirmed twice or typed in: always
            if fx and (size == 1 or len(f) >= 6) and (fx.get("manual") or fx.get("count", 1) >= 2 or min(w.prob for w in chunk) < 0.75):
                right, why = fx["right"], "fix"
            else:
                for ft, term in folded_terms:
                    if f == ft:
                        right, why = term, "spelling"
                        break
                if right is None and len(f) >= 5 and all(w.prob < FUZZY_MAX_PROB for w in chunk):  # every word of it must be one the model doubted
                    best = max(((_sim(f, ft), term) for ft, term in folded_terms
                                if ft[:1] == f[:1] and abs(len(f) - len(ft)) <= max(2, len(ft) // 4)), default=(0.0, None))
                    if best[0] >= FUZZY:
                        right, why = best[1], "similar"
            if right is None:
                continue
            old = "".join(w.text for w in chunk).strip()
            if " ".join(pt[2] for pt in parts) == right:
                continue  # already spelled right (only punctuation around it)
            lead = parts[0][0]
            text = lead + parts[0][1] + right + parts[-1][3]
            out.append(Word(chunk[0].start, chunk[-1].end, text, 1.0))
            changes.append({"from": old, "to": right, "why": why})
            i += size
            done = True
            break
        if not done:
            out.append(words[i])
            i += 1
    return out, changes


# ---------------------------------------------------------------- learning from the user's own corrections
def _is_name_like(s: str) -> bool:
    return bool(re.search(r"[A-ZÇĞİÖŞÜ]", s)) or bool(re.search(r"[çğıöşüÇĞİÖŞÜ]", s))


def learn(original: str, edited: str) -> list[tuple[str, str]]:
    """Compare the model's line with the user's corrected line. Small replacements that look like a respelling
    (not a rewrite) become fixes. Returns the pairs learned."""
    a, b = original.split(), edited.split()
    if not a or not b or original == edited:
        return []
    learned = []
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "replace" or i2 - i1 > 3 or j2 - j1 > 3:
            continue
        old = " ".join(a[i1:i2]).strip(" ,.;:!?\"'()")
        new = " ".join(b[j1:j2]).strip(" ,.;:!?\"'()")
        if not old or not new or old == new or len(fold(new)) < 4 or not _is_name_like(new):
            continue
        if _sim(fold(old), fold(new)) < LEARN_MIN_SIM and fold(old) != fold(new):
            continue
        if fold(old) == fold(new) and old.lower() == new.lower():
            continue  # only the capital letter at a sentence start changed
        learned.append((old, new))
    for old, new in learned:
        add_fix(old, new)
    return learned
