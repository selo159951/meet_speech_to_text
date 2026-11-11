"""Find speakers' real names with the local LLM and combine that with the rule-based
detection (names.py) and voice recognition (people.py).

`generate(prompt, schema=None, system=None, max_tokens=..., temperature=..., cancel=None) -> dict`
is passed in, so this module never imports the engine."""
from __future__ import annotations

import re
import unicodedata

from .names import LO, NOT_NAMES, UP, _is_default

MAX_TOKENS = 2500  # of lines sent to the model (len/3)
LINE_CHARS = 300
BEFORE, AFTER = 1, 2
CONF = {"high": 0.9, "medium": 0.6, "low": 0.3}
AUTO_AT = 0.9
RULE_CONF = 0.6

N = rf"([{UP}][{LO}]+)"
STRONG = [re.compile(p) for p in (
    rf"(?i:\bben\b)(?:\s+[{LO}]+){{0,3}}\s+{N}",
    rf"(?i:\bad[ıi]m\b|\bismim\b),?\s+{N}",
    rf"{N}\s+(?i:bey|han[ıi]m)\b",
    rf"{N},?\s+(?i:sen|siz)\b",
    rf"(?i:te[sş]ekk[uü]r(?:ler|\s+ederim)?|sa[gğ]\s*ol),?\s+{N}",
    rf"{N}['’](?i:e|a|ye|ya)\s+(?i:soral[ıi]m|s[öo]z|d[öo]nelim)",
    rf"(?i:\bi'm|\bi am|my name is|this is|thanks|thank you),?\s+{N}",
    rf"{N},?\s+(?i:what do you think|what about you|your turn)",
)]
ORG_WORDS = r"(?:high school|school|lisesi|lise|anadolu|anatolian|university|üniversite|college|technopark|teknopark|ortaokulu|okulu|vocational)"
ORG_AFTER = re.compile(ORG_WORDS, re.I)
CAPITAL = re.compile(rf"[{UP}][{LO}]+")
PERSON = re.compile(rf"^[{UP}][{LO}]+(?: [{UP}][{LO}]+)?$")
STOP = {w.casefold() for w in NOT_NAMES} | {"konuşmacı", "speaker", "ben", "sen", "bir", "bu", "şu", "ama", "yani", "evet"}

SCHEMA = {
    "type": "object",
    "properties": {"speakers": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "speaker": {"type": "integer"},
            "name": {"type": "string"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "line": {"type": "integer"},
            "reason": {"type": "string"},
        },
        "required": ["speaker", "name", "confidence", "line", "reason"],
    }}},
    "required": ["speakers"],
}

PROMPTS = {
    "tr": (
        "Aşağıda bir toplantı konuşmasından seçilmiş satırlar var. Her satır `[satır numarası] Konuşmacı K: metin` biçimindedir. "
        "Görevin: konuşmacıların gerçek adlarını bulmak.\n"
        "Üç durum:\n"
        "1. Biri kendini tanıtırsa (\"ben Deniz\", \"benim adım Elif\") ad o satırı söyleyen konuşmacıya aittir.\n"
        "2. Biri birine seslenirse (\"Elif sen ne dersin?\", \"Burak Bey\") ad, o satırdan SONRA cevap veren konuşmacıya aittir.\n"
        "3. Biri teşekkür ederse (\"teşekkürler Burak\") ad genellikle bir ÖNCEKİ konuşmacıya aittir.\n"
        "Kurallar: yalnızca toplantıda bulunan ve konuşan kişilerin adlarını yaz. Sadece bahsedilen kişileri yazma. "
        "Okul, şirket ve yer adları kişi değildir (\"Ayla Lisesi\"). "
        "Emin değilsen o konuşmacıyı atla. Bir ad en fazla bir konuşmacıya ait olabilir. "
        "`speaker` alanına K sayısını, `line` alanına adı ortaya koyan satırın numarasını yaz; `reason` kısa bir gerekçe olsun.\n\n"
        "Satırlar:\n{lines}"
    ),
    "en": (
        "Below are lines picked from a meeting transcript. Each line looks like `[line id] Speaker K: text`. "
        "Your task: find the real names of the speakers.\n"
        "Three cases:\n"
        "1. Someone introduces themselves (\"I'm Deniz\", \"my name is Elif\"): the name belongs to the speaker of that line.\n"
        "2. Someone addresses another person (\"Elif, what do you think?\", \"Mr. Burak\"): the name belongs to the speaker who replies AFTER that line.\n"
        "3. Someone thanks a person (\"thanks Burak\"): the name usually belongs to the PREVIOUS speaker.\n"
        "Rules: only give names of people who are in the meeting and speak. Skip people who are merely mentioned. "
        "Names of schools, companies and places are not people (\"Ayla High School\"). "
        "Skip a speaker if you are not sure. A name belongs to at most one speaker. "
        "Put the number K in `speaker`, the id of the line that reveals the name in `line`, and a short `reason`.\n\n"
        "Lines:\n{lines}"
    ),
}
SYSTEM = {
    "tr": "Toplantı dökümlerinden konuşmacı adlarını çıkaran dikkatli bir yardımcısın. Yalnızca istenen JSON'u ver.",
    "en": "You carefully extract speaker names from meeting transcripts. Reply with the requested JSON only.",
}


