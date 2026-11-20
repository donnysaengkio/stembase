"""Stembase engine: the audio work behind the app, as a small local web API that only the app can use.

The Tauri app starts this process, reads the line "STEMBASE_PORT=<port>" from its output, and sends every request with
the secret token it passed in STEMBASE_TOKEN. Jobs (analyze, separate, ...) run one at a time in a worker thread; the app
polls their progress. When the app's process (STEMBASE_PARENT_PID) ends, this process exits too.

Run on its own for development:  python server.py   (prints the port; no token needed when STEMBASE_TOKEN is unset)."""
import os, sys, json, socket, threading, traceback, time, uuid, queue, subprocess, multiprocessing

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.meta import APP_NAME, APP_VERSION, output_root, set_output_root, DEFAULT_OUTPUT_DIR, DATA_DIR, FROZEN

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(output_root(), exist_ok=True)
os.environ.setdefault("HF_HUB_OFFLINE", "1")   # models ship with the app; never look online
os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(DATA_DIR, "numba"))   # librosa's compiled-code cache: must be writable
LOG = os.path.join(DATA_DIR, "engine-log.txt")
TOKEN = os.environ.get("STEMBASE_TOKEN", "")

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

E = {}                     # engine modules, imported in the background so the app can show its window at once
READY = threading.Event()
LOAD_ERROR = []


def load_engine():
    try:
        from engine import analysis, separate, mashup, transform, convert, midi, chords, history, common, gpu
        E.update(analysis=analysis, sep=separate, mashup=mashup, transform=transform, conv=convert, midi=midi,
                 chords=chords, history=history, common=common, gpu=gpu)
    except Exception:
        traceback.print_exc()
        LOAD_ERROR.append(traceback.format_exc())
    READY.set()


# ---------------- choices shown in the app ----------------
STEM_ORDER = ["vocals", "drums", "bass", "other", "guitar", "piano", "instrumental"]
MIDI_STEMS = {"Vocals": "vocals", "Bass": "bass", "Other": "other", "Drums": "drums", "Guitar": "guitar", "Piano": "piano"}
MIDI_SOURCE = ["A Track Stem", "A Full Song"]
ARRANGE = ["Fit to the Music", "One Continuous Take"]
CONVERT_MODES = ["Choose a Format", "Fit to a Target Size"]
SEP_SPEED = {"htdemucs": 0.3, "htdemucs_ft": 1.2, "htdemucs_6s": 0.4}   # seconds of work per second of audio on a CPU


def info():
    c, sep, midi, conv = E["common"], E["sep"], E["midi"], E["conv"]
    return dict(name=APP_NAME, version=APP_VERSION, output_dir=output_root(), default_output_dir=DEFAULT_OUTPUT_DIR, data_dir=DATA_DIR, device=E["gpu"].label(), processing=E["gpu"].mode(), processing_modes=E["gpu"].MODES,
                gpu=(E["gpu"].gpu() or (None, None, None))[2],
                formats=list(c.FORMATS), default_format=c.DEFAULT_FORMAT, audio_exts=list(c.SUPPORTED),
                models=list(sep.MODELS), midi_stems=list(MIDI_STEMS), midi_source=MIDI_SOURCE, midi_parts=list(midi.PARTS),
                snap=list(midi.SNAP), arrange=ARRANGE, convert_modes=CONVERT_MODES, convert_formats=list(conv.FORMATS),
                sample_rates=list(conv.SAMPLE_RATES), channels=conv.CHANNELS, target_codecs=conv.TARGET_CODECS)


# ---------------- helpers ----------------
def audio_seconds(path):
    try:
        import soundfile as sf
        return sf.info(path).duration
    except Exception:
        return None


def about(seconds):
    if seconds is None: return "a few minutes"
    if seconds < 45: return "under a minute"
    m = round(seconds / 60)
    return "about a minute" if m <= 1 else f"about {m} minutes"


