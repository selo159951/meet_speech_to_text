import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import benchmarks, engines, hardware, models  # noqa: E402

GB = 1024 ** 3


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MEETTRANSCRIBER_HOME", str(tmp_path))


def hw(*gpus, vulkan=True, cores=8, ram=16):
    return {"gpus": list(gpus), "vulkan": vulkan, "cpu": {"name": "x", "cores": cores},
            "ram": {"total_gb": ram, "total": ram * GB, "available": ram * GB}}


def gpu(name, vendor, gb):
    return {"name": name, "vendor": vendor, "vram": int(gb * GB), "vram_gb": gb}


NV6, NV2 = gpu("RTX 1000 Ada", "NVIDIA", 6), gpu("GTX 1050", "NVIDIA", 2)
AMD = gpu("Radeon RX 6600", "AMD", 8)
OK, NO = (True, ""), (False, "x")


def test_hardware_parsing():
    assert hardware.vendor_of("NVIDIA GeForce RTX 3060") == "NVIDIA"
    assert hardware.vendor_of("AMD Radeon(TM) Graphics") == "AMD"
    assert hardware.vendor_of("Intel(R) UHD Graphics 770") == "Intel"
    assert hardware.vendor_of("Foo", "PCI\\VEN_10DE&DEV_1") == "NVIDIA"
    assert hardware.parse_memory_value((6 * GB).to_bytes(8, "little")) == 6 * GB
    assert hardware.parse_memory_value(None) == 0
    gs = hardware.build_gpus([
        {"name": "Microsoft Basic Display Adapter", "vram": 0},
        {"name": "Intel(R) UHD Graphics", "vram": 128 * 1024 * 1024},
        {"name": "NVIDIA RTX 1000 Ada Generation Laptop GPU", "vram": 6 * GB},
        {"name": "NVIDIA RTX 1000 Ada Generation Laptop GPU", "vram": 6 * GB}])
    assert [g["vendor"] for g in gs] == ["NVIDIA", "Intel"] and gs[0]["vram_gb"] == 6.0
    smi = hardware.parse_nvidia_smi("NVIDIA RTX 1000, 6144, 5000\n")
    assert smi[0]["total"] == 6144 * 1024 * 1024 and smi[0]["free"] == 5000 * 1024 * 1024
    assert hardware.parse_nvidia_smi("garbage") == []
    w = hardware.parse_wmi_json('{"Name": "AMD Radeon", "AdapterRAM": 4293918720}')
    assert w == [{"name": "AMD Radeon", "vram": 4293918720}]
    assert hardware.parse_wmi_json("not json") == []


def test_choose_engine():
    p = engines.choose(hw(NV6), {}, OK, OK)
    assert (p["engine"], p["device"], p["compute"]) == ("ct2", "cuda", "float16")
    p = engines.choose(hw(NV2), {}, OK, OK)
    assert (p["device"], p["compute"]) == ("cuda", "int8_float16")
    p = engines.choose(hw(AMD), {}, NO, OK)
    assert (p["engine"], p["device"]) == ("whispercpp", "vulkan")
    assert engines.choose(hw(AMD), {}, NO, NO)["device"] == "cpu"  # no whisper.cpp -> CPU
    assert engines.choose(hw(AMD, vulkan=False), {}, NO, OK)["device"] == "cpu"
    assert engines.choose(hw(NV6), {}, NO, OK)["engine"] == "whispercpp"  # NVIDIA without CUDA libs
    assert engines.choose(hw(), {}, NO, NO)["device"] == "cpu"


def test_forced_engine_and_fallback():
    assert engines.choose(hw(NV6), {"engine": "ct2-cpu"}, OK, OK)["device"] == "cpu"
    p = engines.choose(hw(AMD), {"engine": "ct2-cuda"}, NO, OK)  # impossible -> auto
    assert p["engine"] == "whispercpp" and p["fallback_from"] == "ct2-cuda"
    assert engines.choose(hw(NV6), {"engine": "whispercpp"}, OK, OK)["device"] == "vulkan"


def test_available_engines_reasons():
    e = {x["id"]: x for x in engines.available_engines(hw(AMD), NO, NO)}
    assert e["ct2-cuda"]["reason"] == "no_nvidia" and e["whispercpp"]["reason"] == "wcpp_missing"
    assert e["ct2-cpu"]["ok"]
    e = {x["id"]: x for x in engines.available_engines(hw(NV6, vulkan=False), NO, OK)}
    assert e["ct2-cuda"]["reason"] == "no_cuda" and e["whispercpp"]["reason"] == "no_vulkan"


