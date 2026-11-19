# PyInstaller recipe for the Stembase audio engine (server.py), the same on Windows, macOS and Linux.
# Run through build.py, or:  python -m PyInstaller stembase_engine.spec --noconfirm
# Output: dist/stembase-engine/ (the program plus its libraries and the Demucs models). The Tauri app bundles this folder.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

datas = [("models", "models")]
for pkg in ("librosa", "demucs", "pyloudnorm", "lazy_loader", "resampy"):
    datas += collect_data_files(pkg)
# Basic Pitch (audio to MIDI): only its small ONNX model; its TensorFlow / CoreML / TFLite copies are not needed.
datas += collect_data_files("basic_pitch", includes=["saved_models/icassp_2022/nmp.onnx"])
for pkg in ("torch", "librosa", "numpy", "demucs", "safetensors", "tqdm", "regex", "packaging", "filelock", "pyyaml",
            "fastapi", "starlette", "uvicorn", "pydantic"):
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass

hidden = (collect_submodules("demucs") + collect_submodules("engine") + collect_submodules("basic_pitch")
          + collect_submodules("uvicorn")
          + ["yaml", "safetensors.torch", "pyloudnorm", "onnxruntime", "pretty_midi", "mido", "resampy", "mir_eval"])

a = Analysis(
    ["server.py"],
    pathex=["."],
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter", "IPython", "notebook", "pytest", "matplotlib", "torch.utils.tensorboard", "tensorboard", "torchvision",
              "tensorflow", "coremltools", "tflite_runtime", "gradio", "gradio_client", "webview"],
    noarchive=False,
)
pyz = PYZ(a.pure)
# console=True keeps stdout working (the app reads the port line from it); the app starts it without a visible window.
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="stembase-engine", console=True, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="stembase-engine", upx=False)
