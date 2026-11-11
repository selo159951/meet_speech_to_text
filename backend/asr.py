"""Thin facade over the speech engines (see backend/engines).

Keeps the functions pipeline.py and bridge.py use: load_model, transcribe, status,
get_settings, set_setting, set_use_gpu. Settings live in data_dir/settings.json:
  engine: auto | ct2-cuda | ct2-cpu | whispercpp     model: large-v3-turbo | medium | small
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Callable

import numpy as np

from . import engines, hardware, models, store
from .merge import Word

MODEL_NAME = models.DEFAULT
_engine = None
_engine_key: tuple | None = None   # what was requested: ((engine, device, compute), model)
_engine_plan: dict | None = None   # what is really running (device may have fallen back)
_lock = threading.Lock()


# ---------- settings ----------
def _settings_file() -> Path:
    return store.data_dir() / "settings.json"


def get_settings() -> dict:
    try:
        s = json.loads(_settings_file().read_text("utf-8"))
    except (OSError, ValueError):
        s = {}
    s.setdefault("use_gpu", True)
    if not s.get("engine"):  # older versions only had the GPU on/off switch
        s["engine"] = "auto" if s["use_gpu"] else "ct2-cpu"
    if s.get("model") not in models.MODELS:
        s["model"] = MODEL_NAME if MODEL_NAME in models.MODELS else "large-v3-turbo"
    return s


def set_setting(key: str, value) -> None:
    try:
        s = json.loads(_settings_file().read_text("utf-8"))
    except (OSError, ValueError):
        s = {}
    s[key] = value
    _settings_file().write_text(json.dumps(s), "utf-8")


def set_use_gpu(on: bool) -> None:
    set_setting("use_gpu", bool(on))
    set_setting("engine", "auto" if on else "ct2-cpu")


def plan() -> dict:
    return engines.choose(hardware.info(), get_settings())


def key() -> str:
    """Benchmark key of what would run now, e.g. 'ct2/cuda/large-v3-turbo'."""
    p = _engine_plan or plan()
    return f"{p['engine']}/{p['device']}/{get_settings()['model']}"


# ---------- engine ----------
def load_model(progress: Callable[[float], None] | None = None):
    """Create/load the engine chosen by settings + hardware (cached while nothing changes)."""
    global _engine, _engine_key, _engine_plan
    p, model = plan(), get_settings()["model"]
    k = ((p["engine"], p["device"], p["compute"]), model)
    with _lock:
        if _engine is not None and _engine_key == k:
            return _engine
        eng = engines.create(p)
        eng.load(model, progress)
        _engine, _engine_key = eng, k
        _engine_plan = dict(p, device=eng.device)  # the engine may have fallen back to CPU
    return _engine


def release() -> None:
    """Drop the loaded speech model so its video memory is free for the analysis model.
    A transcription that is still running keeps its own reference; the next one reloads (a few seconds)."""
    global _engine, _engine_key
    import gc

    with _lock:
        _engine, _engine_key = None, None
    gc.collect()


def transcribe(samples: np.ndarray, duration: float,
               progress: Callable[[float], None]) -> tuple[list[Word], str]:
    return load_model().transcribe(samples, duration, progress)


def status() -> dict:
    hw = hardware.info()
    p = _engine_plan or plan()
    s = get_settings()
    nv = hardware.best_gpu(hw, "NVIDIA")
    gpu = hardware.best_gpu(hw)
    return {
        "gpu_available": p["device"] != "cpu",
        "gpu_name": gpu["name"] if gpu and p["device"] != "cpu" else None,
        "gpu_error": getattr(_engine, "error", None),
        "use_gpu": s["engine"] != "ct2-cpu",
        "ui_lang": s.get("ui_lang"),
        "model": s["model"],
        "device_in_use": _engine.device if _engine else p["device"],
        "engine": s["engine"],
        "engine_in_use": p["engine"],
        "plan": p,
        "model_downloaded": models.is_downloaded(s["model"]),
        "any_model_downloaded": bool(models.downloaded()),
        "has_nvidia": bool(nv),
        "hardware": hw,
    }
