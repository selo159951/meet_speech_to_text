# -*- mode: python -*-
# Build: .\build_windows.ps1   (CPU build; add -Gpu for the NVIDIA variant)
from PyInstaller.utils.hooks import collect_all

datas = [("frontend", "frontend"), ("models", "models")]
binaries = []
hiddenimports = [
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on",
    "backend.main", "backend.desktop", "backend.names",
]
# packages with native DLLs or data files (VAD model, docx template, WebView2 bridge …)
for pkg in ("faster_whisper", "ctranslate2", "sherpa_onnx", "onnxruntime", "av", "webview",
            "clr_loader", "pythonnet", "tokenizers", "docx"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

a = Analysis(
    ["app.py"], datas=datas, binaries=binaries, hiddenimports=hiddenimports,
    excludes=["nvidia", "tkinter", "matplotlib", "pytest", "IPython"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MeetTranscriber",
          console=False, icon=None)
coll = COLLECT(exe, a.binaries, a.datas, name="MeetTranscriber")
