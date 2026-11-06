from __future__ import annotations

import sys
import threading
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import export, store
from .pipeline import run_job

app = FastAPI()


@app.middleware("http")
async def no_cache_ui(request, call_next):
    """UI files must never be served stale after an app update."""
    resp = await call_next(request)
    if not request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


def _job(job_id: str) -> dict:
    try:
        return store.read_transcript(job_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "job not found")


@app.post("/api/jobs")
async def create_job(file: UploadFile):
    name = Path(file.filename or "audio").name
    job_id = store.create_job(name)
    src = store.job_path(job_id) / ("upload" + Path(name).suffix)
    with open(src, "wb") as f:
        while chunk := await file.read(1 << 20):
            f.write(chunk)
    threading.Thread(target=run_job, args=(job_id, src), daemon=True).start()
    return {"id": job_id}


@app.get("/api/jobs")
def list_jobs(q: str = ""):
    return store.list_jobs(q)


class RenameIn(BaseModel):
    name: str


@app.post("/api/jobs/{job_id}/rename")
def rename(job_id: str, r: RenameIn):
    _job(job_id)
    try:
        return store.rename_job(job_id, r.name)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    return _job(job_id)


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    _job(job_id)
    store.delete_job(job_id)
    return {"ok": True}


@app.get("/api/settings")
def get_settings():
    from . import asr

    return asr.status()


class SettingsIn(BaseModel):
    use_gpu: bool | None = None
    ui_lang: str | None = None


@app.put("/api/settings")
def put_settings(s: SettingsIn):
    from . import asr

    if s.use_gpu is not None:
        asr.set_use_gpu(s.use_gpu)  # model is reloaded on the right device at the next job
    if s.ui_lang in ("tr", "en"):
        asr.set_setting("ui_lang", s.ui_lang)
    return asr.status()


class Edits(BaseModel):
    texts: dict[int, str] = {}
    speakers: dict[int, str] = {}  # speaker index -> display name
    segment_speakers: dict[int, int] = {}  # segment id -> speaker index


@app.patch("/api/jobs/{job_id}")
def save(job_id: str, e: Edits):
    _job(job_id)
    store.save_edits(job_id, e.texts, e.speakers, e.segment_speakers)
    return {"ok": True}


class SplitIn(BaseModel):
    segment_id: int
    start: int  # char offsets in text_edited
    end: int
    speaker: int


@app.post("/api/jobs/{job_id}/split")
def split(job_id: str, s: SplitIn):
    _job(job_id)
    if not 0 <= s.speaker < 20:
        raise HTTPException(400, "bad speaker")
    try:
        return store.split(job_id, s.segment_id, s.start, s.end, s.speaker)
    except KeyError:
        raise HTTPException(404, "segment not found")


class TranscriptIn(BaseModel):
    segments: list[dict]
    speakers: dict[str, str]


@app.put("/api/jobs/{job_id}/transcript")
def put_transcript(job_id: str, t: TranscriptIn):
    _job(job_id)
    try:
        return store.replace_transcript(job_id, t.segments, t.speakers)
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(400, f"bad transcript: {e}")


@app.post("/api/jobs/{job_id}/detect-names")
def detect_names(job_id: str):
    _job(job_id)
    data, found = store.apply_detected_names(job_id)
    return {"job": data, "found": {str(k): v for k, v in found.items()}}


@app.get("/api/jobs/{job_id}/audio")
def audio(job_id: str):
    p = store.job_path(job_id) / "audio.mp3"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="audio/mpeg")  # Starlette handles Range requests


@app.get("/api/jobs/{job_id}/export")
def do_export(job_id: str, version: str = "edited", fmt: str = "txt", lang: str = "en"):
    data = _job(job_id)
    if version not in ("original", "edited") or fmt not in ("txt", "md", "srt", "json", "docx"):
        raise HTTPException(400, "bad version/format")
    stem = Path(data["filename"]).stem
    fname = f"{stem}.{version}.{fmt}"
    media = ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"
             if fmt == "docx" else "text/plain; charset=utf-8")
    return Response(
        export.render(data, version, fmt, lang),
        media_type=media,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}"},
    )


_base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
app.mount("/", StaticFiles(directory=_base / "frontend", html=True), name="ui")
