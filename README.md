# Kâtip · Meeting scribe

Turns meeting recordings (40–80 min and longer) into an editable transcript with time ranges and speaker names. It is a **desktop app**: everything runs offline on the PC, no audio leaves the computer, and no network port is opened. The interface is in Turkish and English.

> **TR:** Toplantı kayıtlarını konuşmacılarıyla birlikte düzenlenebilir metne dönüştüren masaüstü uygulaması. Tamamen çevrimdışı çalışır. `Katip.zip`'i açıp `Katip.exe`'ye çift tıklayın.
>
> **Toplantı modu:** Metinden özet, konular, kararlar, görevler ve açık sorular çıkarılır; konuşmacı başına katkı ve toplantı puanı gösterilir. Tamamen çevrimdışı çalışır (llama.cpp; Vulkan destekli ekran kartı veya CPU), model Sistem sayfasından bir kez indirilir.

## Features
- Drag & drop any audio/video file (mp3, wav, m4a, mp4, ogg…); progress with remaining-time estimate
- Audio **or video** files (only the audio track is read); recording language: automatic, **mixed** (Turkish + English in one meeting) or fixed
- Language auto-detected (Whisper `large-v3-turbo`; medium/small for slower PCs)
- Long recordings are processed in ~5 min parts cut only at pauses (never inside a word); an interrupted job can be **resumed**
- Speakers separated automatically; **People page**: save a person's voice (file, microphone reading, or from a recording) and they are named automatically in later recordings
- Speaker names also guessed from "ben Selim", "benim adım…", "my name is…", "Umut sen…"
- Click a time range to replay it, fix text in place (autosaved), select part of a line → "Who said this?"
- Add / remove / rename / merge speakers and lines, Undo (Ctrl+Z), search, replace, filters
- **System page**: graphics card, video memory, CPU, RAM, whether the PC is suitable, speed test ("1 min of audio ≈ X s"), engine and model choice
- Export **Original**, **Edited** or **Both** as Word / TXT / Markdown / SRT / JSON
- Export the **Analysis** as Word / TXT / Markdown / JSON

## Meeting mode (local AI analysis)
After the transcript is ready (or on demand from the **Analysis** tab), the app reads the meeting on the PC and produces:
- a short **summary** and the **topics** discussed, with their time ranges
- **decisions**, **tasks** (with owner and due date where the meeting says so) and **open questions**
- **per-person contribution**: talk time, turns, words and questions, what each person contributed and what they took away
- a **meeting score** (overall plus decisions, focus, repetition and balance) with short tips

Everything runs fully offline through **llama.cpp**: it uses the graphics card over Vulkan when there is one and the CPU otherwise. There is no Ollama and no local server. The model is downloaded once from the **System** page; after that no network connection is needed.

Names are assigned in this order: a saved voice match from the People page wins; otherwise a name is applied automatically when the rule-based "ben Selim / my name is…" detection and the model agree; a name found by only one of them is shown as a suggestion instead.

Small models make mistakes: the summary and every listed item are a best guess, but each one links to the transcript line it came from in the app, so it can be checked against the recording.

## Graphics cards
| Card | Engine | Notes |
|---|---|---|
| NVIDIA | CUDA (faster-whisper) in `Katip-NVIDIA.zip`, Vulkan in `Katip.zip` | tested |
| AMD Radeon RX, Intel Arc A/B | Vulkan (whisper.cpp) | built for it; **not tested on a real AMD/Intel card yet** |
| Onboard graphics (Intel Iris/UHD, AMD Radeon Graphics) | CPU by default | usually slower than the CPU; Vulkan can be chosen by hand |
| none | CPU | works everywhere, slower |

Measured on a laptop with an RTX 1000 Ada (6 GB) and a 22-core Core Ultra 7, `large-v3-turbo`:
- CUDA: ~3.4 s per audio minute for transcription, ~2.3 GB video memory (does not grow with recording length)
- Vulkan on the same NVIDIA card: ~1.5 s per audio minute, ~0.9 GB (q5_0 model); on the Intel Arc onboard GPU ~6.3 s/min
- 12 min recording end to end on GPU: 53 s (transcription and speaker separation run in parallel)
- CPU only: ~20–35 s per audio minute

## How speakers are separated
1. **Segmentation** (pyannote-segmentation-3.0): finds where speech starts, stops or changes voice.
2. **Voice prints** (3D-Speaker ERes2Net): each speech region becomes a vector describing the voice.
3. **Clustering**: similar voice prints form one speaker.
4. **Sentence check**: each sentence gets its own voice print and moves to another speaker if it clearly sounds like them (catches changes without a pause).
5. **People**: each speaker's voice is compared with the saved people; a clear match gets the name, a close one is offered as "Selim olabilir?".

## Windows .exe (no Python needed)
```powershell
.\tools\build_whispercpp.ps1   # once: builds whisper.cpp with Vulkan into vendor\whispercpp
.\tools\build_llamacpp.ps1     # once: builds llama.cpp with Vulkan into vendor\llamacpp (meeting mode)
.\build_windows.ps1            # dist\Katip.zip         (CPU + Vulkan: any PC)
.\build_windows.ps1 -Gpu       # also dist\Katip-NVIDIA.zip (adds CUDA, fastest on NVIDIA)
```
Unzip and double-click `Katip.exe` (needs Microsoft Edge WebView2, built into Windows 10/11). The System page downloads the Whisper model on first start; after that everything works offline.

## Run (development)
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt     # + requirements-gpu.txt for NVIDIA CUDA
.\.venv\Scripts\python fetch_models.py               # speaker models, ~45 MB, once
.\.venv\Scripts\python app.py
```
Or double-click `Baslat.bat`, which does all of this on the first run.
Tests: `.\.venv\Scripts\python -m pytest tests`. Data lives in `%APPDATA%\Katip` (override with `KATIP_HOME`; `MEETTRANSCRIBER_HOME` is still honoured). An existing `%APPDATA%\MeetTranscriber` folder is copied over once at first start.

## Credits
- **Fikir Babası / Idea:** Umut Akbaş
- **Geliştirici / Developed by:** [Selim Oğuz](https://selimoguz.com.tr) & Claude

## License
GPL-3.0, see [LICENSE](LICENSE).