def sep_seconds(path, model):
    """Estimated separation time, 0 if this song was already separated with this model."""
    sep = E["sep"]
    if os.path.exists(os.path.join(sep.cache_dir(path, model), "instrumental.wav")): return 0
    d = audio_seconds(path)
    if d is None: return None
    return 15 + d * SEP_SPEED.get(model, 0.4) / {"cuda": 10, "directml": 1.6}.get(sep.device(), 1)


def entry(path):
    """A result file as the app shows it."""
    return dict(path=path, name=os.path.basename(path), size=os.path.getsize(path) if os.path.exists(path) else 0)


def need(*paths):
    if not all(paths): raise ValueError("Choose an audio file first." if len(paths) == 1 else "Choose both tracks first.")
    for p in paths: E["common"].check_input(p)


def name(path):
    return E["common"].track_name(path)


# ---------------- jobs: (start message, work) per kind ----------------
def plan_analyze(p):
    need(p["path"])
    secs = audio_seconds(p["path"]) or 240
    t, extra = secs * 0.1 + 5, ""
    if p.get("chords", True):
        t += secs * 0.05 + 5
        if p.get("remove_vocals") and E["chords"].chord_source(p["path"])[0] is None:
            st = sep_seconds(p["path"], "htdemucs")
            t = None if st is None else t + st
            extra = " (including removing the vocals for the chords)"
    return f"Analyzing **{name(p['path'])}**{extra}: {about(t)}."


def run_analyze(p, progress):
    an, ch = E["analysis"], E["chords"]
    path, want = p["path"], p.get("chords", True)
    d = {}
    share = 0.6 if want else 1.0
    rows = an.analyze(path, (p.get("bpm_lo", 70), p.get("bpm_hi", 180)), lambda f, s="": progress(f * share, s), details=d)
    g = d["grid"]
    res = dict(name=name(path), rows=[[k, v] for k, v in rows.items()], tiles=[
        dict(label="Key", value=rows["Key"], sub=f"{rows['Camelot']} · confidence {d['key_conf']:.2f}"),
        dict(label="Tempo", value=f"{g['bpm']:.2f} BPM", sub=f"half {g['bpm'] / 2:.2f} · double {g['bpm'] * 2:.2f}"),
        dict(label="Loudness", value=rows["Loudness"], sub=f"peak {rows['Peak']}"),
        dict(label="Length", value=rows["Duration"],
             sub=" · ".join(x for x in (rows.get("Sample Rate", ""), rows.get("Channels", "").lower()) if x)),
    ], chords=None, chords_midi=None, folder=None)
    if want:
        segs, src = ch.from_track(path, d, p.get("remove_vocals", False), lambda f, s="": progress(share + (1 - share) * f, s))
        prog, usage = ch.summary(segs)
        res["chords"] = dict(progression=prog, usage=[dict(chord=c, pct=pc) for c, pc in usage], source=src,
                             changes=[dict(bar=s["bar"], beat=s["beat"], chord=s["chord"])
                                      for s in segs if s["chord"] != "N" and s["bar"] >= 1])
        if prog:
            folder = os.path.join(output_root(), name(path), "MIDI")
            os.makedirs(folder, exist_ok=True)
            mid = ch.to_midi(segs, g["bpm"], os.path.join(folder, f"{name(path)} - Chords.mid"))
            res["chords_midi"], res["folder"] = entry(mid), folder
    return res


def plan_separate(p):
    need(p["path"])
    sep = E["sep"]
    label = p.get("model") or list(sep.MODELS)[0]
    t = sep_seconds(p["path"], sep.MODELS[label])
    if t == 0: return f"Exporting the stems of **{name(p['path'])}** It was already separated with this model, so this is quick."
    return (f"Separating **{name(p['path'])}** with the {label.split(':')[0]} model: {about(t)} on this "
            f"{'GPU' if sep.device() != 'cpu' else 'computer'}.")


