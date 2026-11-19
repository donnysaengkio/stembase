"""The desktop app: the interface in its own window, no browser and no console.
This is the entry point of the packaged .exe (and of `pythonw desktop.py`). The interface is served on a random
local port that only this computer can reach, and everything stops when the window is closed."""
import os, sys, socket, threading, traceback, multiprocessing

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.meta import APP_NAME, DATA_DIR, ICON

os.makedirs(DATA_DIR, exist_ok=True)
LOG = os.path.join(DATA_DIR, "log.txt")
# No console: send print/progress output to a log file instead of nowhere (None crashes tqdm).
if sys.stdout is None or sys.stderr is None or "--log" in sys.argv:
    sys.stdout = sys.stderr = open(LOG, "w", encoding="utf-8", buffering=1)
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
os.environ.setdefault("HF_HUB_OFFLINE", "1")   # models ship with the app; never look online
os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(DATA_DIR, "numba"))   # librosa's compiled code cache: must be writable

if sys.platform == "win32":  # own taskbar entry and icon instead of Python's
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_NAME.replace(" ", "") + ".App")
    except Exception:
        pass

import webview

SPLASH = f"""<html><body style="margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
background:#0b0f19;color:#e5e7eb;font-family:Segoe UI,sans-serif;flex-direction:column">
<div style="font-size:28px;font-weight:600">{APP_NAME}</div>
<div style="margin-top:12px;color:#9ca3af">Starting… loading the audio engines takes a few seconds</div>
</body></html>"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def set_icon(window):
    try:  # Windows (WinForms backend): give the window our icon
        import clr  # noqa: F401  (pythonnet, installed with pywebview)
        from System.Drawing import Icon
        window.native.Invoke(lambda: setattr(window.native, "Icon", Icon(ICON)))
    except Exception:
        pass


def boot(window):
    set_icon(window)
    try:
        import app  # builds the interface (slow part: torch, demucs, gradio)
        port = free_port()
        app.launch(port, open_browser=False, block=False)
        window.load_url(f"http://127.0.0.1:{port}/")
        if "--selftest" in sys.argv:  # packaging check: open, report what loaded, close
            def check():
                print("selftest url:", window.get_current_url())
                print("selftest tabs:", window.evaluate_js(
                    "Array.from(document.querySelectorAll('[role=tab]')).map(t => t.innerText.trim()).join(' | ')"))
                window.destroy()
            threading.Timer(8, check).start()
    except Exception:
        traceback.print_exc()
        msg = traceback.format_exc().replace("&", "&amp;").replace("<", "&lt;")
        window.load_html(f"<body style='font-family:Segoe UI;padding:24px'><h2>{APP_NAME} could not start</h2>"
                         f"<p>Details (also saved in {LOG}):</p><pre style='white-space:pre-wrap'>{msg}</pre></body>")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    webview.settings["ALLOW_DOWNLOADS"] = True
    w = webview.create_window(APP_NAME, html=SPLASH, width=1280, height=900, min_size=(900, 600), background_color="#0b0f19")
    webview.start(boot, w, private_mode=False, storage_path=os.path.join(DATA_DIR, "webview"))
    print("Window closed.")
    os._exit(0)  # also ends the hidden server and any separation worker threads
