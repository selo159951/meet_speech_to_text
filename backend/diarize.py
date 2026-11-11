"""Offline speaker diarization with sherpa-onnx (no token needed)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import numpy as np

from .merge import Turn

MAX_SPEAKERS = 3         # an ordinary meeting: more voices than this are usually one person split in two
MANY_SPEAKERS = 20       # a class, a panel: up to this many people are kept apart
MIN_BIG_SECONDS = 12.0   # a voice counts as a real participant when it speaks at least this long ...
BIG_SHARE = 0.025        # ... and at least this share of all the speech
THRESHOLD = 0.6  # clustering distance: higher merges more voices into one speaker
SEG_MODEL = "sherpa-onnx-pyannote-segmentation-3-0/model.onnx"
EMB_MODEL = "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"


def models_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "models"


def models_available() -> bool:
    d = models_dir()
    return (d / SEG_MODEL).exists() and (d / EMB_MODEL).exists()


import os

# sherpa-onnx defaults to a single CPU thread, which makes long meetings very slow
THREADS = max(1, min(16, (os.cpu_count() or 2) - 2))  # leave 2 cores for the UI/system


# How far the 10 s analysis window moves each step. sherpa-onnx's default (0.1) looks at
# every second 10 times; 0.5 is 4x faster and gave the same turns on real meetings
# (the sentence-level check in refine_by_sentence catches the rare missed change).
WINDOW_SHIFT = 0.5


def _seg_config(d):
    import sherpa_onnx as so

    c = so.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(d / SEG_MODEL))
    c.window_shift_ratio = WINDOW_SHIFT
    return c


def _make(num_clusters: int):
    import sherpa_onnx as so

    d = models_dir()
    cfg = so.OfflineSpeakerDiarizationConfig(
        segmentation=so.OfflineSpeakerSegmentationModelConfig(
            pyannote=_seg_config(d),
            num_threads=THREADS,
        ),
        embedding=so.SpeakerEmbeddingExtractorConfig(model=str(d / EMB_MODEL), num_threads=THREADS),
        clustering=so.FastClusteringConfig(num_clusters=num_clusters, threshold=THRESHOLD),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    return so.OfflineSpeakerDiarization(cfg)


MIN_SENT = 0.8   # seconds of speech needed for a reliable voice print
MARGIN = 0.15    # how much closer to another speaker a sentence must be to move


def refine_by_sentence(samples: np.ndarray, words, speakers: list[int],
                       progress: Callable[[float], None] = lambda p: None) -> list[int]:
    """Second pass: catch speaker changes the segmentation model missed (e.g. no pause
    between two people). Every sentence gets a voice print; it moves to another speaker
    when it is clearly closer to that speaker's average voice than to its own
    (leave-one-out average, so a sentence can't vote for itself)."""
    from .merge import sentences

    if not models_available() or not words:
        return speakers
    import sherpa_onnx as so

    ex = so.SpeakerEmbeddingExtractor(
        so.SpeakerEmbeddingExtractorConfig(model=str(models_dir() / EMB_MODEL), num_threads=THREADS))
    sents = [(i, j) for i, j in sentences(words) if words[j - 1].end - words[i].start >= MIN_SENT]
    embs, labels = [], []
    for n, (i, j) in enumerate(sents):
        a, b = int(words[i].start * 16000), int(words[j - 1].end * 16000)
        st = ex.create_stream()
        st.accept_waveform(16000, samples[a:b])
        st.input_finished()
        e = np.array(ex.compute(st), dtype=np.float32)
        embs.append(e / (np.linalg.norm(e) + 1e-9))
        votes = np.bincount(speakers[i:j])
        labels.append(int(votes.argmax()))
        progress((n + 1) / len(sents))
    if len(set(labels)) < 2:
        return speakers
    E = np.stack(embs)
    out = list(speakers)
    for _ in range(2):  # a second round uses the corrected averages
        sums = {s: E[[k for k, l in enumerate(labels) if l == s]].sum(0) for s in set(labels)}
        counts = {s: labels.count(s) for s in set(labels)}
        changed = False
        for k, (i, j) in enumerate(sents):
            own = labels[k]
            if counts[own] < 2:  # don't strip a speaker's only sentence
                continue
            sims = {}
            for s in sums:
                c = sums[s] - (E[k] if s == own else 0)
                if s == own or counts[s] > 0:
                    sims[s] = float(E[k] @ (c / (np.linalg.norm(c) + 1e-9)))
            best = max(sims, key=sims.get)
            if best != own and sims[best] - sims[own] > MARGIN and sims[best] > 0.3:
                labels[k] = best
                counts[own] -= 1; counts[best] += 1
                sums[own] = sums[own] - E[k]; sums[best] = sums[best] + E[k]
                out[i:j] = [best] * (j - i)
                changed = True
        if not changed:
            break
    return out


class Cancelled(Exception):
    pass


def consolidate(turns: list[Turn], min_seconds: float = MIN_BIG_SECONDS, share: float = BIG_SHARE,
                cap: int = MANY_SPEAKERS) -> list[Turn] | None:
    """For a meeting with many people. Voices that speak only a few seconds are mostly one real
    person heard differently (or a short "yes"): each of their turns goes to the real participant
    who speaks closest in time. Returns None when there are not more than MAX_SPEAKERS real
    participants (then the caller keeps the usual behaviour of forcing a few speakers)."""
    total = sum(t.end - t.start for t in turns)
    dur: dict[int, float] = {}
    for t in turns:
        dur[t.speaker] = dur.get(t.speaker, 0.0) + t.end - t.start
    big = [k for k, v in sorted(dur.items(), key=lambda kv: -kv[1]) if v >= max(min_seconds, share * total)][:cap]
    if len(big) <= MAX_SPEAKERS:
        return None
    keep = set(big)
    anchors = [t for t in turns if t.speaker in keep]
    out = []
    for t in turns:
        if t.speaker in keep:
            out.append(t)
            continue
        mid = (t.start + t.end) / 2
        near = min(anchors, key=lambda a: 0.0 if a.start <= mid <= a.end else min(abs(a.start - mid), abs(a.end - mid)))
        out.append(Turn(t.start, t.end, near.speaker))
    return out


def diarize(samples: np.ndarray, progress: Callable[[float], None], cancel=None) -> list[Turn]:
    """Returns turns with 0-based speakers ordered by first appearance. Empty if models missing."""
    if not models_available():
        return []

    def cb(done, total, *_):
        if cancel is not None and cancel.is_set():
            return 1  # non-zero stops sherpa-onnx
        progress(done / max(total, 1))
        return 0

    sd = _make(-1)
    result = sd.process(samples, callback=cb).sort_by_start_time()
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    raw = [Turn(r.start, r.end, r.speaker) for r in result]
    if len({t.speaker for t in raw}) > MAX_SPEAKERS:
        many = consolidate(raw)  # a class or a panel keeps its people apart ...
        if many is None:  # ... an ordinary meeting is forced down to a few speakers
            result = _make(MAX_SPEAKERS).process(samples, callback=cb).sort_by_start_time()
            raw = [Turn(r.start, r.end, r.speaker) for r in result]
        else:
            raw = many
    order: dict[int, int] = {}
    turns = []
    for r in raw:
        spk = order.setdefault(r.speaker, len(order))
        turns.append(Turn(r.start, r.end, spk))
    return turns
