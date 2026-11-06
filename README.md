# Meeting Transcriber · Toplantı Yazıya Dökücü

Turns meeting recordings (40–80 min) into an editable transcript with time ranges and speaker labels. Everything runs **offline**: no audio leaves the computer. The interface is available in Turkish and English.

> **TR:** Toplantı kayıtlarını konuşmacılarıyla birlikte düzenlenebilir metne dönüştürür. Tamamen çevrimdışı çalışır. Kurulum için Windows'ta `Baslat.bat` dosyasına çift tıklayın.

## Features
- Drag & drop any audio/video file (mp3, wav, m4a, mp4, ogg…) with a progress bar
- Language auto-detected (Whisper `large-v3-turbo`)
- Speaker detection (max 3) with sherpa-onnx, no account or token needed
- Click a time range to replay exactly that part, then fix the text in place (autosaved)
- Speaker names filled in automatically from "ben Selim", "benim adım…", "my name is…", and from being addressed ("Umut sen…")
- Select part of a line → "Who said this?" → it becomes its own line for that speaker
- Add / remove / rename speakers, move all lines of a wrongly split speaker at once, talk-time stats per speaker
- Add, delete and merge lines; Undo (Ctrl+Z) for every structural change
- Search with highlighting, replace all, filter by speaker / edited lines / matches, follow playback
- Every edited line is marked and can be reverted to the model's output
- Export **Original** (model output), **Edited**, or **Both**, as Word / TXT / Markdown / SRT / JSON

## How speakers are separated
1. **Segmentation** (pyannote-segmentation-3.0): scans the audio in short windows and marks where speech starts, stops or changes voice.
2. **Voice prints** (3D-Speaker ERes2Net): each speech region becomes a vector of numbers describing the voice (pitch, timbre…), independent of the words.
3. **Clustering**: similar voice prints are grouped; each group is one speaker (max 3).
4. **Sentence check**: every sentence from Whisper gets its own voice print and moves to another speaker if it clearly sounds like them. This catches changes without a pause between speakers.
5. Whisper's word timestamps are matched to those speakers.
- Previous recordings stay in the list (stored in `%APPDATA%\MeetTranscriber`)

## Kullanım / How to use
Double-click **`Baslat.bat`**. The first run installs everything (needs Python 3.12 and internet, ~5–10 min; GPU libraries are added automatically if an NVIDIA card exists). After that it opens the app directly.

**GPU switch** (top right): on by default when a working NVIDIA GPU is found; greyed out ("GPU unavailable") otherwise. It applies to the next file.
Measured with `large-v3-turbo` on an RTX 1000 Ada laptop GPU: an 80 min meeting takes **~2.5 min on GPU** vs **~27 min on CPU**.

## Run (development)
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python fetch_models.py      # diarization models, ~30 MB, once
.\.venv\Scripts\python app.py               # native window; add --browser to use the browser
```
On the first transcription, the Whisper model (~1.6 GB) is downloaded once.
For a quicker test on slow PCs, set `MEETTRANSCRIBER_MODEL=small`.

Tests: `.\.venv\Scripts\python -m pytest tests`

## GPU
GPU support needs the CUDA 12 libraries: `pip install -r requirements-gpu.txt` (`Baslat.bat` does this automatically). The app finds them on its own. If the GPU fails mid-load it falls back to CPU.

## Windows .exe (no Python needed)
```powershell
.\build_windows.ps1        # dist\MeetTranscriber-CPU.zip  (~160 MB, any PC)
.\build_windows.ps1 -Gpu   # also dist\MeetTranscriber-GPU.zip (~1.4 GB, adds NVIDIA CUDA libraries)
```
Unzip, double-click `MeetTranscriber.exe`. The first transcription downloads the Whisper model (~1.6 GB) once, after that everything works offline.
The GPU version also runs on PCs without an NVIDIA card (it falls back to CPU), it is just bigger.

Measured on a 22-core laptop with an RTX 1000 Ada, for 5 min of audio: GPU version 50 s, CPU version ≈ 2.5 min.
So an 80 min meeting takes roughly 13 min (GPU) or 40 min (CPU); speaker separation always runs on the CPU.

## Credits
- **Fikir Babası / Idea:** Umut Akbaş
- **Geliştirici / Developed by:** [Selim Oğuz](https://selimoguz.com.tr) & Claude

## License
GPL-3.0, see [LICENSE](LICENSE).
