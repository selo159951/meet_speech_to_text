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

# ---- sentence-level speaker decoding (second pass) ----------------------------------------------
SHORT_SENT = 0.4      # sentences shorter than this are left with the label they have
REF_SENT = 1.5        # only sentences at least this long serve as reference voices
KNN = 3               # a sentence is compared with the 3 most similar reference sentences of a speaker
BETA = 12.0           # similarity difference -> log-probability (0.1 similarity = 1.2 nats)
SWITCH = 1.4          # cost of changing speaker between two sentences (nats)
SWITCH_GAP = 0.8      # a pause of this many seconds makes a change half as expensive
SWITCH_CLOSURE = 0.5  # factor after a closing phrase ("Thank you.") - the next sentence is likely somebody else


def _emissions(E: np.ndarray, labels: list[int], dur: list[float]) -> tuple[np.ndarray, list[int]]:
    """Similarity of every sentence to every speaker: half the (leave-one-out) average voice, half the
    mean of the KNN closest long reference sentences of that speaker. Shape (sentences, speakers)."""
    spk = sorted(set(labels))
    em = np.zeros((len(E), len(spk)), np.float32)
    for c, s in enumerate(spk):
        idx = [k for k, l in enumerate(labels) if l == s]
        ref = [k for k in idx if dur[k] >= REF_SENT] or idx
        tot = E[idx].sum(0)
        for k in range(len(E)):
            own = k in idx
            m = tot - (E[k] if own else 0)
            nrm = float(np.linalg.norm(m))
            cen = float(E[k] @ (m / nrm)) if nrm > 1e-6 and (len(idx) > 1 or not own) else float(E[k] @ E[idx[0]])
            cand = [r for r in ref if r != k]
            sims = sorted((float(E[k] @ E[r]) for r in cand), reverse=True)[:KNN]
            knn = float(np.mean(sims)) if sims else cen
            em[k, c] = 0.5 * cen + 0.5 * knn
    return em, spk


def decode_sentences(em: np.ndarray, gaps: list[float], closure: list[bool]) -> list[int]:
    """Viterbi over the sentence sequence: best speaker path = sum of BETA*(similarity - best similarity)
    minus a cost for every change of speaker. Returns the column index chosen for every sentence."""
    n, m = em.shape
    if n == 0 or m == 0:
        return [0] * n
    logp = (BETA * (em - em.max(1, keepdims=True))).astype(np.float64)
    best = np.zeros((n, m), np.float64)
    back = np.zeros((n, m), np.int32)
    best[0] = logp[0]
    for k in range(1, n):
        cost = SWITCH * (1.0 - 0.5 * min(max(gaps[k], 0.0) / SWITCH_GAP, 1.0))
        if closure[k - 1]:
            cost *= SWITCH_CLOSURE
        for c in range(m):
            stay = best[k - 1, c]
            sw = best[k - 1] - cost
            sw[c] = -1e9
            j = int(sw.argmax())
            if stay >= sw[j]:
                best[k, c], back[k, c] = stay + logp[k, c], c
            else:
                best[k, c], back[k, c] = sw[j] + logp[k, c], j
    path = [int(best[-1].argmax())]
    for k in range(n - 1, 0, -1):
        path.append(int(back[k, path[-1]]))
    return path[::-1]


CLOSING = ("thank you", "thanks", "teşekkür", "sağ ol", "okay", "tamam", "great", "all right", "that's all")


