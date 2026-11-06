"""Whisper model choice, recommendation and download (with real progress)."""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from . import store

GB = 1024 ** 3

# vram = measured/estimated GPU memory incl. the CUDA context at float16; size = download size.
MODELS = {
    "large-v3-turbo": {"repo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo", "size": int(1.62 * GB),
                       "vram": 2.3, "ram": 3.0, "quality": 3, "speed": 2},
    "medium": {"repo": "Systran/faster-whisper-medium", "size": int(1.53 * GB),
               "vram": 3.0, "ram": 3.0, "quality": 2, "speed": 1},
    "small": {"repo": "Systran/faster-whisper-small", "size": int(0.48 * GB),
              "vram": 1.4, "ram": 1.5, "quality": 1, "speed": 3},
}
DEFAULT = os.environ.get("MEETTRANSCRIBER_MODEL", "large-v3-turbo")


def root() -> Path:
    """Where Whisper models live (MEETTRANSCRIBER_MODEL_DIR overrides, e.g. for tests)."""
    env = os.environ.get("MEETTRANSCRIBER_MODEL_DIR")
    return Path(env) if env else store.data_dir() / "models"


def _cache_dir(name: str) -> Path:
    return root() / ("models--" + MODELS[name]["repo"].replace("/", "--"))


def is_downloaded(name: str) -> bool:
    if name not in MODELS:
        return False
    return any(p.is_file() for p in (_cache_dir(name) / "snapshots").glob("*/model.bin"))


def downloaded() -> list[str]:
    return [n for n in MODELS if is_downloaded(n)]


def disk_bytes(name: str) -> int:
    total = 0
    for p in _cache_dir(name).rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def effective_vram_gb(hw: dict, plan_device: str) -> float | None:
    """GPU memory that the engine may use, or None for CPU."""
    if plan_device == "cpu":
        return None
    from .hardware import best_gpu

    g = best_gpu(hw, "NVIDIA" if plan_device == "cuda" else None)
    if not g:
        return None
    return round((g.get("free") or g["vram"]) / GB, 1) if g["vram"] else None


def recommend(hw: dict, plan_device: str) -> str:
    """Best model for this PC. Rules are deliberately simple and explainable."""
    vram = effective_vram_gb(hw, plan_device)
    ram = hw.get("ram", {}).get("total_gb") or 0
    cores = hw.get("cpu", {}).get("cores") or 1
    if plan_device != "cpu":
        if vram is None or vram >= 3.0:  # unknown VRAM: assume a normal card
            return "large-v3-turbo"
        return "small"
    # CPU only: the big model is ~3x slower than 'small'
    if ram and ram < 6:
        return "small"
    return "large-v3-turbo" if cores >= 8 else "small"


def fit(name: str, hw: dict, plan_device: str, compute: str = "float16") -> str:
    """'ok' | 'tight' | 'cpu' - does the model comfortably fit the device that will run it?"""
    if plan_device == "cpu":
        return "cpu"
    vram = effective_vram_gb(hw, plan_device)
    if vram is None:
        return "ok"
    need = MODELS[name]["vram"] * (0.7 if compute == "int8_float16" else 1.0)
    return "ok" if vram >= need + 1.0 else "tight" if vram >= need else "too_big"


def catalog(hw: dict, plan_device: str, compute: str, current: str) -> list[dict]:
    rec = recommend(hw, plan_device)
    return [{"id": n, "size": m["size"], "quality": m["quality"], "speed": m["speed"],
             "downloaded": is_downloaded(n), "recommended": n == rec, "current": n == current,
             "fit": fit(n, hw, plan_device, compute)} for n, m in MODELS.items()]


# ---------------- download with progress ----------------
_dl: dict = {"state": "idle", "model": None, "done": 0, "total": 0, "error": None}
_dl_lock = threading.Lock()


def download_status() -> dict:
    with _dl_lock:
        return dict(_dl)


def start_download(name: str) -> dict:
    if name not in MODELS:
        raise ValueError("unknown model")
    with _dl_lock:
        if _dl["state"] == "running":
            return dict(_dl)
        _dl.update(state="running", model=name, done=disk_bytes(name), total=MODELS[name]["size"], error=None)
    threading.Thread(target=_download, args=(name,), daemon=True).start()
    return download_status()


def _download(name: str) -> None:
    stop = threading.Event()

    def poll():  # bytes on disk (incl. *.incomplete files) against the known size
        while not stop.wait(0.4):
            with _dl_lock:
                _dl["done"] = min(disk_bytes(name), MODELS[name]["size"])

    threading.Thread(target=poll, daemon=True).start()
    try:
        from faster_whisper.utils import download_model

        root().mkdir(parents=True, exist_ok=True)
        download_model(MODELS[name]["repo"], cache_dir=str(root()))
        stop.set()
        with _dl_lock:
            _dl.update(state="done", done=_dl["total"])
    except Exception as e:
        stop.set()
        with _dl_lock:
            _dl.update(state="error", error=f"{type(e).__name__}: {e}")
