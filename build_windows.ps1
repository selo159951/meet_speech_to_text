# Build MeetTranscriber.exe (run on Windows). Output: dist\MeetTranscriber\MeetTranscriber.exe
$ErrorActionPreference = "Stop"
if (-not (Test-Path .venv)) { py -3.12 -m venv .venv }
.\.venv\Scripts\pip install -r requirements.txt pyinstaller
.\.venv\Scripts\python fetch_models.py
.\.venv\Scripts\pyinstaller --noconfirm --clean MeetTranscriber.spec
Write-Host "Done: dist\MeetTranscriber\MeetTranscriber.exe  (zip the folder and send it)"
