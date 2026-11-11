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

    def transcribe(self, samples: np.ndarray, duration: float,
                   progress: Callable[[float], None]) -> tuple[list[Word], str]:
        from .. import asr

        mode = asr.language_mode()
        # auto: one language per part; mixed: the language is detected for every 30 s window, so a
        # sentence in English inside a Turkish meeting is written in English (and the other way round)
        segs, info = self._model.transcribe(
            samples, language=mode if mode not in ("auto", "mixed") else None, multilingual=(mode == "mixed"),
            word_timestamps=True, vad_filter=True, condition_on_previous_text=False,
        )
        words: list[Word] = []
        for seg in segs:
            for w in seg.words or []:
                words.append(Word(w.start, w.end, w.word))
            progress(min(seg.end / duration, 1.0))
        return words, info.language