def test_missing_whispercpp_module_is_not_available():
    ok, _ = engines.wcpp_available()
    assert isinstance(ok, bool)  # ImportError must never propagate


def test_model_recommendation():
    assert models.recommend(hw(NV6), "cuda") == "large-v3-turbo"
    assert models.recommend(hw(gpu("old", "NVIDIA", 2)), "cuda") == "small"
    assert models.recommend(hw(cores=4), "cpu") == "small"
    assert models.recommend(hw(cores=16, ram=16), "cpu") == "large-v3-turbo"
    assert models.recommend(hw(cores=16, ram=4), "cpu") == "small"
    assert models.fit("large-v3-turbo", hw(NV6), "cuda") == "ok"
    assert models.fit("medium", hw(gpu("g", "NVIDIA", 3.5)), "cuda") == "tight"
    assert models.fit("small", hw(), "cpu") == "cpu"


def test_estimates_default_and_measured():
    k = "ct2/cuda/large-v3-turbo"
    e = benchmarks.estimate(k, 600)  # 10 min on GPU: parallel -> max(32, 24) + overhead
    assert e["source"] == "default" and e["seconds"] == round(32 + benchmarks.OVERHEAD)
    cpu = benchmarks.estimate("ct2/cpu/large-v3-turbo", 600)  # sequential: asr + diar
    assert cpu["seconds"] == round(200 + 24 + benchmarks.OVERHEAD)
    benchmarks.set_result(k, 2.0, 1.0)
    e = benchmarks.estimate(k, 600)
    assert e["source"] == "measured" and e["seconds"] == round(20 + benchmarks.OVERHEAD)


def test_record_moving_average_and_skips():
    k = "ct2/cuda/large-v3-turbo"
    benchmarks.set_result(k, 4.0, 2.0)
    benchmarks.record({"audio": 600, "asr": 20, "diar": 10}, key=k)  # 2.0 / 1.0 per min
    r = benchmarks.load()[k]
    assert 2.0 < r["asr"] < 4.0 and r["source"] == "jobs" and r["n"] == 2
    before = benchmarks.load()
    benchmarks.record({"audio": 30, "asr": 1, "diar": 1}, key=k)           # too short
    benchmarks.record({"audio": 600, "asr": 1, "diar": 1}, key=k, resumed=True)  # partial timings
    assert benchmarks.load() == before


def test_integrated_graphics_are_flagged_and_not_auto_used():
    from backend import hardware
    from backend.engines import choose

    gpus = hardware.build_gpus([
        {"name": "Intel(R) Arc(TM) Pro Graphics", "vram": 54_760_833_024},   # onboard, shared RAM
        {"name": "NVIDIA RTX 1000 Ada Generation Laptop GPU", "vram": 6_439_305_216},
    ])
    assert [g["integrated"] for g in gpus] == [False, True]  # real card sorted first
    assert hardware.best_gpu({"gpus": gpus})["vendor"] == "NVIDIA"
    for name, onboard in [("Intel(R) Arc(TM) A770 Graphics", False), ("Intel(R) Iris(R) Xe Graphics", True),
                          ("AMD Radeon(TM) 780M", True), ("AMD Radeon RX 7800 XT", False),
                          ("AMD Radeon(TM) Graphics", True), ("Intel(R) Arc(TM) B580 Graphics", False)]:
        assert hardware.is_integrated(name, hardware.vendor_of(name)) is onboard, name
    igpu_only = {"gpus": hardware.build_gpus([{"name": "Intel(R) Iris(R) Xe Graphics", "vram": 8 * hardware.GB}]),
                 "vulkan": True}
    plan = choose(igpu_only, {"engine": "auto"}, cuda=(False, ""), wcpp=(True, ""))
    assert plan["device"] == "cpu" and plan["reason"] == "auto_cpu_igpu"
    forced = choose(igpu_only, {"engine": "whispercpp"}, cuda=(False, ""), wcpp=(True, ""))
    assert forced["engine"] == "whispercpp"  # still possible by hand
    rx = {"gpus": hardware.build_gpus([{"name": "AMD Radeon RX 7600", "vram": 8 * hardware.GB}]), "vulkan": True}
    assert choose(rx, {"engine": "auto"}, cuda=(False, ""), wcpp=(True, ""))["device"] == "vulkan"
