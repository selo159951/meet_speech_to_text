import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import llm  # noqa: E402
from backend.llm import catalog  # noqa: E402

GB = 1024 ** 3
LIST_OUT = ("Available devices:\n"
            "  Vulkan0: Intel(R) Arc(TM) Pro Graphics (51334 MiB, 47828 MiB free)\n"
            "  Vulkan1: NVIDIA RTX 1000 Ada Generation Laptop GPU (5923 MiB, 5155 MiB free)\n")


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MEETTRANSCRIBER_HOME", str(tmp_path))
    monkeypatch.setenv("KATIP_LLM_DIR", str(tmp_path / "llm"))
    monkeypatch.setenv("KATIP_LLAMACPP_DIR", str(tmp_path / "bin"))
    monkeypatch.setattr(llm, "_devices_cache", None)


def hw(*gpus, ram=16):
    return {"gpus": list(gpus), "vulkan": True, "cpu": {"name": "x", "cores": 8},
            "ram": {"total_gb": ram, "total": ram * GB, "available": ram * GB}}


def gpu(name, gb, integrated=False):
    return {"name": name, "vendor": "NVIDIA", "vram": int(gb * GB), "vram_gb": gb, "integrated": integrated}


def fake_model(name, tmp_path):
    m = catalog.get(name)
    d = tmp_path / "llm"
    d.mkdir(exist_ok=True)
    f = d / m["file"]
    with open(f, "wb") as fh:
        fh.truncate(int(m["size_gb"] * GB))  # sparse file
    return f


def test_parse_devices():
    devs = llm.parse_devices(LIST_OUT)
    assert [(d["index"], d["free_mb"]) for d in devs] == [(0, 47828), (1, 5155)]
    assert devs[1]["name"].startswith("NVIDIA RTX 1000")
    assert llm.parse_devices("nothing") == []


def test_choose_device():
    devs = llm.parse_devices(LIST_OUT)
    nv = gpu("NVIDIA RTX 1000 Ada Generation Laptop GPU", 6)
    onboard = gpu("Intel(R) Arc(TM) Pro Graphics", 48, integrated=True)
    assert llm.choose_device(hw(onboard, nv), devs, 3.6) == ("vulkan", 1)
    assert llm.choose_device(hw(onboard, nv), devs, 6.0) == ("vulkan", 1)  # does not fit completely: partial offload
    assert llm.choose_device(hw(onboard, nv), [{**devs[1], "free_mb": 2000}] if len(devs) > 1 else devs, 6.0)[0] == "cpu"  # almost no room
    assert llm.choose_device(hw(onboard), devs, 3.6) == ("cpu", None)
    assert llm.choose_device(hw(), devs, 3.6) == ("cpu", None)
    assert llm.choose_device(hw(nv), [], 3.6) == ("cpu", None)


def test_plan(tmp_path):
    fake_model("gemma-3-4b", tmp_path)
    devs = llm.parse_devices(LIST_OUT)
    nv = gpu("NVIDIA RTX 1000 Ada Generation Laptop GPU", 6)
    p = llm.plan(hw(nv), devs)
    assert p["model"] == "gemma-3-4b" and p["device"] == "vulkan" and p["gpu_index"] == 1
    assert Path(p["path"]).name == "gemma-3-4b-it-Q4_K_M.gguf"
    assert llm.plan(hw(), devs)["device"] == "cpu"


def test_plan_without_model():
    with pytest.raises(llm.LlmError):
        llm.plan(hw(), [])


def test_catalog_recommend_fit():
    big, small = gpu("RTX 4080", 16), gpu("RTX 1000", 6)
    assert catalog.recommend(hw(big)) == catalog.DEFAULT_LARGE
    assert catalog.recommend(hw(small)) == catalog.DEFAULT_SMALL
    assert catalog.recommend(hw(gpu("Radeon Graphics", 24, integrated=True))) == catalog.DEFAULT_SMALL
    assert catalog.recommend(hw()) == catalog.DEFAULT_SMALL
    assert catalog.fit("gemma-3-4b", hw(small)) == "ok"
    assert catalog.fit("gemma-4-e4b", hw(small)) == "tight"
    assert catalog.fit("qwen3.5-9b", hw(small)) == "tight"  # not on the card, but 16 GB RAM: runs on the CPU
    assert catalog.fit("qwen3.5-9b", hw(small, ram=8)) == "no"
    assert catalog.fit("qwen3.5-9b", hw(ram=32)) == "ok"  # CPU: system RAM
    m = catalog.get("qwen3.5-9b")
    assert m["url"] == "https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/main/Qwen3.5-9B-Q4_K_M.gguf"