def run_separate(p, progress):
    sep, midi = E["sep"], E["midi"]
    path = p["path"]
    model = sep.MODELS[p.get("model") or list(sep.MODELS)[0]]
    wanted = [MIDI_STEMS[m] for m in p.get("midi", []) if m in MIDI_STEMS]
    files = sep.export(path, model, p.get("format") or E["common"].DEFAULT_FORMAT,
                       lambda f, d="": progress(f * (0.85 if wanted else 1), d))
    folder = os.path.dirname(files["vocals"])
    msg = f"**{name(path)}**: {len(files)} stems saved to `{folder}`"
    mids = []
    if wanted:
        full = sep.separate(path, model)   # full-quality cached stems, whatever the export format
        missing = [sep.LABELS[s] for s in wanted if s not in full]
        done = midi.stems_to_midi(full, [s for s in wanted if s in full], folder, name(path),
                                  lambda f, d="": progress(0.85 + 0.15 * f, d))
        mids = [entry(m) for m in done.values()]
        if done: msg += f"\n\nMIDI made from: {', '.join(sep.LABELS[s] for s in done)}, saved next to the audio stems."
        if missing: msg += f"\n\n{', '.join(missing)}: only the 6-stem model separates these, so no MIDI was made for them."
    stems = [dict(entry(files[s]), stem=s, label=sep.LABELS[s]) for s in STEM_ORDER if s in files]
    return dict(title="Stems Ready", message=msg, stems=stems, midi=mids, folder=folder)


def plan_midi(p):
    need(p["path"])
    midi = E["midi"]
    part = p.get("part") or list(midi.PARTS)[0]
    if p.get("source") == MIDI_SOURCE[1]:
        model = "htdemucs_6s" if midi.PARTS[part].get("stem") in ("piano", "guitar") else "htdemucs"
        t = sep_seconds(p["path"], model)
        t = None if t is None else t + 30
        how = f"separating the {part.lower()} from the song first, then transcribing"
    else:
        t, how = (audio_seconds(p["path"]) or 240) * 0.05 + 25, "transcribing"
    return f"Turning **{name(p['path'])}** into MIDI, {how}: {about(t)}."


def run_midi(p, progress):
    midi = E["midi"]
    part = p.get("part") or list(midi.PARTS)[0]
    r = midi.audio_to_midi(p["path"], part, p.get("source") == MIDI_SOURCE[1], float(p.get("sensitivity", 0.5)),
                           int(p.get("min_ms", 80)), p.get("snap") or list(midi.SNAP)[0], progress)
    img = os.path.join(r["folder"], ".preview", f"{name(p['path'])} - {part.replace(' / ', ' & ')} (piano roll).png")
    r["image"].save(img)
    return dict(title="MIDI Ready", message=r["info"] + f"\n\nSaved `{r['midi']}`", midi=entry(r["midi"]),
                preview=entry(r["preview"]), image=entry(img), folder=r["folder"])


def plan_mashup(p):
    need(p.get("vocals"), p.get("instrumental"))
    sep = E["sep"]
    model = sep.MODELS[p.get("model") or list(sep.MODELS)[0]]
    t = [sep_seconds(x, model) for x in (p["vocals"], p["instrumental"])]
    total = None if None in t else sum(t) + 60
    return (f"Making the mashup of **{name(p['vocals'])}** and **{name(p['instrumental'])}**: {about(total)}, "
            f"separating {sum(1 for x in t if x != 0)} of the 2 songs, then matching and mixing.")


def run_mashup(p, progress):
    mash, sep = E["mashup"], E["sep"]
    arr = "continuous" if p.get("arrangement") == ARRANGE[1] else "sections"
    P, outs, out_dir, title = mash.make_mashup(p["vocals"], p["instrumental"], p.get("key", "Auto"), arr,
                                               float(p.get("vocal_gain", 0)), sep.MODELS[p.get("model") or list(sep.MODELS)[0]],
                                               p.get("format") or E["common"].DEFAULT_FORMAT, progress)
    return dict(title="Mashup Ready", audio=entry(outs["Mashup"]),
                message=mash.report(P, p["vocals"], p["instrumental"]) + f"\n\nThe mix and its aligned stems are saved to `{out_dir}`",
                folder=out_dir)