def _tokens(text: str) -> int:
    return len(text) // 3


def _is_strong(text: str) -> bool:
    return any(rx.search(text) for rx in STRONG)


def _has_inner_capital(text: str) -> bool:
    for m in CAPITAL.finditer(text):
        before = text[:m.start()].rstrip()
        if before and before[-1] not in ".?!…:" and m.group(0).casefold() not in STOP:
            return True
    return False


def _label(seg: dict, lang: str) -> str:
    return f"{'Konuşmacı' if lang == 'tr' else 'Speaker'} {seg['speaker'] + 1}"


def _render(seg: dict, lang: str) -> str:
    return f"[{seg['id']}] {_label(seg, lang)}: {seg['text_edited'].strip()[:LINE_CHARS]}"


def candidates(segments: list[dict], lang: str = "tr") -> list[list[int]]:
    """Groups of consecutive segment indexes worth showing to the model (<= MAX_TOKENS)."""
    strong = [i for i, s in enumerate(segments) if _is_strong(s["text_edited"])]
    seen = set(strong)
    weak = [i for i, s in enumerate(segments) if i not in seen and _has_inner_capital(s["text_edited"])]
    chosen: set[int] = set()
    used = 0
    for i in strong + weak:  # strong hits first, so the cap cuts the weak ones
        window = {j for j in range(i - BEFORE, i + AFTER + 1) if 0 <= j < len(segments)} - chosen
        cost = sum(_tokens(_render(segments[j], lang)) + 1 for j in window)
        if used + cost > MAX_TOKENS:
            continue
        chosen |= window
        used += cost
    groups: list[list[int]] = []
    for i in sorted(chosen):
        if groups and groups[-1][-1] == i - 1:
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups


def title(name: str, lang: str = "tr") -> str:
    """'ıŞIL' -> 'Işıl', 'İREM' -> 'İrem' (Turkish i/İ/ı/I rules)."""
    def word(w: str) -> str:
        if lang == "tr":
            return w[:1].replace("i", "İ").replace("ı", "I").upper() + w[1:].replace("I", "ı").replace("İ", "i").lower()
        return w.capitalize()
    return " ".join(word(w) for w in name.split())


def _norm(name: str) -> str:
    s = name.replace("İ", "i").replace("ı", "i").replace("I", "i")
    s = unicodedata.normalize("NFKD", s.casefold())
    return "".join(c for c in s if not unicodedata.combining(c)).strip()