def test_active(tmp_path):
    h = hw(gpu("RTX 1000", 6))
    assert catalog.active(h) is None
    fake_model("gemma-3-4b", tmp_path)
    assert catalog.active(h) == "gemma-3-4b"  # any downloaded
    fake_model("qwen3.5-4b", tmp_path)
    assert catalog.active(h) == "qwen3.5-4b"  # recommended
    catalog.set_setting("gemma-3-4b")
    assert catalog.active(h) == "gemma-3-4b"  # setting
    catalog.set_setting("qwen3.5-9b")  # not downloaded -> falls back
    assert catalog.active(h) == "qwen3.5-4b"
    assert llm.available() is False  # no binary


def test_extract_json():
    assert llm.extract_json('x {"a": 1} y') == {"a": 1}
    assert llm.extract_json('<think>{"no": 0}\nhmm</think>\n{"a": [1, {"b": 2}]}') == {"a": [1, {"b": 2}]}
    with pytest.raises(llm.LlmError):
        llm.extract_json("no json")
    with pytest.raises(llm.LlmError):
        llm.extract_json("{broken")


def test_build_command():
    p = {"path": "m.gguf", "device": "vulkan", "gpu_index": 1}
    cmd = llm.build_command(p, "p.txt", "s.txt", {"type": "object"}, 512, 0.2, 4096)
    assert cmd[1:5] == ["-m", "m.gguf", "-f", "p.txt"]
    assert cmd[cmd.index("-sysf") + 1] == "s.txt"
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == {"type": "object"}
    assert cmd[cmd.index("-dev") + 1] == "Vulkan1" and cmd[cmd.index("-ngl") + 1] == "999"
    assert cmd[cmd.index("-c") + 1] == "4096" and cmd[cmd.index("-n") + 1] == "512"
    assert "--reasoning-budget" in cmd and "-no-cnv" in cmd
    cpu = llm.build_command({"path": "m", "device": "cpu", "gpu_index": None}, "p", None, None, 10, 0.0, 4096)
    assert cpu[cpu.index("-ngl") + 1] == "0" and cpu[cpu.index("-dev") + 1] == "none"
    assert "-sysf" not in cpu and "--json-schema" not in cpu


def test_ctx():
    assert llm._ctx(100, 2048) == 4096
    assert llm._ctx(5000, 2048) == 7560
    assert llm._ctx(50000, 2048) == 16384
    assert llm.approx_tokens("a" * 300) == 101


class FakeProc:
    def __init__(self, cmd, stdout, stderr, out=b"", err=b"", code=0, hang=False, **kw):
        self.cmd, self.returncode, self.hang, self.killed = cmd, code, hang, False
        stdout.write(out)
        stderr.write(err)

    def wait(self, timeout=None):
        import subprocess

        if self.hang and not self.killed:
            raise subprocess.TimeoutExpired("x", timeout)
        return self.returncode

    def kill(self):
        self.killed = True


@pytest.fixture
def ready(tmp_path, monkeypatch):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / llm.binary_path().name).write_bytes(b"x")
    fake_model("gemma-3-4b", tmp_path)
    monkeypatch.setattr(llm, "plan", lambda hw=None, devs=None: {
        "model": "gemma-3-4b", "path": "m.gguf", "device": "cpu", "gpu_index": None, "ctx": 4096})
    return tmp_path


def run_with(monkeypatch, **kw):
    made = []

    def popen(cmd, stdin=None, stdout=None, stderr=None, **k):
        pr = FakeProc(cmd, stdout, stderr, **kw)
        made.append(pr)
        return pr

    monkeypatch.setattr(llm.subprocess, "Popen", popen)
    return made


def test_generate_schema_and_files(ready, monkeypatch):
    out = '<think>x</think>\n{"summary": "Merhaba şğü"}'.encode("utf-8")
    made = run_with(monkeypatch, out=out)
    r = llm.generate("istek", {"type": "object"}, system="sistem")
    assert r == {"summary": "Merhaba şğü"}
    cmd = made[0].cmd
    assert "--json-schema" in cmd and cmd[cmd.index("-ngl") + 1] == "0"


