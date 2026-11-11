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
from .llm_api import LlmApi
from .system_api import SystemApi

EXPORT_TYPES = {
    "docx": "Word document (*.docx)",
    "txt": "Text file (*.txt)",
    "md": "Markdown (*.md)",
    "srt": "Subtitles (*.srt)",
    "json": "JSON (*.json)",
}
MEDIA_EXT = "*.mp3;*.wav;*.m4a;*.mp4;*.ogg;*.opus;*.flac;*.aac;*.webm;*.mkv;*.mov;*.wma;*.amr;*.3gp"
MEDIA_TYPES = (f"Audio and video ({MEDIA_EXT})", "All files (*.*)")


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


class Api(SystemApi, LlmApi):
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
        return {**asr.status(), "meeting_mode": bool(asr.get_settings().get("meeting_mode", False))}

    def set_settings(self, values: dict) -> dict:
        if "use_gpu" in values:
            asr.set_use_gpu(bool(values["use_gpu"]))
        if values.get("ui_lang") in ("tr", "en"):
            asr.set_setting("ui_lang", values["ui_lang"])
        if "meeting_mode" in values:
            asr.set_setting("meeting_mode", bool(values["meeting_mode"]))
        return self.get_settings()

    # ---------------- meeting analysis ----------------
    def analyze_job(self, job_id: str) -> dict:
        from . import analysis

        _job(job_id)
        return analysis.start(job_id)

    def cancel_analysis(self, job_id: str) -> dict:
        from . import analysis

        _job(job_id)
        return analysis.cancel(job_id)

    def get_analysis(self, job_id: str) -> dict:
        from . import analysis

        _job(job_id)
        return analysis.status(job_id)

    # ---------------- export & files ----------------
    def _last_dir(self, key: str = "export_dir") -> str:
        d = asr.get_settings().get(key)
        return d if d and os.path.isdir(d) else str(Path.home() / "Documents")

    def _remember_dir(self, key: str, d: str) -> None:
        asr.set_setting(key, d)

    def save_export(self, job_id: str, version: str, fmt: str, lang: str = "en") -> dict:
        """Ask where to save, write the file(s). Returns {"paths": [...]} or {"cancelled": True}."""
        import json

        import webview

        if fmt not in EXPORT_TYPES or version not in ("original", "edited", "both", "analysis"):
            return {"error": "bad format"}
        data = _job(job_id)
        stem = Path(data["filename"]).stem
        win = self._window()

        if version == "analysis":  # a meeting analysis has no subtitles
            if fmt not in ("md", "txt", "docx", "json"):
                return {"error": "bad format"}
            path = store.job_path(job_id) / "analysis.json"
            if not path.exists():
                raise ValueError("this recording has no finished analysis yet")
            try:
                analysis = json.loads(path.read_text("utf-8"))
            except (OSError, ValueError):
                raise ValueError("the analysis file could not be read") from None
            suffix = "analiz" if lang == "tr" else "analysis"
            chosen = _first(win.create_file_dialog(
                webview.FileDialog.SAVE, directory=self._last_dir(),
                save_filename=f"{stem} - {suffix}.{fmt}", file_types=(EXPORT_TYPES[fmt],)))
            if not chosen:
                return {"cancelled": True}
            target = Path(chosen)
            if target.suffix.lower() != f".{fmt}":
                target = target.with_name(target.name + f".{fmt}")
            _write(target, export.render_analysis(data, analysis, fmt, lang))
            self._remember_dir("export_dir", str(target.parent))
            return {"paths": [str(target)]}

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

    # ---- people ----
    def list_people(self) -> list[dict]:
        from . import people

        return people.list_people()

    def create_person(self, name: str) -> dict:
        from . import people

        return people.create_person(name)

    def rename_person(self, person_id: str, name: str) -> dict:
        from . import people

        return people.rename_person(person_id, name)

    def delete_person(self, person_id: str) -> dict:
        from . import people

        people.delete_person(person_id)
        return {"ok": True}

    def add_person_sample_file(self, person_id: str | None = None, name: str | None = None) -> dict:
        """Native "Open" dialog, then add the chosen recording as a voice sample.
        person_id None + name: a new person is created once the sample is good enough."""
        import webview

        path = _first(self._window().create_file_dialog(
            webview.FileDialog.OPEN, directory=self._last_dir("open_dir"), file_types=MEDIA_TYPES))
        if not path:
            return {"cancelled": True}
        self._remember_dir("open_dir", str(Path(path).parent))
        return self._sample_from_path(path, person_id, name)

    def _sample_from_path(self, path: str, person_id: str | None, name: str | None) -> dict:
        from . import audio, people

        if person_id:
            return people.add_sample_from_file(person_id, path)
        if not (name or "").strip():
            raise ValueError("name required")
        speech = people.speech_only(audio.decode(Path(path))[0])
        if len(speech) / people.SR < people.MIN_SPEECH:  # nothing is created for a too short sample
            people.too_short(speech)
        pid = people.create_person(name)["id"]
        return people._enroll(pid, speech, "file:" + Path(path).name, people.MIN_SPEECH)

    def start_recording(self) -> dict:
        from . import people

        return people.start_recording()

    def recording_status(self) -> dict:
        from . import people

        return people.recording_status()

    def stop_recording(self, person_id: str | None = None, name: str | None = None) -> dict:
        from . import people

        return people.stop_recording(person_id, name)

    def cancel_recording(self) -> dict:
        from . import people

        return people.cancel_recording()

    def save_speaker_as_person(self, job_id: str, speaker: int, person_id: str | None = None,
                               name: str | None = None) -> dict:
        from . import people

        _job(job_id)
        return people.add_sample_from_job(job_id, int(speaker), person_id or None, name)

    def rematch_job(self, job_id: str) -> dict:
        from . import people

        _job(job_id)
        return people.rematch_job(job_id)

    def accept_suggestion(self, job_id: str, speaker: int, person_id: str) -> dict:
        from . import people

        _job(job_id)
        return people.accept_suggestion(job_id, int(speaker), person_id)

    def accept_name_suggestion(self, job_id: str, speaker: int, name: str) -> dict:
        import json

        _job(job_id)
        name = name.strip()
        if not name:
            raise ValueError("empty name")
        job = store.save_edits(job_id, None, {int(speaker): name[:80]})
        path = store.job_path(job_id) / "analysis.json"
        try:
            data = json.loads(path.read_text("utf-8"))
            data["name_suggestions"] = [x for x in data.get("name_suggestions", []) if x.get("speaker") != int(speaker)]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
        except (OSError, ValueError):
            pass
        return job