def plan_shift(p):
    need(p["path"])
    if not float(p.get("semitones") or 0) and not float(p.get("bpm") or 0):
        raise ValueError("Nothing to change: set a key shift or a target BPM.")
    return f"Rendering **{name(p['path'])}**: {about((audio_seconds(p['path']) or 240) * 0.15 + 5)}."


def run_shift(p, progress):
    semis, bpm = float(p.get("semitones") or 0), float(p.get("bpm") or 0)
    out, src, st = E["transform"].change(p["path"], semis, bpm, p.get("format") or E["common"].DEFAULT_FORMAT, progress)
    info = f"Saved `{out}`"
    if src: info += f"\n\nDetected tempo {src:.2f} BPM → {bpm:g} BPM, {100 * (st - 1):+.2f}%"
    return dict(title="Shift Ready", audio=entry(out), message=info, folder=os.path.dirname(out))


def plan_convert(p):
    files = p.get("paths") or []
    if not files: raise ValueError("Add one or more audio files first.")
    if p.get("mode") == CONVERT_MODES[1] and not float(p.get("target_mb") or 0) > 0:
        raise ValueError("Enter a target size in MB.")
    return f"Converting {len(files)} file{'s' if len(files) != 1 else ''}: {about(len(files) * 8)}."


def run_convert(p, progress):
    conv = E["conv"]
    files, fit = p["paths"], p.get("mode") == CONVERT_MODES[1]
    rows, outs, errors, lossless_from_lossy = [], [], [], []
    for i, f in enumerate(files):
        step = lambda x, d="", i=i: progress((i + x) / len(files), f"{i + 1}/{len(files)}: {d}")
        try:
            r = conv.convert(f, None if fit else p.get("format"), p.get("sample_rate") or "Keep original",
                             p.get("channels") or conv.CHANNELS[0], float(p["target_mb"]) if fit else None,
                             p.get("codec") or conv.TARGET_CODECS[0], progress=step)
        except Exception as e:
            traceback.print_exc(); errors.append(f"- **{os.path.basename(f)}**: {e}"); continue
        outs.append(entry(r["output"]))
        if r["lossy_to_lossless"]: lossless_from_lossy.append(os.path.basename(f))
        rows.append([os.path.basename(f), r["format"], f"{r['sample_rate']} Hz, {'mono' if r['channels'] == 1 else 'stereo'}",
                     f"{r['before_mb']:.2f} MB", f"{r['after_mb']:.2f} MB", f"{r['change']:+.0f}%", os.path.basename(r["output"])])
    folder = os.path.dirname(outs[0]["path"]) if outs else os.path.join(output_root(), "Converted")
    msg = f"Converted {len(outs)} of {len(files)} file{'s' if len(files) != 1 else ''} into `{folder}`."
    if lossless_from_lossy:
        msg += ("\n\nNote: " + ", ".join(lossless_from_lossy) + " started as MP3/Ogg/Opus. Converting to WAV, AIFF or FLAC "
                "makes the file bigger but cannot bring back detail the original compression removed.")
    if errors: msg += "\n\nNot converted:\n" + "\n".join(errors)
    return dict(title="Converted" if outs else "Nothing converted", message=msg, files=outs, rows=rows, folder=folder)


KINDS = {"analyze": (plan_analyze, run_analyze), "separate": (plan_separate, run_separate), "midi": (plan_midi, run_midi),
         "mashup": (plan_mashup, run_mashup), "shift": (plan_shift, run_shift), "convert": (plan_convert, run_convert)}


# ---------------- job queue ----------------
class Cancelled(BaseException):
    """Raised inside a job when the app asks to cancel it. A BaseException, so the engine's `except Exception`
    handlers (which skip a bad file and carry on) don't swallow it."""


