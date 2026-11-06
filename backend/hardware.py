"""What this PC can do: GPUs (+VRAM), CPU, RAM, Vulkan runtime.

Parsing is kept in small pure functions (unit-tested with fake data); the Windows
calls (registry, nvidia-smi, GlobalMemoryStatusEx) are thin wrappers around them.
Results are cached; nothing here opens a console window.
"""
from __future__ import annotations

import os
import subprocess
import re
import threading
from pathlib import Path

GB = 1024 ** 3
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_GPU_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
_VIRTUAL = ("microsoft basic", "remote display", "virtual", "parsec", "citrix", "vmware", "displaylink",
            "meta virtual", "idd ")

_cache: dict | None = None
_lock = threading.Lock()


# ---------------- pure parsing ----------------
def vendor_of(name: str, vendor_id: str = "") -> str:
    n = (name or "").lower()
    v = (vendor_id or "").upper()
    if "nvidia" in n or "geforce" in n or "quadro" in n or "rtx" in n or "VEN_10DE" in v:
        return "NVIDIA"
    if "amd" in n or "radeon" in n or "ati " in n or "VEN_1002" in v:
        return "AMD"
    if "intel" in n or "arc" in n.split() or "iris" in n or "uhd" in n or "VEN_8086" in v:
        return "Intel"
    return "other"


def is_integrated(name: str, vendor: str) -> bool:
    """Onboard graphics share system RAM: their "VRAM" is not real video memory and they are
    usually slower than the CPU for Whisper. Discrete: NVIDIA, Intel Arc A/B-series, AMD RX/Pro."""
    n = (name or "").lower()
    if vendor == "Intel":
        return not re.search(r"arc(\(tm\))?\s*(pro\s*)?[ab]\d{2,3}", n) and "iris xe max" not in n
    if vendor == "AMD":
        discrete = re.search(r"\brx\s*\d|radeon\s*pro\s*w|radeon\s*vii|firepro|instinct", n)
        return not discrete
    return False


def is_real_gpu(name: str) -> bool:
    n = (name or "").lower()
    return bool(n) and not any(x in n for x in _VIRTUAL)


def parse_memory_value(raw) -> int:
    """Registry HardwareInformation.qwMemorySize: int (QWORD) or little-endian bytes."""
    if isinstance(raw, (bytes, bytearray)):
        return int.from_bytes(bytes(raw)[:8], "little")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def build_gpus(adapters: list[dict]) -> list[dict]:
    """adapters: [{name, vram (bytes, may be 0), ven (optional PCI id string)}] -> clean GPU list.

    Drops virtual adapters and duplicates, sorts dedicated (big VRAM) cards first."""
    out, seen = [], set()
    for a in adapters:
        name = (a.get("name") or "").strip()
        if not is_real_gpu(name):
            continue
        vram = int(a.get("vram") or 0)
        key = (name, vram)
        if key in seen:
            continue
        seen.add(key)
        vendor = vendor_of(name, a.get("ven", ""))
        out.append({"name": name, "vendor": vendor, "vram": vram, "vram_gb": round(vram / GB, 1),
                    "integrated": is_integrated(name, vendor)})
    out.sort(key=lambda g: (g["integrated"], -g["vram"]))  # real graphics cards first
    return out


def parse_nvidia_smi(text: str) -> list[dict]:
    """Output of: nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader,nounits"""
    res = []
    for line in (text or "").strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            res.append({"name": parts[0], "total": int(float(parts[1]) * 1024 * 1024),
                        "free": int(float(parts[2]) * 1024 * 1024)})
        except ValueError:
            continue
    return res


def parse_wmi_json(text: str) -> list[dict]:
    """Output of: Get-CimInstance Win32_VideoController | Select Name,AdapterRAM | ConvertTo-Json"""
    import json

    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    if isinstance(data, dict):
        data = [data]
    return [{"name": d.get("Name"), "vram": int(d.get("AdapterRAM") or 0)} for d in data if isinstance(d, dict)]


