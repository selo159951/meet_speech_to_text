# -*- mode: python -*-
# Build: .\build_windows.ps1   (CPU build; add -Gpu for the NVIDIA variant)
from PyInstaller.utils.hooks import collect_all

import os
datas = [("frontend", "frontend"), ("assets", "assets")]
# speaker models only: models/llm holds multi-GB language models that are downloaded by the app, never bundled
for n in os.listdir("models"):
    if n != "llm":
        src = os.path.join("models", n)
        datas.append((src, src if os.path.isdir(src) else "models"))
binaries = []
hiddenimports = ["backend.bridge", "backend.window", "backend.names", "backend.people",
                 "backend.system_api", "backend.engines.ct2", "backend.engines.whispercpp",
                 "backend.analysis", "backend.names_llm", "backend.llm", "backend.llm.catalog", "backend.llm_api"]
# packages with native DLLs or data files (VAD model, docx template, WebView2 bridge …)
for pkg in ("faster_whisper", "ctranslate2", "sherpa_onnx", "onnxruntime", "av", "webview",
            "clr_loader", "pythonnet", "tokenizers", "docx", "sounddevice", "_sounddevice_data"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# whisper.cpp Vulkan runtime (AMD / Intel GPUs), built by tools/build_whispercpp.ps1
import os
if os.path.isdir("vendor/whispercpp"):
    for f in os.listdir("vendor/whispercpp"):
        binaries.append((os.path.join("vendor/whispercpp", f), "whispercpp"))

# llama.cpp runtime for the local LLM, built by tools/build_llamacpp.ps1
if os.path.isdir("vendor/llamacpp"):
    for f in os.listdir("vendor/llamacpp"):
        binaries.append((os.path.join("vendor/llamacpp", f), "llamacpp"))

a = Analysis(
    ["app.py"], datas=datas, binaries=binaries, hiddenimports=hiddenimports,
    excludes=["nvidia", "tkinter", "matplotlib", "pytest", "IPython"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Katip",
          console=False, icon=None)
coll = COLLECT(exe, a.binaries, a.datas, name="Katip")