def refine_by_sentence(samples: np.ndarray, words, speakers: list[int],
                       progress: Callable[[float], None] = lambda p: None) -> list[int]:
    """Second pass. Every sentence gets a voice print; the speaker of each sentence is then decoded for
    the whole meeting at once (Viterbi): a sentence follows the voice it sounds most like, a change of
    speaker has a price, so one short "Thank you." cannot flip back and forth on its own noise but a
    clear change (or a short remark of the moderator between two people) is kept."""
    from .merge import sentences

    if not models_available() or not words:
        return speakers
    import sherpa_onnx as so

    ex = so.SpeakerEmbeddingExtractor(
        so.SpeakerEmbeddingExtractorConfig(model=str(models_dir() / EMB_MODEL), num_threads=THREADS))
    total = len(samples)
    sents = [(i, j) for i, j in sentences(words) if words[j - 1].end - words[i].start >= SHORT_SENT
             and min(total, int(words[j - 1].end * 16000)) > max(0, int(words[i].start * 16000))]
    if not sents:
        progress(1.0)
        return speakers
    embs, labels, dur, gaps, closure = [], [], [], [], []
    for n, (i, j) in enumerate(sents):
        a, b = max(0, int(words[i].start * 16000)), min(total, int(words[j - 1].end * 16000))
        st = ex.create_stream()
        st.accept_waveform(16000, np.ascontiguousarray(samples[a:b], dtype=np.float32))
        st.input_finished()
        e = np.array(ex.compute(st), dtype=np.float32)
        embs.append(e / (np.linalg.norm(e) + 1e-9))
        labels.append(int(np.bincount(speakers[i:j]).argmax()))
        dur.append(words[j - 1].end - words[i].start)
        gaps.append(words[i].start - words[sents[n - 1][1] - 1].end if n else 9.0)
        txt = " ".join(w.text for w in words[i:j]).strip().lower().strip(".!?… ")
        closure.append(txt.endswith(CLOSING) or txt in CLOSING)
        progress(0.7 * (n + 1) / len(sents))
    if len(set(labels)) < 2 or len(sents) < 3:
        progress(1.0)
        return speakers
    E = np.stack(embs)
    em, spk = _emissions(E, labels, dur)
    path = decode_sentences(em, gaps, closure)
    out = list(speakers)
    for (i, j), c in zip(sents, path):
        out[i:j] = [spk[c]] * (j - i)
    progress(1.0)
    return out


# ---- one person heard as two speakers -----------------------------------------------------------
MERGE_SIM = 0.72           # voice prints of two speakers this alike are one person (measured: two different
                           # people reach at most 0.66, p99 0.62; the same person is 0.81 or more)
MERGE_MARGIN = 0.05        # ... and each must be clearly closer to the other than to anybody else
MERGE_MIN_SECONDS = 8.0    # a voice print needs this much speech to be trusted


def _spans(words, spk: list[int], s: int, gap: float = 0.3) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for w, l in zip(words, spk):
        if l != s:
            continue
        if out and w.start - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], w.end)
        else:
            out.append([w.start, w.end])
    return [(a, b) for a, b in out]


def merge_split_speakers(samples: np.ndarray, words, spk: list[int], threshold: float = MERGE_SIM) -> list[int]:
    """Merge speakers that are the same voice (a person whose voice changed with the microphone or
    the room can be split in two). Only mutual best matches above the threshold are merged, and
    never a speaker with too little speech to judge. Returns the speaker list with contiguous ids
    in order of first appearance."""
    if not models_available() or not words or len(set(spk)) < 2:
        return list(spk)
    from . import people

    spk = list(spk)
    prints: dict[int, np.ndarray] = {}
    secs: dict[int, float] = {}

    def voice(s: int):
        if s not in prints:
            parts = [samples[max(0, int(a * 16000)):int(b * 16000)] for a, b in _spans(words, spk, s) if b > a]
            speech = np.concatenate(parts) if parts else samples[:0]
            secs[s] = len(speech) / 16000
            E = people.window_embeddings(speech, max_seconds=90) if secs[s] >= MERGE_MIN_SECONDS else None
            v = people._unit(E.sum(0)) if E is not None and len(E) else None
            prints[s] = v if v is not None and bool(np.all(np.isfinite(v))) else None
        return prints[s]

    while True:
        ids = [s for s in sorted(set(spk)) if voice(s) is not None]
        if len(ids) < 2:
            break
        M = np.array([[float(prints[a] @ prints[b]) if a != b else -1.0 for b in ids] for a in ids])
        best = None
        for i, a in enumerate(ids):
            j = int(M[i].argmax())
            if int(M[j].argmax()) != i or M[i, j] < threshold or i > j:
                continue
            second = max(float(np.partition(M[i], -2)[-2]) if len(ids) > 2 else -1.0,
                         float(np.partition(M[j], -2)[-2]) if len(ids) > 2 else -1.0)
            if M[i, j] - second < MERGE_MARGIN:
                continue
            if best is None or M[i, j] > best[0]:
                best = (float(M[i, j]), a, ids[j])
        if best is None:
            break
        _, a, b = best  # b joins a
        spk = [a if l == b else l for l in spk]
        prints.pop(a, None); prints.pop(b, None); secs.pop(b, None)
    order: dict[int, int] = {}
    for l in spk:
        order.setdefault(l, len(order))
    return [order[l] for l in spk]


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
