"""Entry point: local FastAPI server + native window (falls back to browser)."""
import socket
import sys
import threading
import time
import webbrowser

from backend import store

# pythonw / windowed .exe have no console: send output to a log file instead of None.
if sys.stdout is None or sys.stderr is None:
    _log = open(store.data_dir() / "app.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log

import uvicorn  # noqa: E402

from backend.main import app  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    if "--serve" in sys.argv:  # server only, fixed port (for testing the built .exe)
        port = int(sys.argv[sys.argv.index("--serve") + 1])
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", use_colors=False)
        return
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                           use_colors=False))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}/"
    if "--browser" in sys.argv:
        print("Open", url)
        webbrowser.open(url)
        while True:
            time.sleep(3600)
    try:
        import webview

        from backend.desktop import Api

        webview.create_window("Meeting Transcriber", url, width=1100, height=800, js_api=Api())
        webview.start()
    except Exception as e:
        print("Native window unavailable (", e, ") - opening browser")
        webbrowser.open(url)
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
