"""CTranslate2 / faster-whisper engine: NVIDIA CUDA or CPU."""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Callable

import numpy as np

from .. import models
from ..merge import Word


def _register_cuda_dlls() -> None:
    """Make pip-installed nvidia-* DLLs (cuBLAS, cuDNN) loadable on Windows."""
    if os.name != "nt":
        return
    roots = [Path(p) / "nvidia" for p in sys.path if p]
    if getattr(sys, "_MEIPASS", None):
        roots.append(Path(sys._MEIPASS) / "nvidia")
    for root in roots:
        if not root.is_dir():
            continue
        for bin_dir in root.glob("*/bin"):
            try:
                os.add_dll_directory(str(bin_dir))
            except OSError:
                pass
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


_register_cuda_dlls()

_cuda: tuple[bool, str] | None = None


def cuda_status() -> tuple[bool, str]:
    """(ok, detail): a CUDA GPU exists AND the CUDA libraries really load. Probed once."""
    global _cuda
    if _cuda is None:
        try:
            import ctranslate2

            n = ctranslate2.get_cuda_device_count()
            err = "No CUDA device"
        except Exception as e:
            n, err = 0, str(e)
        if n == 0:
            _cuda = (False, err)
        else:
            try:
                if os.name == "nt":
                    import ctypes

                    ctypes.WinDLL("cublas64_12.dll")
                    ctypes.WinDLL("cudnn64_9.dll")
                _cuda = (True, "")
            except Exception as e:
                _cuda = (False, f"CUDA libraries missing: {e}")
    return _cuda


def mark_cuda_broken(err: str) -> None:
    global _cuda
    _cuda = (False, err)


class CT2Engine:
    name = "ct2"

    def __init__(self, device: str = "cpu", compute: str = "int8"):
        self.device = device
        self.compute = compute
        self.error: str | None = None  # why a GPU request fell back to CPU
        self._model = None
        self._lock = threading.Lock()

    def _create(self, model: str, device: str, compute: str):
        from faster_whisper import WhisperModel

        models.root().mkdir(parents=True, exist_ok=True)
        return WhisperModel(models.MODELS[model]["repo"] if model in models.MODELS else model,
                            device=device, compute_type=compute, download_root=str(models.root()))

    def load(self, model: str, progress: Callable[[float], None] | None = None) -> None:
        with self._lock:
            if self._model is not None:
                return
            if self.device == "cuda":
                try:
                    m = self._create(model, "cuda", self.compute)
                    list(m.transcribe(np.zeros(16000, np.float32), language="en")[0])  # real probe
                    self._model = m
                    return
                except Exception as e:
                    print("GPU failed, using CPU:", e)
                    self.error = str(e)
                    mark_cuda_broken(self.error)
                    self.device, self.compute = "cpu", "int8"
            self._model = self._create(model, "cpu", "int8")

    def vote_languages(self, samples: np.ndarray, windows: int = 12) -> list[tuple[str, float]]:
        """Which languages are spoken in the WHOLE recording: the language is detected in up to 12 evenly
        spaced 30 s windows and the probabilities are averaged. [(language, share)] best first.
        (Detecting only the first 30 s of a part, or every window on its own, wrote English speech as
        Turkish text whenever one window sounded Turkish.)"""
        sr, win = 16000, 30 * 16000
        n = len(samples)
        starts = [0] if n <= win else sorted({int(x) for x in np.linspace(0, n - win, min(windows, max(1, n // win)))})
        total: dict[str, float] = {}
        used = 0
        for a in starts:
            chunk = samples[a:a + win]
            if float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2))) < 0.005:  # silence says nothing about the language
                continue
            with self._lock:
                _, _, probs = self._model.detect_language(chunk, vad_filter=True)
            for lang, p in probs:
                total[lang] = total.get(lang, 0.0) + float(p)
            used += 1
        if not used:
            return []
        return sorted(((l, v / used) for l, v in total.items()), key=lambda t: -t[1])[:3]

    def _decode(self, audio: np.ndarray, language: str | None, offset: float = 0.0) -> tuple[list[Word], str]:
        segs, info = self._model.transcribe(audio, language=language, word_timestamps=True, vad_filter=True,
                                            condition_on_previous_text=False)
        words = [Word(w.start + offset, w.end + offset, w.word, float(w.probability))
                 for seg in segs for w in (seg.words or [])]
        return words, info.language

    def transcribe(self, samples: np.ndarray, duration: float,
                   progress: Callable[[float], None]) -> tuple[list[Word], str]:
        from .. import asr

        mode = asr.language_mode()
        voted = asr.recording_languages()  # [(language, share)] for this recording, best first
        main = voted[0][0] if voted else None
        if mode == "mixed" and len([1 for _, share in voted if share >= 0.15]) > 1:
            return self._transcribe_mixed(samples, duration, progress, voted)
        # a fixed language, or the language of the recording as a whole: the speech is written, never translated
        language = mode if mode not in ("auto", "mixed") else main
        segs, info = self._model.transcribe(
            samples, language=language, word_timestamps=True, vad_filter=True, condition_on_previous_text=False,
        )
        words: list[Word] = []
        for seg in segs:
            for w in seg.words or []:
                words.append(Word(w.start, w.end, w.word, float(w.probability)))
            progress(min(seg.end / duration, 1.0))
        return words, language or info.language

    def _transcribe_mixed(self, samples, duration, progress, voted):
        """Two languages in one meeting: every ~25 s window is written in each language that is really
        spoken in the recording and the version the model is more sure about wins. A language the
        recording does not contain is never tried, so English speech cannot come out as Turkish text."""
        from ..chunking import speech_regions

        cands = [l for l, share in voted if share >= 0.15][:2] or [voted[0][0]]
        sr = 16000
        wins, cur = [], None
        for a, b in speech_regions(samples) or [(0.0, len(samples) / sr)]:
            if cur and b - cur[0] <= 25.0:
                cur[1] = b
            else:
                cur = [a, b]
                wins.append(cur)
        words: list[Word] = []
        count: dict[str, float] = {}
        for k, (a, b) in enumerate(wins):
            a0, b0 = max(0.0, a - 0.3), min(len(samples) / sr, b + 0.3)
            chunk = samples[int(a0 * sr):int(b0 * sr)]
            best, best_score, best_lang = [], -1.0, cands[0]
            for lang in cands:
                ws, _ = self._decode(chunk, lang, a0)
                tot = sum(max(w.end - w.start, 0.01) for w in ws)
                score = sum(max(w.end - w.start, 0.01) * w.prob for w in ws) / tot if tot else 0.0
                if score > best_score + (0.02 if lang != cands[0] else 0.0):  # ties keep the main language
                    best, best_score, best_lang = ws, score, lang
            words += best
            count[best_lang] = count.get(best_lang, 0.0) + (b - a)
            progress(min(b / duration, 1.0))
        return words, max(count, key=count.get) if count else cands[0]