class Job:
    def __init__(self, kind, params, message):
        self.id, self.kind, self.params, self.message = uuid.uuid4().hex, kind, params, message
        self.state, self.progress, self.desc, self.result, self.error = "queued", 0.0, "", None, None
        self.started = self.finished = None
        self.cancel = False

    def view(self):
        now = self.finished or time.time()
        return dict(id=self.id, kind=self.kind, state=self.state, message=self.message, progress=round(self.progress, 4),
                    desc="Cancelling…" if self.cancel and self.state == "running" else self.desc, elapsed=round(now - self.started, 1) if self.started else 0, result=self.result,
                    error=self.error)


JOBS, Q = {}, queue.Queue()


def worker():
    while True:
        job = Q.get()
        if job.cancel:   # cancelled while waiting for its turn
            job.state, job.finished = "cancelled", time.time()
            continue
        job.state, job.started = "running", time.time()

        def progress(f, d=""):
            if job.cancel: raise Cancelled()   # every job reports progress often, so it stops at its next step
            job.progress = max(job.progress, min(float(f), 1.0))   # never moves backwards
            if d: job.desc = d

        try:
            READY.wait()
            job.result = KINDS[job.kind][1](job.params, progress)
            job.progress, job.state = 1.0, "done"
        except Cancelled:
            job.state = "cancelled"
        except Exception as e:
            traceback.print_exc()
            job.error = str(e) if isinstance(e, ValueError) else f"{type(e).__name__}: {e}"
            job.state = "error"
        job.finished = time.time()


def user_error(e):
    return JSONResponse({"error": str(e) if isinstance(e, ValueError) else f"{type(e).__name__}: {e}"}, status_code=400)


