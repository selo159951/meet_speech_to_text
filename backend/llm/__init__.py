"""Local LLM: runs llama.cpp's llama-completion.exe (Vulkan or CPU) once per call.

Same pattern as engines/whispercpp.py: a child process, UTF-8 in and out, no console window.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from . import catalog

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_DEVICE_RE = re.compile(r"^\s*Vulkan(\d+):\s*(.+?)\s*\((\d+)\s*MiB(?:,\s*(\d+)\s*MiB free)?\)", re.M)
_THINK_RE = re.compile(r"<think>.*?</think>", re.S)
_END_RE = re.compile(r"\s*\[end of text\]\s*$")


class LlmError(Exception):
    pass


class Cancelled(Exception):
    pass


def binary_dir() -> Path:
    env = os.environ.get("KATIP_LLAMACPP_DIR")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS) / "llamacpp"
    return Path(__file__).resolve().parents[2] / "vendor" / "llamacpp"


def binary_path() -> Path:
    return binary_dir() / ("llama-completion.exe" if os.name == "nt" else "llama-completion")


def approx_tokens(text: str) -> int:
    return len(text) // 3 + 1


def _run_kwargs() -> dict:
    kw: dict = {"creationflags": _CREATE_NO_WINDOW}
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kw["startupinfo"] = si
    return kw


# ---------- devices ----------
def parse_devices(text: str) -> list[dict]:
    """Output of ``llama-completion --list-devices`` -> [{"index", "name", "total_mb", "free_mb"}]."""
    return [{"index": int(m.group(1)), "name": m.group(2), "total_mb": int(m.group(3)),
             "free_mb": int(m.group(4) or m.group(3))} for m in _DEVICE_RE.finditer(text)]


_devices_cache: list[dict] | None = None


def list_devices(refresh: bool = False) -> list[dict]:
    global _devices_cache
    if _devices_cache is not None and not refresh:
        return _devices_cache
    exe = binary_path()
    devs: list[dict] = []
    if exe.is_file():
        try:
            p = subprocess.run([str(exe), "--list-devices"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=60,
                               cwd=str(exe.parent), **_run_kwargs())
            devs = parse_devices((p.stdout or "") + "\n" + (p.stderr or ""))
        except (OSError, subprocess.SubprocessError):
            devs = []
    _devices_cache = devs
    return devs


def choose_device(hw: dict, devs: list[dict], need_gb: float) -> tuple[str, int | None]:
    """("vulkan", index) for a real card the model fits in, else ("cpu", None)."""
    card = catalog.discrete_gpu(hw)
    if not card or not hw.get("vulkan", True):
        return "cpu", None
    n = card["name"].lower()
    d = next((d for d in devs if d["name"].lower() in n or n in d["name"].lower()), None)
    if not d or d["free_mb"] / 1024 < need_gb:
        return "cpu", None
    return "vulkan", d["index"]


def _ctx(prompt_tokens: int, max_tokens: int) -> int:
    return min(max(4096, prompt_tokens + max_tokens + 512), 16384)


def plan(hw: dict | None = None, devs: list[dict] | None = None) -> dict:
    from .. import hardware

    hw = hw if hw is not None else hardware.info()
    name = catalog.active(hw)
    if not name:
        raise LlmError("no language model downloaded")
    device, idx = choose_device(hw, list_devices() if devs is None else devs, catalog.get(name)["need_gb"])
    return {"model": name, "path": str(catalog.path_of(name)), "device": device,
            "gpu_index": idx, "ctx": 4096}


def available() -> bool:
    try:
        return binary_path().is_file() and catalog.active() is not None
    except Exception:
        return False


# ---------- output ----------
def extract_json(text: str) -> dict:
    text = _THINK_RE.sub("", text)
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b < a:
        raise LlmError("no JSON in model output: " + text[-300:])
    try:
        return json.loads(text[a:b + 1])
    except ValueError as e:
        raise LlmError(f"invalid JSON from model: {e}") from e


def build_command(p: dict, prompt_file: str, system_file: str | None, schema: dict | None,
                  max_tokens: int, temperature: float, ctx: int) -> list[str]:
    cmd = [str(binary_path()), "-m", p["path"], "-f", prompt_file]
    if system_file:
        cmd += ["-sysf", system_file]
    if schema is not None:
        cmd += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
    cmd += ["-no-cnv", "--jinja", "--simple-io", "--no-display-prompt"]
    if p["device"] == "vulkan":
        cmd += ["-ngl", "999", "-dev", f"Vulkan{p['gpu_index']}"]
    else:
        cmd += ["-ngl", "0", "-dev", "none"]  # really CPU: otherwise Vulkan still takes the prompt
    cmd += ["-c", str(ctx), "-n", str(max_tokens), "--temp", str(temperature), "--reasoning-budget", "0"]
    return cmd


# llama-completion runs as plain completion (its conversation mode needs a terminal), so the
# chat format the model was trained on is written out here for the models whose format is known.
TEMPLATES = {
    "gemma": "<start_of_turn>user\n{system}\n\n{prompt}<end_of_turn>\n<start_of_turn>model\n",
    "chatml": "<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
}


def wrap(model: str, prompt: str, system: str | None) -> tuple[str, str | None]:
    t = TEMPLATES.get(catalog.get(model).get("template") or "")
    if not t:
        return prompt, system
    return t.format(system=system or "You are a helpful assistant.", prompt=prompt), None


def generate(prompt: str, schema: dict | None = None, system: str | None = None,
             max_tokens: int = 2048, temperature: float = 0.2,
             cancel: threading.Event | None = None) -> dict | str:
    if not binary_path().is_file():
        raise LlmError(f"llama.cpp binary not found: {binary_path()}")
    p = plan()
    ctx = _ctx(approx_tokens(prompt + (system or "")), max_tokens)
    p["ctx"] = ctx
    prompt, system = wrap(p["model"], prompt, system)
    with tempfile.TemporaryDirectory(prefix="mt_llm_") as td:
        pf = Path(td) / "prompt.txt"
        pf.write_text(prompt, "utf-8")
        sf = None
        if system:
            sf = str(Path(td) / "system.txt")
            Path(sf).write_text(system, "utf-8")
        cmd = build_command(p, str(pf), sf, schema, max_tokens, temperature, ctx)
        out_f, err_f = Path(td) / "out.txt", Path(td) / "err.txt"
        with open(out_f, "wb") as fo, open(err_f, "wb") as fe:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=fo, stderr=fe,
                                    cwd=str(binary_path().parent), **_run_kwargs())
            while True:
                if cancel is not None and cancel.is_set():
                    proc.kill()
                    proc.wait()
                    raise Cancelled()
                try:
                    proc.wait(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
        out = out_f.read_bytes().decode("utf-8", errors="replace")
        err = err_f.read_bytes().decode("utf-8", errors="replace")
    if proc.returncode != 0:
        raise LlmError(f"llama-completion failed (exit {proc.returncode}): {err[-800:]}")
    if schema is None:
        return _END_RE.sub("", _THINK_RE.sub("", out)).strip()
    try:
        return extract_json(out)
    except LlmError as e:
        raise LlmError(f"{e}\n{err[-800:]}") from e
