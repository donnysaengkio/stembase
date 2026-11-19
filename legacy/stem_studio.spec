# PyInstaller build recipe. Run "Build installer.bat" (or: python -m PyInstaller stem_studio.spec --noconfirm).
# One-folder build: dist\Stem Studio\Stem Studio.exe plus its libraries and the bundled Demucs models.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

APP = "Stem Studio"
datas = [("stem_studio.ico", "."), ("models", "models")]
for pkg in ("gradio", "gradio_client", "safehttpx", "groovy", "librosa", "demucs", "webview", "pyloudnorm", "lazy_loader",
            "resampy"):
    datas += collect_data_files(pkg)
# Basic Pitch (audio to MIDI): only its small ONNX model; its TensorFlow / CoreML / TFLite copies are not needed.
datas += collect_data_files("basic_pitch", includes=["saved_models/icassp_2022/nmp.onnx"])
for pkg in ("gradio", "gradio_client", "torch", "librosa", "numpy", "demucs", "huggingface_hub", "safetensors", "tqdm",
            "regex", "requests", "packaging", "filelock", "pyyaml", "fastapi", "uvicorn", "httpx", "pydantic"):
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass

hidden = (collect_submodules("demucs") + collect_submodules("engine") + collect_submodules("basic_pitch")
          + ["app", "yaml", "safetensors.torch", "pyloudnorm", "onnxruntime", "pretty_midi", "mido", "resampy", "mir_eval"])

a = Analysis(
    ["desktop.py"],
    pathex=["."],
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter", "IPython", "notebook", "pytest", "matplotlib", "torch.utils.tensorboard", "tensorboard", "torchvision",
              "tensorflow", "coremltools", "tflite_runtime"],
    module_collection_mode={"gradio": "py", "gradio_client": "py"},   # gradio reads its own source at runtime
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=APP, icon="stem_studio.ico", console=False,
          version=None, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name=APP, upx=False)