# ---------------- web API ----------------
app = FastAPI(title=f"{APP_NAME} engine", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def check_token(request: Request, call_next):
    if request.method != "OPTIONS" and TOKEN:
        got = request.headers.get("x-stembase-token") or request.query_params.get("t")
        if got != TOKEN: return JSONResponse({"error": "not allowed"}, status_code=403)
    return await call_next(request)


@app.get("/api/status")
def status():
    if not READY.is_set(): return {"ready": False}
    if LOAD_ERROR: return {"ready": False, "error": LOAD_ERROR[0], "log": LOG}
    return {"ready": True, "info": info()}


@app.post("/api/jobs/{kind}")
async def start_job(kind: str, request: Request):
    if kind not in KINDS: raise HTTPException(404, "unknown job")
    if not READY.is_set() or LOAD_ERROR: return user_error(ValueError("The audio engine is still starting. Try again in a moment."))
    params = await request.json()
    try:
        message = KINDS[kind][0](params)
    except Exception as e:
        return user_error(e)
    job = Job(kind, params, message)
    JOBS[job.id] = job
    Q.put(job)
    return job.view()


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    """Ask a job to stop: it ends at its next progress step (a queued job never starts)."""
    if job_id not in JOBS: raise HTTPException(404, "unknown job")
    job = JOBS[job_id]
    if job.state in ("queued", "running"): job.cancel = True
    return job.view()


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    if job_id not in JOBS: raise HTTPException(404, "unknown job")
    return JOBS[job_id].view()


CHECKS = {"split": lambda q: E["history"].split(q.get("path"), q.get("model")),
          "analyze": lambda q: E["history"].analysis(q.get("path")),
          "midi": lambda q: E["history"].midi(q.get("path")),
          "mashup": lambda q: E["history"].mashup(q.get("vocals"), q.get("instrumental")),
          "shift": lambda q: E["history"].shift(q.get("path")),
          "convert": lambda q: E["history"].converted(q.get("paths") or [])}


@app.post("/api/check/{kind}")
async def check_done(kind: str, request: Request):
    """Results from an earlier run of this tab for these files, or null."""
    if kind not in CHECKS or not READY.is_set() or LOAD_ERROR: return {"found": None}
    try:
        return {"found": CHECKS[kind](await request.json())}
    except Exception:
        traceback.print_exc()
        return {"found": None}


@app.post("/api/output-folder")
async def change_output_folder(request: Request):
    """Use another Output folder from now on ({"path": null} goes back to Music/Stembase). Not while a job runs."""
    if any(j.state in ("queued", "running") for j in JOBS.values()):
        return JSONResponse({"error": "Wait for the current job to finish, then change the Output folder."}, 409)
    try:
        return {"output_dir": set_output_root((await request.json()).get("path"))}
    except OSError as e:
        return JSONResponse({"error": f"Stembase can't save files in that folder: {e.strerror or e}"}, 400)


PEAKS = {}   # (path, size, mtime, n) -> peaks, so a waveform is only read once


@app.get("/api/peaks")
def peaks(path: str, n: int = 600):
    """The waveform outline of an audio file: n loudness peaks between 0 and 1, plus its length in seconds."""
    if not os.path.isfile(path): raise HTTPException(404, "not found")
    n = max(50, min(int(n), 2000))
    st = os.stat(path)
    key = (path, st.st_size, st.st_mtime, n)
    if key not in PEAKS:
        import numpy as np
        try:
            import soundfile as sf   # fast for WAV, FLAC, AIFF, OGG
            y, sr = sf.read(path, dtype="float32", always_2d=True)
            y = np.abs(y).max(axis=1)
        except Exception:
            import librosa             # MP3 and anything soundfile can't open
            y, sr = librosa.load(path, sr=11025, mono=True)
            y = np.abs(y)
        dur = len(y) / sr if sr else 0
        if len(y) < n: y = np.pad(y, (0, n - len(y)))
        p = y[: len(y) // n * n].reshape(n, -1).max(axis=1)
        top = float(p.max()) or 1.0
        if len(PEAKS) > 64: PEAKS.clear()
        PEAKS[key] = {"peaks": [round(float(v) / top, 3) for v in p], "duration": round(dur, 3)}
    return PEAKS[key]


@app.post("/api/processing")
async def change_processing(request: Request):
    """Automatic, GPU or CPU for stem separation; used from the next job on."""
    try:
        E["gpu"].set_mode((await request.json()).get("mode"))
    except ValueError as e:
        return user_error(e)
    return {"processing": E["gpu"].mode(), "device": E["gpu"].label()}


@app.get("/api/file")
def get_file(path: str):
    """A file to play or show in the app (audio, MIDI previews, piano rolls)."""
    if not os.path.isfile(path): raise HTTPException(404, "not found")
    return FileResponse(path)


@app.post("/api/open")
async def open_location(request: Request):
    """Show a result in the file manager: a folder opens, a file is selected in its folder."""
    path = (await request.json()).get("path") or output_root()
    if not os.path.exists(path): path = output_root()
    os.makedirs(output_root(), exist_ok=True)
    is_file = os.path.isfile(path)
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)] if is_file else ["explorer", os.path.normpath(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path] if is_file else ["open", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path) if is_file else path])
    return {"ok": True}


# ---------------- start ----------------
def watch_parent(pid):
    """Stop when the app that started us is gone (it quit or crashed), so no engine is left running in the background.
    (Reading stdin for this would be simpler, but on Windows a thread blocked on a pipe can freeze the whole process.)"""
    if sys.platform == "win32":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x00100000, False, pid)   # SYNCHRONIZE
        if h: k.WaitForSingleObject(h, 0xFFFFFFFF)
    else:
        while True:
            try:
                os.kill(pid, 0)
            except OSError:
                break
            time.sleep(1)
    os._exit(0)


def main():
    import uvicorn
    if os.environ.get("STEMBASE_PARENT_PID", "").isdigit():
        threading.Thread(target=watch_parent, args=(int(os.environ["STEMBASE_PARENT_PID"]),), daemon=True).start()
    if FROZEN or "--log" in sys.argv:   # nobody reads our output apart from the port line: keep the rest in a log file
        out = open(LOG, "w", encoding="utf-8", buffering=1)
        real_stdout, sys.stdout, sys.stderr = sys.stdout, out, out
    else:
        real_stdout = sys.stdout
    # Load the audio engines before serving: importing torch & co. in a thread while the server runs can deadlock.
    load_engine()
    threading.Thread(target=worker, daemon=True).start()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    print(f"STEMBASE_PORT={port}", file=real_stdout, flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
