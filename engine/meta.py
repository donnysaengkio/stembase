"""App name, version and folders. No heavy imports, so the window can appear before the audio engines load."""
import os, sys, json

APP_NAME = "Stembase"   # change here, in ui/src-tauri/tauri.conf.json and ui/package.json to rename the app
APP_VERSION = "2.0.0"
FROZEN = getattr(sys, "frozen", False)   # True inside the packaged engine
APP_DIR = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES_DIR = getattr(sys, "_MEIPASS", APP_DIR)   # bundled read-only resources (icon, models)
HOME = os.path.expanduser("~")
DEFAULT_OUTPUT_DIR = os.path.join(HOME, "Music", APP_NAME)   # results: never inside the program folder


def _data_dir():
    """Per-user app data (log, caches): the usual place on each system."""
    if sys.platform == "win32":
        return os.path.join(os.environ.get("LOCALAPPDATA") or HOME, APP_NAME)
    if sys.platform == "darwin":
        return os.path.join(HOME, "Library", "Application Support", APP_NAME)
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share"), APP_NAME)


DATA_DIR = _data_dir()
MODELS_DIR = os.path.join(RES_DIR, "models")   # Demucs models shipped with the app: models/<name>/<name>.yaml + *.safetensors
ICON = os.path.join(RES_DIR, "stembase.ico")
SETTINGS = os.path.join(DATA_DIR, "settings.json")   # engine settings kept between runs (the Output folder)


def _settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_output = _settings().get("output_dir") or DEFAULT_OUTPUT_DIR


def output_root():
    """The Output folder everything is saved in: Music/Stembase unless changed in Preferences."""
    return _output


def set_output_root(path):
    """Use another Output folder (None or "" goes back to the default). Raises OSError if it can't be written to."""
    global _output
    path = os.path.abspath(os.path.expanduser(path)) if path else DEFAULT_OUTPUT_DIR
    os.makedirs(path, exist_ok=True)
    probe = os.path.join(path, ".stembase-write-test")
    with open(probe, "w") as f:
        f.write("ok")
    os.remove(probe)
    s = _settings()
    s["output_dir"] = None if path == DEFAULT_OUTPUT_DIR else path
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    _output = path
    return path
