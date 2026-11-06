"""Functions the page can call inside the desktop window (window.pywebview.api.*).

Only used by the native app; in a normal browser the page falls back to downloads.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import asr, export, store

FILE_TYPES = {
    "docx": "Word document (*.docx)",
    "txt": "Text file (*.txt)",
    "md": "Markdown (*.md)",
    "srt": "Subtitles (*.srt)",
    "json": "JSON (*.json)",
}


def _first(result) -> str | None:
    if not result:
        return None
    return result if isinstance(result, str) else result[0]


def _write(path: Path, data: str | bytes) -> None:
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")


class Api:
    def _window(self):
        import webview

        return webview.windows[0]

    def _last_dir(self) -> str:
        d = asr.get_settings().get("export_dir")
        return d if d and os.path.isdir(d) else str(Path.home() / "Documents")

    def _remember_dir(self, d: str) -> None:
        s = asr.get_settings()
        s["export_dir"] = d
        asr._settings_file().write_text(__import__("json").dumps(s), "utf-8")

    def open_url(self, url: str) -> None:
        """Open a web link in the user's normal browser (not inside the app window)."""
        import webbrowser

        if url.startswith(("https://", "http://")):
            webbrowser.open(url)

    def save_export(self, job_id: str, version: str, fmt: str, lang: str = "en") -> dict:
        """Ask where to save, write the file(s). Returns {"paths": [...]} or {"cancelled": True}."""
        import webview

        if fmt not in FILE_TYPES or version not in ("original", "edited", "both"):
            return {"error": "bad format"}
        data = store.read_transcript(job_id)
        stem = Path(data["filename"]).stem
        win = self._window()
        versions = ["original", "edited"] if version == "both" else [version]
        if len(versions) == 1:
            path = _first(win.create_file_dialog(
                webview.FileDialog.SAVE, directory=self._last_dir(),
                save_filename=f"{stem}.{versions[0]}.{fmt}", file_types=(FILE_TYPES[fmt],)))
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
        self._remember_dir(str(targets[0].parent))
        return {"paths": [str(t) for t in targets]}

    def reveal(self, path: str) -> None:
        """Open Explorer with the saved file selected."""
        p = Path(path)
        if not p.exists():
            return
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p.parent)])