def test_generate_text(ready, monkeypatch):
    run_with(monkeypatch, out=" <think>a</think>Selam [end of text]".encode())
    assert llm.generate("x") == "Selam"


def test_generate_errors(ready, monkeypatch):
    run_with(monkeypatch, err=b"boom " * 400, code=1)
    with pytest.raises(llm.LlmError) as e:
        llm.generate("x")
    assert "exit 1" in str(e.value) and len(str(e.value)) < 1000
    run_with(monkeypatch, out=b"not json")
    with pytest.raises(llm.LlmError):
        llm.generate("x", {"type": "object"})


def test_generate_cancel_kills(ready, monkeypatch):
    made = run_with(monkeypatch, hang=True)
    ev = threading.Event()
    threading.Timer(0.3, ev.set).start()
    with pytest.raises(llm.Cancelled):
        llm.generate("x", cancel=ev)
    assert made[0].killed


def test_generate_without_binary(tmp_path):
    with pytest.raises(llm.LlmError):
        llm.generate("x")


def test_chat_format_is_written_for_known_models():
    p, s = llm.wrap("qwen3.5-4b", "Soru", "Sistem")
    assert s is None and p.startswith("<|im_start|>system\nSistem<|im_end|>") and p.endswith("<|im_start|>assistant\n")
    p, s = llm.wrap("gemma-3-4b", "Soru", "Sistem")
    assert s is None and p == "<start_of_turn>user\nSistem\n\nSoru<end_of_turn>\n<start_of_turn>model\n"
    assert llm.wrap("gemma-4-e4b", "Soru", "Sistem") == ("Soru", "Sistem")


def test_plan_offloads_part_of_a_big_model():
    nv = gpu("RTX 1000", 6)
    devs = [{"index": 1, "name": "RTX 1000", "total_mb": 6000, "free_mb": 5000}]
    import backend.llm.catalog as cat
    assert llm.choose_device(hw(nv), devs, 7.0) == ("vulkan", 1)
    p = {"path": "m", "device": "vulkan", "gpu_index": 1, "ngl": "auto"}
    cmd = llm.build_command(p, "p", None, None, 10, 0.0, 4096)
    assert cmd[cmd.index("-ngl") + 1] == "auto" and cmd[cmd.index("-dev") + 1] == "Vulkan1"
    p["ngl"] = "999"
    assert llm.build_command(p, "p", None, None, 10, 0.0, 4096)[cmd.index("-ngl") + 1] == "999"


def test_generate_retries_bad_json_and_falls_back_to_cpu(monkeypatch, tmp_path):
    calls = []
    plan = {"model": "qwen3.5-4b", "path": "m.gguf", "device": "vulkan", "gpu_index": 1, "ctx": 4096, "ngl": "auto"}
    monkeypatch.setattr(llm, "plan", lambda *a, **k: dict(plan))
    monkeypatch.setattr(llm, "binary_path", lambda: tmp_path / "llama-completion.exe")
    (tmp_path / "llama-completion.exe").write_bytes(b"")

    def fake(p, prompt, schema, system, max_tokens, temperature, cancel, timeout):
        calls.append((p["device"], round(temperature, 2)))
        if len(calls) == 1:
            return '{"a": 1'  # cut off
        if len(calls) == 2:
            raise llm.LlmError("llama-completion failed (exit 3): vulkan device lost")
        return '{"ok": true}'

    monkeypatch.setattr(llm, "_run_once", fake)
    assert llm.generate("x", schema={"type": "object"}, temperature=0.2) == {"ok": True}
    assert [c[0] for c in calls] == ["vulkan", "vulkan", "cpu"] and calls[1][1] > calls[0][1]


def test_generate_gives_up_after_three_tries(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "plan", lambda *a, **k: {"model": "qwen3.5-4b", "path": "m", "device": "cpu", "gpu_index": None, "ctx": 4096})
    monkeypatch.setattr(llm, "binary_path", lambda: tmp_path / "x.exe")
    (tmp_path / "x.exe").write_bytes(b"")
    n = []
    monkeypatch.setattr(llm, "_run_once", lambda *a, **k: (n.append(1), "nonsense")[1])
    with pytest.raises(llm.LlmError):
        llm.generate("x", schema={"type": "object"})
    assert len(n) == 3
