@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Meeting Transcriber

if exist ".venv\Scripts\pythonw.exe" goto run

echo ================================================
echo  Meeting Transcriber - ilk kurulum (bir kez)
echo ================================================
where py >nul 2>&1 || (
  echo Python bulunamadi. Lutfen https://www.python.org/downloads/ adresinden
  echo Python 3.12 kurun ^("Add to PATH" secili olsun^) ve tekrar calistirin.
  pause & exit /b 1
)
py -3.12 -m venv .venv 2>nul || py -3 -m venv .venv || (echo Sanal ortam olusturulamadi. & pause & exit /b 1)
echo Gerekli paketler indiriliyor...
".venv\Scripts\python" -m pip install -q --upgrade pip
".venv\Scripts\pip" install -q -r requirements.txt || (echo Paket kurulumu basarisiz. & pause & exit /b 1)
where nvidia-smi >nul 2>&1 && (
  echo NVIDIA ekran karti bulundu, GPU destegi kuruluyor...
  ".venv\Scripts\pip" install -q -r requirements-gpu.txt
)
echo Konusmaci modelleri indiriliyor...
".venv\Scripts\python" fetch_models.py || (echo Model indirilemedi. & pause & exit /b 1)
echo Kurulum tamam.

:run
start "" ".venv\Scripts\pythonw.exe" app.py
exit /b 0
