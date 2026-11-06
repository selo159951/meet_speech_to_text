# Builds the official ggml-org/whisper.cpp with the Vulkan backend and copies the
# runtime files into <repo>/vendor/whispercpp (gitignored).
#
# Prerequisites (installed with winget if missing):
#   Kitware.CMake, Microsoft.VisualStudio.2022.BuildTools (C++ workload), KhronosGroup.VulkanSDK
# vulkan-1.dll is NOT bundled: it ships with the GPU driver.
param(
    [string]$Tag = "v1.9.5",
    [string]$Src = "$env:USERPROFILE\dev\whisper.cpp"
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $repo "vendor\whispercpp"

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
function Ensure-Winget($cmd, $id, $extra = "") {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Host "Installing $id ..."
        winget install -e --id $id --silent --accept-package-agreements --accept-source-agreements @($extra | ? { $_ })
        Refresh-Path
    }
}
Refresh-Path
Ensure-Winget "cmake" "Kitware.CMake"
if (-not $env:VULKAN_SDK -and -not (Test-Path "C:\VulkanSDK")) {
    winget install -e --id KhronosGroup.VulkanSDK --silent --accept-package-agreements --accept-source-agreements
    Refresh-Path
}
if (-not $env:VULKAN_SDK) {
    $sdk = Get-ChildItem C:\VulkanSDK -Directory | Sort-Object Name -Descending | Select-Object -First 1
    $env:VULKAN_SDK = $sdk.FullName
}
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere) -or -not (& $vswhere -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath)) {
    winget install -e --id Microsoft.VisualStudio.2022.BuildTools --silent --accept-package-agreements --accept-source-agreements `
        --override "--quiet --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
}

if (-not (Test-Path (Join-Path $Src "CMakeLists.txt"))) {
    git clone --depth 1 --branch $Tag https://github.com/ggml-org/whisper.cpp.git $Src
}

Push-Location $Src
try {
    cmake -B build -DGGML_VULKAN=1 -DCMAKE_BUILD_TYPE=Release -DWHISPER_BUILD_TESTS=OFF
    cmake --build build --config Release -j
} finally { Pop-Location }

$bin = Join-Path $Src "build\bin\Release"
if (-not (Test-Path (Join-Path $bin "whisper-cli.exe"))) { $bin = Join-Path $Src "build\bin" }
New-Item -ItemType Directory -Force $dest | Out-Null
Remove-Item "$dest\*" -Force -ErrorAction SilentlyContinue
Copy-Item (Join-Path $bin "whisper-cli.exe") $dest
Get-ChildItem $bin -Filter *.dll | Where-Object { $_.Name -ne "vulkan-1.dll" } | Copy-Item -Destination $dest
Write-Host "Copied to $dest :"
Get-ChildItem $dest | Select-Object Name, Length
