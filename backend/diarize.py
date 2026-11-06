"""Offline speaker diarization with sherpa-onnx (no token needed)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import numpy as np

from .merge import Turn

MAX_SPEAKERS = 3
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


def _make(num_clusters: int):
    import sherpa_onnx as so

    d = models_dir()
    cfg = so.OfflineSpeakerDiarizationConfig(
        segmentation=so.OfflineSpeakerSegmentationModelConfig(
            pyannote=so.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(d / SEG_MODEL)),
            num_threads=THREADS,
        ),
        embedding=so.SpeakerEmbeddingExtractorConfig(model=str(d / EMB_MODEL), num_threads=THREADS),
        clustering=so.FastClusteringConfig(num_clusters=num_clusters, threshold=0.6),
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


def diarize(samples: np.ndarray, progress: Callable[[float], None]) -> list[Turn]:
    """Returns turns with 0-based speakers ordered by first appearance. Empty if models missing."""
    if not models_available():
        return []

    def cb(done, total, *_):
        progress(done / max(total, 1))
        return 0

    sd = _make(-1)
    result = sd.process(samples, callback=cb).sort_by_start_time()
    if len({r.speaker for r in result}) > MAX_SPEAKERS:
        result = _make(MAX_SPEAKERS).process(samples, callback=cb).sort_by_start_time()
    order: dict[int, int] = {}
    turns = []
    for r in result:
        spk = order.setdefault(r.speaker, len(order))
        turns.append(Turn(r.start, r.end, spk))
    return turns
