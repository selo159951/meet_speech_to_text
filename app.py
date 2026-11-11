"""Kâtip - desktop app (no web server, no open ports)."""
import sys

from backend import store

# One-time: copy an existing %APPDATA%\MeetTranscriber folder to %APPDATA%\Katip.
# Runs before data_dir() is used (also before the log file is opened below).
store.migrate_old_data()

# pythonw / windowed .exe have no console: send output to a log file instead of None.
if sys.stdout is None or sys.stderr is None:
    _log = open(store.data_dir() / "app.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log


def _fatal(msg: str) -> None:
    print(msg, file=sys.stderr)
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, msg, "Kâtip", 0x10)


def main():
    try:
        import webview

        from backend.bridge import Api
        from backend.window import START_URL, attach_file_drop, install_virtual_hosts
    except Exception as e:  # missing runtime pieces
        return _fatal(f"The app could not start:\n{e}")

    store.mark_interrupted()  # jobs cut off by closing the app can be resumed (after migrate_old_data)
    if sys.platform == "win32":
        install_virtual_hosts()
    api = Api()
    # starts maximized; the size below is what "restore down" gives
    window = webview.create_window("Kâtip", START_URL, width=1180, height=820,
                                   min_size=(720, 560), maximized=True, js_api=api)
    api._get_window = lambda: window
    attached = []

    def on_loaded():
        if not attached:  # the page is loaded once; register the drop handler once
            attach_file_drop(window, api)
            attached.append(True)

    window.events.loaded += on_loaded
    try:
        webview.start(gui="edgechromium" if sys.platform == "win32" else None,
                      private_mode=False, storage_path=str(store.data_dir() / "webview"))
    except Exception as e:
        _fatal("Microsoft Edge WebView2 is required.\n"
               "Install it from https://go.microsoft.com/fwlink/p/?LinkId=2124703\n\n" + str(e))


if __name__ == "__main__":
    main()
