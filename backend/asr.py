"""faster-whisper wrapper with optional GPU (user can switch it on/off)."""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Callable

import numpy as np

from . import store
from .merge import Word

MODEL_NAME = os.environ.get("MEETTRANSCRIBER_MODEL", "large-v3-turbo")
_model = None
_model_device: str | None = None
_gpu_ok: bool | None = None  # cached probe result
_gpu_error: str | None = None
_lock = threading.Lock()


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


# ---------- settings ----------
def _settings_file() -> Path:
    return store.data_dir() / "settings.json"


def get_settings() -> dict:
    try:
        return {"use_gpu": True, **json.loads(_settings_file().read_text("utf-8"))}
    except (OSError, ValueError):
        return {"use_gpu": True}


def set_setting(key: str, value) -> None:
    s = get_settings()
    s[key] = value
    _settings_file().write_text(json.dumps(s), "utf-8")


def set_use_gpu(on: bool) -> None:
    set_setting("use_gpu", bool(on))


# ---------- model ----------
def _create(device: str, compute: str):
    from faster_whisper import WhisperModel

    return WhisperModel(
        MODEL_NAME, device=device, compute_type=compute,
        download_root=str(store.data_dir() / "models"),
    )


def _cuda_device_count() -> int:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count()
    except Exception:
        return 0


def gpu_name() -> str | None:
    try:
        import subprocess

        out = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=5,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return out.stdout.strip().splitlines()[0] or None
    except Exception:
        return None


def gpu_available() -> bool:
    """True only if a CUDA GPU exists AND the CUDA libraries really work (probed once)."""
    global _gpu_ok, _gpu_error
    if _gpu_ok is None:
        if _cuda_device_count() == 0:
            _gpu_ok, _gpu_error = False, "No NVIDIA GPU found"
        else:
            try:
                if os.name == "nt":  # cheap check that the CUDA DLLs can be loaded
                    import ctypes

                    ctypes.WinDLL("cublas64_12.dll")
                    ctypes.WinDLL("cudnn64_9.dll")
                _gpu_ok = True
            except Exception as e:
                _gpu_ok, _gpu_error = False, f"CUDA libraries missing: {e}"
    return _gpu_ok


def status() -> dict:
    return {
        "gpu_available": gpu_available(),
        "gpu_name": gpu_name() if gpu_available() else None,
        "gpu_error": _gpu_error,
        "use_gpu": get_settings()["use_gpu"],
        "ui_lang": get_settings().get("ui_lang"),
        "model": MODEL_NAME,
        "device_in_use": _model_device,
    }


def load_model():
    """Load (or reload) the model on the device chosen by the user setting."""
    global _model, _model_device, _gpu_ok, _gpu_error
    want = "cuda" if (get_settings()["use_gpu"] and gpu_available()) else "cpu"
    with _lock:
        if _model is not None and _model_device == want:
            return _model
        _model = None
        if want == "cuda":
            try:
                m = _create("cuda", "float16")
                list(m.transcribe(np.zeros(16000, np.float32), language="en")[0])  # real probe
                _model, _model_device = m, "cuda"
            except Exception as e:
                print("GPU failed, using CPU:", e)
                _gpu_ok, _gpu_error = False, str(e)
        if _model is None:
            _model, _model_device = _create("cpu", "int8"), "cpu"
    return _model


def transcribe(samples: np.ndarray, duration: float,
               progress: Callable[[float], None]) -> tuple[list[Word], str]:
    model = load_model()
    segs, info = model.transcribe(
        samples, language=None, word_timestamps=True, vad_filter=True,
        condition_on_previous_text=False,
    )
    words: list[Word] = []
    for seg in segs:
        for w in seg.words or []:
            words.append(Word(w.start, w.end, w.word))
        progress(min(seg.end / duration, 1.0))
    return words, info.language
