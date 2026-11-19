@echo off
rem For running from source. The installed app needs none of this.
cd /d "%~dp0"
python -m pip install -r requirements.txt
rem Basic Pitch (audio to MIDI) lists TensorFlow as a requirement, but the app uses its small ONNX model instead.
python -m pip install --no-deps basic-pitch==0.4.0
pause
