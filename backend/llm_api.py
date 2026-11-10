"""Bridge methods for the local LLM (model choice, download). `Api` inherits from LlmApi."""
from __future__ import annotations

from . import hardware, llm
from .llm import catalog


class LlmApi:
    def get_llm_info(self) -> dict:
        hw = hardware.info()
        rec = catalog.recommend(hw)
        exe = llm.binary_path().is_file()
        active = catalog.active(hw)
        device, gpu = "cpu", None
        if exe and active:
            device = llm.plan(hw)["device"]
            if device == "vulkan":
                gpu = catalog.discrete_gpu(hw)["name"]
        return {
            "binary": exe, "device": device, "gpu": gpu, "model": catalog.get_setting(), "active": active,
            "models": [{"name": m["name"], "label": m["label"], "size_gb": m["size_gb"],
                        "need_gb": m["need_gb"], "downloaded": catalog.is_downloaded(m["name"]),
                        "fit": catalog.fit(m["name"], hw), "recommended": m["name"] == rec}
                       for m in catalog.CATALOG],
            "download": catalog.download_status(),
        }

    def set_llm_model(self, name: str) -> dict:
        if name != "auto" and not catalog.get(name):
            raise ValueError("unknown model")
        catalog.set_setting(name)
        return self.get_llm_info()

    def download_llm(self, name: str | None = None) -> dict:
        if not name or name == "auto":
            s = catalog.get_setting()
            name = s if s != "auto" else catalog.recommend(hardware.info())
        return catalog.start_download(name)
