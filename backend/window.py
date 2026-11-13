"""The desktop window: WebView2 serves the UI and audio straight from disk.

No port is opened. pywebview would normally start a local HTTP server for local
files; instead we map two virtual host names to folders inside WebView2
(SetVirtualHostNameToFolderMapping), which only this window can resolve:

  https://app.sesdefteri/    -> frontend/      (the UI)
  https://media.sesdefteri/  -> data/jobs/     (each recording's audio.mp3)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import store

APP_HOST = "app.sesdefteri"
MEDIA_HOST = "media.sesdefteri"
START_URL = f"https://{APP_HOST}/index.html"


def frontend_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "frontend"


def install_virtual_hosts() -> None:
    """Patch pywebview's WebView2 start-up so the folders are mapped before the first load."""
    from webview.platforms import edgechromium
    from Microsoft.Web.WebView2.Core import CoreWebView2HostResourceAccessKind

    original = edgechromium.EdgeChrome.on_webview_ready
    if getattr(original, "_meet_patched", False):
        return

    def on_webview_ready(self, sender, args):
        if args.IsSuccess:
            core = sender.CoreWebView2
            allow = CoreWebView2HostResourceAccessKind.Allow
            core.SetVirtualHostNameToFolderMapping(APP_HOST, str(frontend_dir()), allow)
            core.SetVirtualHostNameToFolderMapping(MEDIA_HOST, str(store.jobs_dir()), allow)
        return original(self, sender, args)

    on_webview_ready._meet_patched = True
    edgechromium.EdgeChrome.on_webview_ready = on_webview_ready


def attach_file_drop(window, api) -> None:
    """Dropped files arrive with their full path (pywebview DOM events); start a job for each."""
    from webview.dom import DOMEventHandler

    def on_drop(event):
        for f in (event.get("dataTransfer") or {}).get("files", []):
            path = f.get("pywebviewFullPath")
            if not path:
                continue
            try:
                res = api.start_job(path)
                window.evaluate_js(f"window.onJobStarted && window.onJobStarted({json.dumps(res)})")
            except Exception as e:  # shown to the user
                window.evaluate_js(f"window.onJobError && window.onJobError({json.dumps(str(e))})")

    window.dom.document.events.drop += DOMEventHandler(on_drop, prevent_default=True, stop_propagation=True)