def suggest(segments: list[dict], speakers: dict, generate, cancel=None, lang: str = "tr") -> list[dict]:
    groups = candidates(segments, lang)
    if not groups:
        return []
    lines = "\n\n".join("\n".join(_render(segments[i], lang) for i in g) for g in groups)
    # one entry per speaker at most: stops a small model from repeating the same name until it runs out
    schema = {**SCHEMA, "properties": {"speakers": {**SCHEMA["properties"]["speakers"], "maxItems": max(1, len(speakers))}}}
    out = generate(PROMPTS[lang].format(lines=lines), schema=schema, system=SYSTEM[lang],
                   max_tokens=1024, temperature=0.1, cancel=cancel)
    ids = {s["id"] for s in segments}
    segs_by_id = {s["id"]: s for s in segments}
    known = {int(k) for k in speakers} | {s["speaker"] for s in segments}
    # a name must really be said in the recording: small models like to return the prompt's example names
    spoken = set(re.findall(r"\w+", _norm(" ".join(str(x.get("text_edited") or x.get("text_original") or "") for x in segments))))
    best: dict[int, dict] = {}
    for e in (out or {}).get("speakers") or []:
        try:
            spk, line = int(e["speaker"]) - 1, int(e["line"])
            raw = str(e["name"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        conf = e.get("confidence")
        conf = min(max(float(conf), 0.0), 1.0) if isinstance(conf, (int, float)) else CONF.get(str(conf).lower())
        name = title(raw, lang)
        if conf is None or spk not in known or line not in ids or not PERSON.match(name):
            continue
        if any(w.casefold() in STOP for w in name.split()):
            continue
        near = " ".join(str(segs_by_id[i].get("text_edited") or segs_by_id[i].get("text_original") or "")
                        for i in range(line - 1, line + 3) if i in segs_by_id)
        if _norm(name.split()[0]) not in set(re.findall(r"\w+", _norm(near))) and not any(
                t.startswith(_norm(name.split()[0])) for t in re.findall(r"\w+", _norm(near))):
            continue  # the cited lines never say this name
        if ORG_AFTER.search(near) and re.search(rf"{re.escape(name.split()[0])}\W+(?:\w+\W+){{0,2}}{ORG_WORDS}", near, re.I):
            continue  # "Ayla High School" is a place, not a person
        cited = segs_by_id[line]
        said = str(cited.get("text_edited") or cited.get("text_original") or "")
        own = re.search(rf"(?i:\bi am|\bi'm|\bmy name is|\bben\b|\bad[ıi]m\b|\bismim\b)\W+(?:\w+\W+){{0,3}}{re.escape(name.split()[0])}", said)
        if own and cited["speaker"] != spk:
            continue  # "I am Elif" was said by somebody else: the name is theirs, not this speaker's
        if cited["speaker"] == spk and not own:
            continue  # a speaker who names somebody ("let's move on with Paula") is not that person
        if not _is_strong(near):
            conf = min(conf, 0.6)  # nobody introduced themselves or was addressed there: a suggestion, never automatic
        if not all(any(t.startswith(_norm(w)) for t in spoken) for w in name.split()):
            continue
        if spk not in best or conf > best[spk]["confidence"]:
            best[spk] = {"speaker": spk, "name": name, "confidence": conf, "line": line}
    by_name: dict[str, dict] = {}
    for e in best.values():
        k = _norm(e["name"])
        if k not in by_name or e["confidence"] > by_name[k]["confidence"]:
            by_name[k] = e
    return sorted(by_name.values(), key=lambda e: e["speaker"])


def combine(rule: dict, llm: list[dict], voice: dict | None, speakers: dict | None = None):
    """-> (auto: {speaker: name}, suggestions: [{speaker, name, confidence, line, source}])."""
    voice = voice or {}
    matches = {int(k): v for k, v in (voice.get("voice_matches") or {}).items()}
    best: dict[int, dict] = {}
    for e in llm:
        if e["speaker"] not in best or e["confidence"] > best[e["speaker"]]["confidence"]:
            best[e["speaker"]] = e
    used: set[str] = set()
    for k, label in (speakers or {}).items():
        if not _is_default(label, int(k)):
            used.add(_norm(label))
    used |= {_norm(m["name"]) for m in matches.values() if m.get("name")}

    def open_(spk: int) -> bool:
        return spk not in matches and (not speakers or _is_default(speakers.get(str(spk)), spk))

    auto: dict[int, str] = {}
    rest = []
    for spk in (s for s in sorted(set(rule) | set(best)) if open_(s)):
        r, e = rule.get(spk), best.get(spk)
        name = None
        if r and e and _norm(r) == _norm(e["name"]):
            name = r
        elif e and not r and e["confidence"] >= AUTO_AT:
            name = e["name"]
        if name and _norm(name) not in used:
            auto[spk] = name
            used.add(_norm(name))
        elif not name:
            rest.append(spk)
    sugg: list[dict] = []
    for spk in rest:
        r, e = rule.get(spk), best.get(spk)
        if r and _norm(r) not in used:
            sugg.append({"speaker": spk, "name": r, "confidence": RULE_CONF, "line": None, "source": "rule"})
        if e and _norm(e["name"]) not in used:
            sugg.append({**e, "source": "llm"})
    return auto, sugg
