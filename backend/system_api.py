"""Bridge methods for the System page: hardware, engine/model choice, speed test, ETA.

`Api` (bridge.py) inherits from SystemApi, so these are callable as
window.pywebview.api.<method> like everything else.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from . import asr, benchmarks, engines, hardware, models

_test = {"state": "idle", "stage": None, "progress": 0.0, "result": None, "error": None}
_test_lock = threading.Lock()


def sample_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "assets" / "speedtest.wav"


def verdict(hw: dict, plan: dict, model: str) -> dict:
    """Friendly one-line verdict. level: ok | warn | cpu. The UI translates `key`."""
    if plan["device"] == "cpu":
        gpu = hardware.best_gpu(hw)
        return {"level": "cpu", "key": "v_cpu" if not gpu else "v_cpu_gpu_unused"}
    f = models.fit(model, hw, plan["device"], plan["compute"])
    if f == "ok":
        return {"level": "ok", "key": "v_ok"}
    return {"level": "warn", "key": "v_tight"}


def _run_test() -> None:
    from . import audio, diarize

    def upd(**kw):
        with _test_lock:
            _test.update(kw)

    from .pipeline import _queue_lock

    got = False
    try:
        upd(stage="loading", progress=0.0)
        _queue_lock.acquire()
        got = True  # never compete with a running job for the GPU
        samples, duration = audio.decode(sample_path())
        eng = asr.load_model()
        key = asr.key()
        upd(stage="transcribing", progress=0.1)
        t0 = time.time()
        eng.transcribe(samples, duration, lambda p: upd(progress=0.1 + 0.5 * p))
        t_asr = time.time() - t0
        upd(stage="diarizing", progress=0.6)
        t0 = time.time()
        diarize.diarize(samples, lambda p: upd(progress=0.6 + 0.4 * p))
        t_diar = time.time() - t0
        mins = duration / 60
        benchmarks.set_result(key, t_asr / mins, t_diar / mins, "test")
        upd(state="done", stage="done", progress=1.0, error=None,
            result={"key": key, "asr_spm": round(t_asr / mins, 2), "diar_spm": round(t_diar / mins, 2),
                    "seconds_asr": round(t_asr, 1), "seconds_diar": round(t_diar, 1),
                    "sample_seconds": round(duration, 1), "device": eng.device})
    except Exception as e:
        upd(state="error", error=f"{type(e).__name__}: {e}")
    finally:
        if got:
            _queue_lock.release()


class SystemApi:
    def get_system_info(self) -> dict:
        hw = hardware.refresh_free()
        s = asr.get_settings()
        plan = asr.status()["plan"]
        model = s["model"]
        pm = benchmarks.per_minute(asr.key())
        return {
            "hardware": hw,
            "settings": {"engine": s["engine"], "model": model},
            "plan": plan,
            "engines": engines.available_engines(hw),
            "models": models.catalog(hw, plan["device"], plan["compute"], model),
            "verdict": verdict(hw, plan, model),
            "speed": {"asr_spm": pm["asr"], "diar_spm": pm["diar"], "source": pm["source"]},
            "model_downloaded": models.is_downloaded(model),
            "download": models.download_status(),
            "test": self.speed_test_status(),
            "first_run": not models.downloaded(),
        }

    def set_engine(self, engine: str) -> dict:
        if engine not in engines.ENGINE_IDS:
            raise ValueError("unknown engine")
        asr.set_setting("engine", engine)
        asr.set_setting("use_gpu", engine != "ct2-cpu")
        return self.get_system_info()

    def set_model(self, model: str) -> dict:
        if model not in models.MODELS:
            raise ValueError("unknown model")
        asr.set_setting("model", model)
        return self.get_system_info()

    def estimate(self, duration_seconds: float) -> dict:
        return benchmarks.estimate(asr.key(), float(duration_seconds or 0))

    # ---- model download ----
    def download_model(self, model: str | None = None) -> dict:
        return models.start_download(model or asr.get_settings()["model"])

    def download_status(self) -> dict:
        return models.download_status()

    # ---- speed test ----
    def run_speed_test(self) -> dict:
        if not models.is_downloaded(asr.get_settings()["model"]):
            raise ValueError("model not downloaded yet")
        with _test_lock:
            if _test["state"] == "running":
                return dict(_test)
            _test.update(state="running", stage="loading", progress=0.0, result=None, error=None)
        threading.Thread(target=_run_test, daemon=True).start()
        return self.speed_test_status()

    def speed_test_status(self) -> dict:
        with _test_lock:
            return dict(_test)
