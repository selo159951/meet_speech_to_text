# Build the Windows app.
#   .\build_windows.ps1        -> dist\MeetTranscriber            (works everywhere, CPU)
#   .\build_windows.ps1 -Gpu   -> also dist\MeetTranscriber-GPU   (adds NVIDIA CUDA libraries, ~2 GB)
# Each folder is also zipped next to it, ready to share.
param([switch]$Gpu)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) { py -3.12 -m venv .venv }
.\.venv\Scripts\pip install -q -r requirements.txt pyinstaller
.\.venv\Scripts\python fetch_models.py
.\.venv\Scripts\pyinstaller --noconfirm --clean MeetTranscriber.spec
Push-Location dist; tar.exe -a -c -f MeetTranscriber-CPU.zip MeetTranscriber; Pop-Location

if ($Gpu) {
    .\.venv\Scripts\pip install -q -r requirements-gpu.txt
    $dst = "dist\MeetTranscriber-GPU"
    if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
    Copy-Item -Recurse dist\MeetTranscriber $dst
    # the app looks for <app>\_internal\nvidia\*\bin\*.dll at start-up
    foreach ($pkg in "cublas", "cudnn", "cuda_nvrtc") {
        $src = ".venv\Lib\site-packages\nvidia\$pkg\bin"
        if (Test-Path $src) {
            $to = "$dst\_internal\nvidia\$pkg\bin"
            New-Item -ItemType Directory -Force $to | Out-Null
            Copy-Item "$src\*.dll" $to
        }
    }
    Push-Location dist; tar.exe -a -c -f MeetTranscriber-GPU.zip MeetTranscriber-GPU; Pop-Location  # >2 GB: tar, not Compress-Archive
}
Write-Host "Done. Run dist\MeetTranscriber\MeetTranscriber.exe (share the .zip files in dist\)"
