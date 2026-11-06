"""Download the diarization models into ./models (run once before dev/build)."""
import tarfile
import urllib.request
from pathlib import Path

BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
FILES = [
    (BASE + "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2", True),
    (BASE + "speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx", False),
]
dest = Path(__file__).parent / "models"
dest.mkdir(exist_ok=True)
for url, archive in FILES:
    name = url.rsplit("/", 1)[1]
    target = dest / name
    if archive and (dest / name.replace(".tar.bz2", "")).exists() or (not archive and target.exists()):
        continue
    print("Downloading", name)
    urllib.request.urlretrieve(url, target)
    if archive:
        with tarfile.open(target) as t:
            t.extractall(dest)
        target.unlink()
print("Models ready in", dest)
