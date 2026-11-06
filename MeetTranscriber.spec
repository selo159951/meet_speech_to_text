# -*- mode: python -*-
from PyInstaller.utils.hooks import collect_all

datas = [("frontend", "frontend"), ("models", "models")]
binaries, hiddenimports = [], ["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
                               "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on"]
for pkg in ("faster_whisper", "ctranslate2", "sherpa_onnx", "av", "webview", "tokenizers"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

a = Analysis(["app.py"], datas=datas, binaries=binaries, hiddenimports=hiddenimports)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MeetTranscriber", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="MeetTranscriber")
