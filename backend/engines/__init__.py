"""Speech-recognition engines and the choice between them.

An engine has `name` ("ct2" | "whispercpp"), `device` ("cuda" | "vulkan" | "cpu") and
  load(model, progress)                        -> None   (downloads/loads the model)
  transcribe(samples, duration, progress)      -> (list[Word], language)
samples: float32, 16 kHz, mono. Word.text keeps faster-whisper's leading space.

`choose()` and `available_engines()` are pure (hardware + probe results are passed in),
so they are unit-tested with fake hardware.
"""
from __future__ import annotations

from typing import Callable, Protocol

import numpy as np

from ..hardware import GB, best_gpu
from ..merge import Word


class Engine(Protocol):
    name: str
    device: str

    def load(self, model: str, progress: Callable[[float], None] | None = None) -> None: ...

    def transcribe(self, samples: np.ndarray, duration: float,
                   progress: Callable[[float], None]) -> tuple[list[Word], str]: ...


ENGINE_IDS = ("auto", "ct2-cuda", "ct2-cpu", "whispercpp")


def wcpp_available() -> tuple[bool, str]:
    """(ok, reason) for the optional whisper.cpp/Vulkan engine; any import problem = not available."""
    try:
        from . import whispercpp

        return whispercpp.available()
    except Exception as e:  # ImportError, missing DLLs ...
        return False, f"{type(e).__name__}: {e}"


def cuda_status() -> tuple[bool, str]:
    from . import ct2

    return ct2.cuda_status()


def available_engines(hw: dict, cuda: tuple[bool, str] | None = None,
                      wcpp: tuple[bool, str] | None = None) -> list[dict]:
    """[{id, ok, reason, detail}] - reason is a short code the UI translates."""
    nv = best_gpu(hw, "NVIDIA")
    cuda = cuda if cuda is not None else (cuda_status() if nv else (False, ""))
    out = []
    if not nv:
        out.append({"id": "ct2-cuda", "ok": False, "reason": "no_nvidia", "detail": ""})
    elif not cuda[0]:
        out.append({"id": "ct2-cuda", "ok": False, "reason": "no_cuda", "detail": cuda[1]})
    else:
        out.append({"id": "ct2-cuda", "ok": True, "reason": "ok", "detail": ""})
    out.append({"id": "ct2-cpu", "ok": True, "reason": "ok", "detail": ""})
    if not hw.get("gpus"):
        out.append({"id": "whispercpp", "ok": False, "reason": "no_gpu", "detail": ""})
    elif not hw.get("vulkan"):
        out.append({"id": "whispercpp", "ok": False, "reason": "no_vulkan", "detail": ""})
    else:
        wcpp = wcpp if wcpp is not None else wcpp_available()
        if wcpp[0]:
            out.append({"id": "whispercpp", "ok": True, "reason": "ok", "detail": ""})
        else:
            out.append({"id": "whispercpp", "ok": False, "reason": "wcpp_missing", "detail": wcpp[1]})
    return out


def choose(hw: dict, settings: dict, cuda: tuple[bool, str] | None = None,
           wcpp: tuple[bool, str] | None = None) -> dict:
    """Pick engine/device/compute. settings["engine"]: auto | ct2-cuda | ct2-cpu | whispercpp.

    A forced choice that cannot work falls back to auto ("fallback_from" says what was asked)."""
    ok = {e["id"]: e["ok"] for e in available_engines(hw, cuda, wcpp)}
    want = settings.get("engine") or "auto"
    nv = best_gpu(hw, "NVIDIA")
    compute = "float16" if nv and nv["vram"] >= 4 * GB else "int8_float16"

    def plan(engine, device, comp, reason, fb=None):
        return {"engine": engine, "device": device, "compute": comp, "reason": reason,
                "requested": want, "fallback_from": fb}

    if want == "ct2-cpu":
        return plan("ct2", "cpu", "int8", "forced_cpu")
    fb = None
    if want == "ct2-cuda":
        if ok["ct2-cuda"]:
            return plan("ct2", "cuda", compute, "forced_cuda")
        fb = want
    elif want == "whispercpp":
        if ok["whispercpp"]:
            return plan("whispercpp", "vulkan", "fp16", "forced_vulkan")
        fb = want
    if ok["ct2-cuda"]:
        return plan("ct2", "cuda", compute, "auto_cuda", fb)
    if ok["whispercpp"]:
        return plan("whispercpp", "vulkan", "fp16", "auto_vulkan", fb)
    return plan("ct2", "cpu", "int8", "auto_cpu", fb)


def create(p: dict) -> Engine:
    """Instantiate the engine for a plan from choose()."""
    if p["engine"] == "whispercpp":
        from .whispercpp import WhisperCppEngine

        return WhisperCppEngine()
    from .ct2 import CT2Engine

    return CT2Engine(p["device"], p["compute"])
