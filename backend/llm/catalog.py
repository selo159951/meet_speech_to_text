"""Local LLM models (GGUF from Hugging Face): catalog, choice, download with resume."""
from __future__ import annotations

import os
import threading
import urllib.request
from pathlib import Path

from .. import models

DEFAULT_SMALL = "qwen3.5-4b"  # measured: best names and tasks of the small ones (docs/toplanti-modu-rapor.md)
DEFAULT_LARGE = "qwen3.5-9b"  # for cards with 8 GB or more

GB = 1024 ** 3


def _m(name, label, repo, file, size_gb, need_gb, min_vram_gb, license):
    return {"name": name, "label": label, "file": file,
            "url": f"https://huggingface.co/{repo}/resolve/main/{file}",
            "size_gb": size_gb, "need_gb": need_gb, "min_vram_gb": min_vram_gb, "license": license}


CATALOG = [
    _m("gemma-3-4b", "Gemma 3 4B", "unsloth/gemma-3-4b-it-GGUF", "gemma-3-4b-it-Q4_K_M.gguf",
       2.49, 3.6, 4, "Gemma"),
    _m("qwen3.5-4b", "Qwen 3.5 4B", "unsloth/Qwen3.5-4B-GGUF", "Qwen3.5-4B-Q4_K_M.gguf",
       2.74, 3.9, 4, "Apache-2.0"),
    _m("gemma-4-e4b", "Gemma 4 E4B", "unsloth/gemma-4-E4B-it-GGUF", "gemma-4-E4B-it-Q4_K_M.gguf",
       4.98, 6.0, 6, "Gemma"),
    _m("qwen3.5-9b", "Qwen 3.5 9B", "unsloth/Qwen3.5-9B-GGUF", "Qwen3.5-9B-Q4_K_M.gguf",
       5.68, 7.0, 8, "Apache-2.0"),
    # gemma-4-12b (7 GB) is left out: in the measurement it returned broken JSON (docs/toplanti-modu-rapor.md)
]

for _e in CATALOG:  # chat format written out by llm.wrap (ChatML for Qwen; Gemma runs as plain completion)
    _e["template"] = "chatml" if _e["name"].startswith("qwen") else "gemma" if _e["name"].startswith("gemma-3") else ""

def get(name: str) -> dict | None:
    return next((m for m in CATALOG if m["name"] == name), None)


def model_dir() -> Path:
    env = os.environ.get("SESDEFTERI_LLM_DIR") or os.environ.get("KATIP_LLM_DIR")
    return Path(env) if env else models.root() / "llm"


def path_of(name: str) -> Path:
    return model_dir() / get(name)["file"]


def is_downloaded(name: str) -> bool:
    m = get(name)
    if not m:
        return False
    p = path_of(name)
    return p.is_file() and p.stat().st_size > m["size_gb"] * GB * 0.9


def downloaded() -> list[str]:
    return [m["name"] for m in CATALOG if is_downloaded(m["name"])]


def discrete_gpu(hw: dict) -> dict | None:
    gs = [g for g in hw.get("gpus", []) if not g.get("integrated")]
    return max(gs, key=lambda g: g["vram"]) if gs else None


def memory_gb(hw: dict) -> float:
    """Memory the model would live in: the card's VRAM if discrete, else RAM."""
    g = discrete_gpu(hw)
    if g:
        return (g.get("free") or g["vram"]) / GB
    return float(hw.get("ram", {}).get("total_gb") or 0)


def recommend(hw: dict) -> str:
    g = discrete_gpu(hw)
    return DEFAULT_LARGE if g and g["vram"] / GB >= 7.5 else DEFAULT_SMALL


def fit(name: str, hw: dict) -> str:
    need = get(name)["need_gb"]
    mem = memory_gb(hw)
    if mem >= need + 1.0:
        return "ok"
    ram = float(hw.get("ram", {}).get("total_gb") or 0)
    # too big for the card but enough RAM: it still runs, on the processor (slower)
    return "tight" if mem >= need or ram >= need + 4 else "no"


def get_setting() -> str:
    from .. import asr

    return asr.get_settings().get("llm_model") or "auto"


def set_setting(name: str) -> None:
    from .. import asr

    asr.set_setting("llm_model", name)


def active(hw: dict | None = None) -> str | None:
    """Setting if downloaded, else the recommended one, else any downloaded one."""
    from .. import hardware

    s = get_setting()
    if s != "auto" and is_downloaded(s):
        return s
    rec = recommend(hw if hw is not None else hardware.info())
    if is_downloaded(rec):
        return rec
    have = downloaded()
    return have[0] if have else None


# ---------------- download ----------------
_dl: dict = {"name": None, "done": 0, "total": 0, "running": False, "error": None}
_lock = threading.Lock()


def download_status() -> dict:
    with _lock:
        return dict(_dl)


def start_download(name: str) -> dict:
    m = get(name)
    if not m:
        raise ValueError("unknown model")
    with _lock:
        if _dl["running"]:
            return dict(_dl)
        _dl.update(name=name, done=0, total=int(m["size_gb"] * GB), running=True, error=None)
    threading.Thread(target=_download, args=(m,), daemon=True).start()
    return download_status()


def _download(m: dict) -> None:
    dest = model_dir() / m["file"]
    part = dest.with_name(dest.name + ".part")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        have = part.stat().st_size if part.is_file() else 0
        headers = {"User-Agent": "SesDefteri"}
        if have:
            headers["Range"] = f"bytes={have}-"
        req = urllib.request.Request(m["url"], headers=headers)
        with urllib.request.urlopen(req, timeout=60) as r:
            if have and r.status != 206:
                have = 0
            length = int(r.headers.get("Content-Length") or 0)
            total = have + length if length else int(m["size_gb"] * GB)
            with _lock:
                _dl.update(done=have, total=total)
            with open(part, "ab" if have else "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    have += len(chunk)
                    with _lock:
                        _dl["done"] = have
        if length and have != total:
            raise RuntimeError(f"incomplete download ({have}/{total} bytes)")
        os.replace(part, dest)
        with _lock:
            _dl.update(running=False, done=_dl["total"])
    except Exception as e:
        with _lock:
            _dl.update(running=False, error=f"{type(e).__name__}: {e}")
