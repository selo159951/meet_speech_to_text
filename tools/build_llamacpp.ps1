# Downloads the official llama.cpp Windows Vulkan release and keeps only what the app needs
# (llama-completion.exe + its DLLs) in <repo>/vendor/llamacpp (gitignored).
# vulkan-1.dll is NOT bundled: it ships with the GPU driver.
param(
    [string]$Tag = "b12255"
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $repo "vendor\llamacpp"
$tmp = Join-Path $env:TEMP "llamacpp_$Tag"
$zip = Join-Path $tmp "llama.zip"
$url = "https://github.com/ggml-org/llama.cpp/releases/download/$Tag/llama-$Tag-bin-win-vulkan-x64.zip"

if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
New-Item -ItemType Directory -Force $tmp | Out-Null
Write-Host "Downloading $url ..."
Invoke-WebRequest -Uri $url -OutFile $zip
$raw = Join-Path $tmp "raw"
Expand-Archive -Path $zip -DestinationPath $raw

if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
New-Item -ItemType Directory -Force $dest | Out-Null
$keep = @("llama-completion.exe", "llama-completion-impl.dll", "llama.dll", "llama-common.dll",
          "libomp.dll", "mtmd.dll", "ggml*.dll", "LICENSE*")
foreach ($pat in $keep) {
    Get-ChildItem -Path $raw -Recurse -File -Filter $pat | ForEach-Object { Copy-Item $_.FullName $dest }
}
Remove-Item -Recurse -Force $tmp

& (Join-Path $dest "llama-completion.exe") --version
if ($LASTEXITCODE -ne 0) { throw "llama-completion.exe does not start after pruning" }
Write-Host "Done: $dest"
