"""Guess speaker names from self-introductions ("ben Selim", "my name is Ana")
and from being addressed ("Umut sen de bir şey söyle" -> next speaker is Umut)."""
from __future__ import annotations

import re

UP, LO = "A-ZÇĞİÖŞÜ", "a-zçğıöşü"
NAME = rf"([{UP}][{LO}]+)"
END = r"(?![\w'’])"  # "Ankara'da" is a place with a suffix, not a name

SELF_INTRO = [
    re.compile(rf"\b(?:[Bb]enim\s+)?(?:ad[ıi]m|ismim)\s+{NAME}{END}"),
    # "ben Selim", "Ben de konuşmacı olarak Bahadır" (up to 3 lowercase words in between)
    re.compile(rf"\b[Bb]en(?:\s+[{LO}]+){{0,3}}\s+{NAME}{END}"),
    re.compile(rf"\b(?:[Mm]y name is|[Ii]'m|[Ii] am|[Tt]his is)\s+([A-Z][a-z]+){END}"),
]
ADDRESS = re.compile(
    rf"\b{NAME},?\s+(?:sen\b|siz\b|sıra\s+sende|söz\s+sende|buyur|what about you|your turn|go ahead)"
)
INTRO_WINDOW = 60  # introductions happen near the start of what someone says
NOT_NAMES = {"Türkçe", "İngilizce", "Bey", "Hanım", "Hocam", "Tamam", "Evet", "Hayır", "Not", "Sorry", "Here"}


def _is_default(label: str | None, spk: int) -> bool:
    return not label or label in (f"Speaker {spk + 1}", f"Konuşmacı {spk + 1}")


def detect_names(segments: list[dict], speakers: dict) -> dict[int, str]:
    """Return {speaker_index: name} for speakers still labelled 'Speaker N'."""
    strong: dict[int, str] = {}
    weak: dict[int, str] = {}
    for i, seg in enumerate(segments):
        text, spk = seg["text_edited"], seg["speaker"]
        if spk not in strong:
            for rx in SELF_INTRO:
                m = rx.search(text)
                if m and m.start() < INTRO_WINDOW and m.group(1) not in NOT_NAMES:
                    strong[spk] = m.group(1)
                    break
        m = ADDRESS.search(text)
        if m and m.group(1) not in NOT_NAMES:
            nxt = next((s for s in segments[i + 1:] if s["speaker"] != spk), None)
            if nxt is not None:
                weak.setdefault(nxt["speaker"], m.group(1))
    result: dict[int, str] = {}
    used = {v for k, v in speakers.items() if not _is_default(v, int(k))}
    for spk, name in [*strong.items(), *weak.items()]:
        if spk in result or name in used or not _is_default(speakers.get(str(spk)), spk):
            continue
        result[spk] = name
        used.add(name)
    return result
