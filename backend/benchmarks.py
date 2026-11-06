"""Seconds per audio-minute for transcription and speaker separation, per engine/model.

Stored in data_dir/benchmarks.json. The speed test seeds the numbers; every finished
real job updates them with a moving average, so estimates get better with use.
"""
from __future__ import annotations

import json
import threading

from . import store

# Measured defaults (RTX 1000 Ada / 22 cores) used until a real measurement exists.
DEFAULTS = {
    "cuda": {"asr": 3.2, "diar": 2.4, "parallel": True},
    "vulkan": {"asr": 8.0, "diar": 2.4, "parallel": True},
    "cpu": {"asr": 20.0, "diar": 2.4, "parallel": False},
}
MODEL_FACTOR = {"large-v3-turbo": 1.0, "medium": 1.8, "small": 0.5}  # relative to turbo, for defaults
OVERHEAD = 8.0   # seconds: decoding + model loading
ALPHA = 0.4      # weight of a new real job in the moving average
_lock = threading.Lock()


def _file():
    return store.data_dir() / "benchmarks.json"


def load() -> dict:
    try:
        return json.loads(_file().read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _save(d: dict) -> None:
    _file().write_text(json.dumps(d), "utf-8")


def blend(old: float | None, new: float, alpha: float = ALPHA) -> float:
    return new if old is None else old * (1 - alpha) + new * alpha


def set_result(key: str, asr_spm: float, diar_spm: float, source: str = "test") -> None:
    """A speed test replaces the numbers for this key."""
    with _lock:
        d = load()
        d[key] = {"asr": round(asr_spm, 2), "diar": round(diar_spm, 2), "source": source, "n": 1}
        _save(d)


def record(timings: dict, key: str | None = None, resumed: bool = False) -> None:
    """Called when a real job finishes. Skips tiny files and resumed jobs (partial timings)."""
    try:
        audio = float(timings.get("audio") or 0)
        if resumed or audio < 60 or not timings.get("asr"):
            return
        if key is None:
            from . import asr

            key = asr.key()
        mins = audio / 60
        with _lock:
            d = load()
            cur = d.get(key, {})
            d[key] = {"asr": round(blend(cur.get("asr"), timings["asr"] / mins), 2),
                      "diar": round(blend(cur.get("diar"), (timings.get("diar") or 0) / mins), 2),
                      "source": "jobs", "n": cur.get("n", 0) + 1}
            _save(d)
    except Exception:  # never break a finished job because of statistics
        pass


def per_minute(key: str) -> dict:
    """{"asr", "diar", "parallel", "source"} for a key like 'ct2/cuda/large-v3-turbo'."""
    r = load().get(key)
    device = key.split("/")[1] if key.count("/") >= 2 else "cpu"
    base = DEFAULTS.get(device, DEFAULTS["cpu"])
    if r:
        return {"asr": r["asr"], "diar": r["diar"], "parallel": base["parallel"], "source": "measured"}
    f = MODEL_FACTOR.get(key.rsplit("/", 1)[-1], 1.0)
    return {"asr": round(base["asr"] * f, 2), "diar": base["diar"], "parallel": base["parallel"],
            "source": "default"}


def estimate(key: str, duration_s: float) -> dict:
    pm = per_minute(key)
    mins = max(duration_s, 0) / 60
    a, d = pm["asr"] * mins, pm["diar"] * mins
    total = (max(a, d) if pm["parallel"] else a + d) + OVERHEAD
    return {"seconds": round(total), "asr": round(a), "diar": round(d), "source": pm["source"]}