# ---------------- Windows probes ----------------
def _run(cmd: list[str], timeout: float = 8) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def _registry_adapters() -> list[dict]:
    if os.name != "nt":
        return []
    import winreg

    res = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _GPU_CLASS)
    except OSError:
        return []
    with root:
        for i in range(64):
            try:
                sub = winreg.EnumKey(root, i)
            except OSError:
                break
            if not sub.isdigit():
                continue
            try:
                with winreg.OpenKey(root, sub) as k:
                    def val(n):
                        try:
                            return winreg.QueryValueEx(k, n)[0]
                        except OSError:
                            return None
                    name = val("DriverDesc")
                    if not name:
                        continue
                    vram = parse_memory_value(val("HardwareInformation.qwMemorySize"))
                    if not vram:  # old drivers store a 32-bit value
                        vram = parse_memory_value(val("HardwareInformation.MemorySize"))
                    res.append({"name": name, "vram": vram, "ven": str(val("MatchingDeviceId") or "")})
            except OSError:
                continue
    return res


def _wmi_adapters() -> list[dict]:
    if os.name != "nt":
        return []
    out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM | ConvertTo-Json"], 15)
    return parse_wmi_json(out)


def nvidia_smi() -> list[dict]:
    return parse_nvidia_smi(_run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
                                  "--format=csv,noheader,nounits"], 6))


def detect_gpus() -> list[dict]:
    reg = _registry_adapters()
    gpus = build_gpus(reg)
    if not gpus or any(g["vram"] == 0 for g in gpus):  # missing size -> ask WMI (capped at 4 GB there)
        wmi = {a["name"]: a["vram"] for a in _wmi_adapters() if a.get("name")}
        if not gpus:
            gpus = build_gpus([{"name": n, "vram": v} for n, v in wmi.items()])
        else:
            for g in gpus:
                if not g["vram"] and wmi.get(g["name"]):
                    g["vram"] = wmi[g["name"]]
                    g["vram_gb"] = round(g["vram"] / GB, 1)
    smi = nvidia_smi()  # exact numbers for NVIDIA (the registry value can be wrong on 4 GB+ cards)
    for g in gpus:
        if g["vendor"] == "NVIDIA":
            m = next((s for s in smi if s["name"] == g["name"]), None) or (smi[0] if len(smi) == 1 else None)
            if m:
                g["vram"], g["vram_gb"], g["free"] = m["total"], round(m["total"] / GB, 1), m["free"]
    return gpus


def cpu_name() -> str:
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                return " ".join(str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).split())
        except OSError:
            pass
    import platform

    return platform.processor() or "CPU"


def memory() -> dict:
    """{"total": bytes, "available": bytes} via GlobalMemoryStatusEx (0s if unknown)."""
    if os.name != "nt":
        return {"total": 0, "available": 0}
    import ctypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]

    st = MEMORYSTATUSEX()
    st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
        return {"total": 0, "available": 0}
    return {"total": int(st.ullTotalPhys), "available": int(st.ullAvailPhys)}


def vulkan_runtime() -> bool:
    root = os.environ.get("SystemRoot", r"C:\Windows")
    return (Path(root) / "System32" / "vulkan-1.dll").is_file()


# ---------------- public ----------------
def info(refresh: bool = False) -> dict:
    """Cached hardware description (JSON-able). refresh=True re-reads everything."""
    global _cache
    with _lock:
        if _cache is None or refresh:
            mem = memory()
            _cache = {
                "gpus": detect_gpus(),
                "cpu": {"name": cpu_name(), "cores": os.cpu_count() or 1},
                "ram": {"total": mem["total"], "available": mem["available"],
                        "total_gb": round(mem["total"] / GB, 1)},
                "vulkan": vulkan_runtime(),
            }
        return _cache


def refresh_free() -> dict:
    """Current memory numbers (free VRAM for NVIDIA, available RAM) on top of the cached description."""
    hw = info()
    mem = memory()
    hw["ram"]["available"] = mem["available"]
    smi = nvidia_smi()
    for g in hw["gpus"]:
        m = next((s for s in smi if s["name"] == g["name"]), None)
        if g["vendor"] == "NVIDIA" and m:
            g["free"] = m["free"]
    return hw


def best_gpu(hw: dict, vendor: str | None = None) -> dict | None:
    """Prefers a real graphics card over onboard graphics (whose memory is shared RAM)."""
    gs = [g for g in hw.get("gpus", []) if vendor is None or g["vendor"] == vendor]
    return min(gs, key=lambda g: (g.get("integrated", False), -g["vram"])) if gs else None
