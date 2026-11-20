"""Builds Stembase for the computer it runs on: Windows (.exe installer), macOS (.app and .dmg) or Linux (.AppImage and .deb).

    python build.py            # engine + app + installer
    python build.py --app      # only the app (reuses the engine already in dist/stembase-engine)

Needs: Python with requirements.txt and pyinstaller, Node.js, Rust, and on Linux the WebKitGTK packages Tauri lists.
Installers end up in ui/src-tauri/target/release/bundle/. Each system must build its own: PyInstaller cannot cross-compile.
"""
import os, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
UI = os.path.join(ROOT, "ui")
NPM = "npm.cmd" if sys.platform == "win32" else "npm"
NPX = "npx.cmd" if sys.platform == "win32" else "npx"


def run(cmd, cwd=ROOT):
    print("\n>", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def python():
    """The project's own environment (.venv) when there is one, so its packages (on Windows torch-directml with its
    older torch) don't have to replace those in the main Python; otherwise the Python running this script."""
    venv = os.path.join(ROOT, ".venv", "Scripts" if sys.platform == "win32" else "bin", "python")
    venv += ".exe" if sys.platform == "win32" else ""
    return venv if os.path.exists(venv) else sys.executable


def main():
    if "--app" not in sys.argv:
        shutil.rmtree(os.path.join(ROOT, "dist", "stembase-engine"), ignore_errors=True)
        run([python(), "-m", "PyInstaller", "stembase_engine.spec", "--noconfirm"])
    if not os.path.isdir(os.path.join(UI, "node_modules")):
        run([NPM, "ci"], cwd=UI)
    # Updates are signed: the app only installs an update signed with this key (its public half is in tauri.conf.json).
    key = os.path.join(os.path.expanduser("~"), ".tauri", "stembase.key")
    if not os.environ.get("TAURI_SIGNING_PRIVATE_KEY") and os.path.exists(key):
        os.environ["TAURI_SIGNING_PRIVATE_KEY"] = open(key).read().strip()
    os.environ.setdefault("TAURI_SIGNING_PRIVATE_KEY_PASSWORD", "")
    targets = {"win32": "nsis", "darwin": "app,dmg"}.get(sys.platform, "appimage,deb")
    run([NPX, "tauri", "build", "--bundles", targets], cwd=UI)
    print("\nDone. Installers:", os.path.join(UI, "src-tauri", "target", "release", "bundle"))


if __name__ == "__main__":
    main()
