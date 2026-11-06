"""Everything the window can ask the backend for (window.pywebview.api.<method>).

There is no HTTP server: the page calls these methods directly through pywebview's
JS<->Python bridge, and files are read from disk by path. Every method returns plain
JSON-able data; raising an exception rejects the JS promise with its message.
"""
from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

from . import asr, export, store
from .pipeline import run_job

EXPORT_TYPES = {
    "docx": "Word document (*.docx)",
    "txt": "Text file (*.txt)",
    "md": "Markdown (*.md)",
    "srt": "Subtitles (*.srt)",
    "json": "JSON (*.json)",
}
MEDIA_EXT = "*.mp3;*.wav;*.m4a;*.mp4;*.ogg;*.opus;*.flac;*.aac;*.webm;*.mkv;*.mov;*.wma;*.amr;*.3gp"
MEDIA_TYPES = (f"Audio / video ({MEDIA_EXT})", "All files (*.*)")


def _first(result) -> str | None:
    if not result:
        return None
    return result if isinstance(result, str) else result[0]


def _write(path: Path, data: str | bytes) -> None:
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")


def _job(job_id: str) -> dict:
    try:
        return store.read_transcript(job_id)
    except (FileNotFoundError, ValueError):
        raise ValueError("job not found") from None


class Api:
    """Methods starting with "_" are not exposed to the page."""

    def __init__(self, window_getter=None):
        self._get_window = window_getter

    def _window(self):
        if self._get_window:
            return self._get_window()
        import webview

        return webview.windows[0]

    # ---------------- recordings ----------------
    def list_jobs(self, q: str = "") -> list[dict]:
        return store.list_jobs(q or "")

    def get_job(self, job_id: str) -> dict:
        return _job(job_id)

    def delete_job(self, job_id: str) -> dict:
        _job(job_id)
        store.delete_job(job_id)
        return {"ok": True}

    def rename_job(self, job_id: str, name: str) -> dict:
        _job(job_id)
        return store.rename_job(job_id, name)

    def start_job(self, path: str) -> dict:
        """Start transcribing a file that is on disk (drag & drop or file picker)."""
        src = Path(path)
        if not src.is_file():
            raise ValueError(f"file not found: {path}")
        job_id = store.create_job(src.name)
        threading.Thread(target=run_job, args=(job_id, src), kwargs={"keep_source": True},
                         daemon=True).start()
        return {"id": job_id, "filename": src.name}

    def resume_job(self, job_id: str) -> dict:
        """Continue a job that was interrupted (app closed while it was running)."""
        job = _job(job_id)
        if job["status"] not in ("interrupted", "error"):
            raise ValueError("this recording is not interrupted")
        if not (store.job_path(job_id) / "audio.mp3").exists():
            raise ValueError("the audio of this recording is missing - add the file again")
        store.update_job(job_id, status="queued", stage="queued", error=None)
        threading.Thread(target=run_job, args=(job_id, None), kwargs={"resume": True}, daemon=True).start()
        return {"id": job_id, "filename": job["filename"]}

    def pick_and_start(self) -> dict:
        """Native "Open" dialog, then start the chosen file."""
        import webview

        path = _first(self._window().create_file_dialog(
            webview.FileDialog.OPEN, directory=self._last_dir("open_dir"), file_types=MEDIA_TYPES))
        if not path:
            return {"cancelled": True}
        self._remember_dir("open_dir", str(Path(path).parent))
        return self.start_job(path)

    # ---------------- editing ----------------
    def save_edits(self, job_id: str, texts: dict | None = None, segment_speakers: dict | None = None) -> dict:
        _job(job_id)
        store.save_edits(job_id, {int(k): v for k, v in (texts or {}).items()}, None,
                         {int(k): int(v) for k, v in (segment_speakers or {}).items()})
        return {"ok": True}

    def replace_transcript(self, job_id: str, segments: list, speakers: dict) -> dict:
        _job(job_id)
        return store.replace_transcript(job_id, segments, speakers)

    def split(self, job_id: str, segment_id: int, start: int, end: int, speaker: int) -> dict:
        _job(job_id)
        if not 0 <= int(speaker) < 20:
            raise ValueError("bad speaker")
        return store.split(job_id, int(segment_id), int(start), int(end), int(speaker))

    def detect_names(self, job_id: str) -> dict:
        _job(job_id)
        data, found = store.apply_detected_names(job_id)
        return {"job": data, "found": {str(k): v for k, v in found.items()}}

    # ---------------- settings ----------------
    def get_settings(self) -> dict:
        return asr.status()

    def set_settings(self, values: dict) -> dict:
        if "use_gpu" in values:
            asr.set_use_gpu(bool(values["use_gpu"]))
        if values.get("ui_lang") in ("tr", "en"):
            asr.set_setting("ui_lang", values["ui_lang"])
        return asr.status()

    # ---------------- export & files ----------------
    def _last_dir(self, key: str = "export_dir") -> str:
        d = asr.get_settings().get(key)
        return d if d and os.path.isdir(d) else str(Path.home() / "Documents")

    def _remember_dir(self, key: str, d: str) -> None:
        asr.set_setting(key, d)

    def save_export(self, job_id: str, version: str, fmt: str, lang: str = "en") -> dict:
        """Ask where to save, write the file(s). Returns {"paths": [...]} or {"cancelled": True}."""
        import webview

        if fmt not in EXPORT_TYPES or version not in ("original", "edited", "both"):
            return {"error": "bad format"}
        data = _job(job_id)
        stem = Path(data["filename"]).stem
        win = self._window()
        versions = ["original", "edited"] if version == "both" else [version]
        if len(versions) == 1:
            path = _first(win.create_file_dialog(
                webview.FileDialog.SAVE, directory=self._last_dir(),
                save_filename=f"{stem}.{versions[0]}.{fmt}", file_types=(EXPORT_TYPES[fmt],)))
            if not path:
                return {"cancelled": True}
            target = Path(path)
            if target.suffix.lower() != f".{fmt}":
                target = target.with_name(target.name + f".{fmt}")
            targets = [target]
        else:  # both versions: pick a folder, write two files
            folder = _first(win.create_file_dialog(webview.FileDialog.FOLDER, directory=self._last_dir()))
            if not folder:
                return {"cancelled": True}
            targets = [Path(folder) / f"{stem}.{v}.{fmt}" for v in versions]
        for v, t in zip(versions, targets):
            _write(t, export.render(data, v, fmt, lang))
        self._remember_dir("export_dir", str(targets[0].parent))
        return {"paths": [str(t) for t in targets]}

    def reveal(self, path: str) -> None:
        """Open Explorer with the file selected."""
        p = Path(path)
        if not p.exists():
            return
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p.parent)])

    def open_url(self, url: str) -> None:
        """Open a web link in the user's normal browser (never inside the app window)."""
        import webbrowser

        if isinstance(url, str) and url.startswith(("https://", "http://")):
            webbrowser.open(url)
