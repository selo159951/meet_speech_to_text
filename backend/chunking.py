"""Split long recordings into ~5 minute parts, cutting only where nobody is speaking.

Whisper itself has no length limit here (it works in 30 s windows), but parts make a
crash resumable, keep memory flat and give smooth progress. A cut is never placed
inside a word: it goes in the middle of the longest pause found between 4:30 and
5:00 of the current part. If nobody pauses there, the quietest 200 ms is used.
"""
from __future__ import annotations

from typing import Callable, Sequence

import numpy as np

SR = 16000
TARGET = 300.0       # a part is at most 5:00 ...
EARLIEST = 270.0     # ... and normally ends after 4:30
MIN_GAP = 0.15       # pauses shorter than this are not a safe place to cut


def choose_cuts(duration: float, speech: Sequence[tuple[float, float]],
                quietest: Callable[[float, float], float] | None = None,
                target: float = TARGET, earliest: float = EARLIEST) -> list[tuple[float, float]]:
    """Return [(start, end), …] parts covering 0..duration.

    speech: sorted (start, end) seconds where someone talks (from VAD).
    quietest(a, b): time of the quietest moment in [a, b] - used when there is no pause.
    """
    # pauses = gaps between speech regions, plus leading/trailing silence
    gaps, prev = [], 0.0
    for s, e in speech:
        if s - prev >= MIN_GAP:
            gaps.append((prev, s))
        prev = max(prev, e)
    if duration - prev >= MIN_GAP:
        gaps.append((prev, duration))

    parts, start = [], 0.0
    while duration - start > target:
        lo, hi = start + earliest, start + target
        best, best_len = None, 0.0
        for g0, g1 in gaps:
            a, b = max(g0, lo), min(g1, hi)  # part of the pause inside the window
            if b - a > best_len:
                best, best_len = (a + b) / 2, b - a
        if best is None:
            best = quietest(lo, hi) if quietest else hi
        parts.append((start, best))
        start = best
    parts.append((start, duration))
    return [(round(a, 3), round(b, 3)) for a, b in parts]


def speech_regions(samples: np.ndarray) -> list[tuple[float, float]]:
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    ts = get_speech_timestamps(samples, VadOptions(min_silence_duration_ms=150, speech_pad_ms=60))
    return [(t["start"] / SR, t["end"] / SR) for t in ts]


def quietest_moment(samples: np.ndarray) -> Callable[[float, float], float]:
    def find(a: float, b: float) -> float:
        win = int(0.2 * SR)
        seg = samples[int(a * SR):int(b * SR)]
        if len(seg) < win:
            return (a + b) / 2
        energy = np.convolve(seg.astype(np.float32) ** 2, np.ones(win, np.float32), "valid")
        return a + (int(np.argmin(energy)) + win // 2) / SR
    return find


def split(samples: np.ndarray) -> list[tuple[float, float]]:
    duration = len(samples) / SR
    if duration <= TARGET:
        return [(0.0, round(duration, 3))]
    return choose_cuts(duration, speech_regions(samples), quietest_moment(samples))
