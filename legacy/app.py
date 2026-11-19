"""Music analysis, stem separation, mashups and key/tempo changes. Builds the interface (`demo`).
desktop.py shows it in its own window (that is what the installed app runs); `python app.py` opens it in a browser instead."""
import os, sys, subprocess, traceback, time
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")   # fully offline: no usage pings
import gradio as gr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.common import APP_NAME, APP_VERSION, OUTPUT_DIR, track_name, check_input, FORMATS, DEFAULT_FORMAT
from engine import analysis, separate as sep, mashup, transform, convert as conv, midi
from engine.icons import tab_css
from engine import chords
import html

os.makedirs(OUTPUT_DIR, exist_ok=True)
STEM_ORDER = ["vocals", "drums", "bass", "other", "guitar", "piano", "instrumental"]
STEM_TITLES = sep.LABELS
MIDI_STEMS = {"Vocals": "vocals", "Bass": "bass", "Other instruments": "other", "Drums": "drums",
              "Guitar (6-stem model)": "guitar", "Piano (6-stem model)": "piano"}
MIDI_SOURCE = ["Just that part (a single instrument, voice or drum recording)", "A full song: separate the part out first"]
ARRANGE = ["Place vocal sections on the instrumental's phrases (recommended)", "Keep the vocal as one continuous take"]


def gp(progress):
    return lambda f, d="": progress(f, desc=d)


def open_folder(path):
    path = path or OUTPUT_DIR
    os.makedirs(path, exist_ok=True)
    if sys.platform == "win32": os.startfile(path)
    elif sys.platform == "darwin": subprocess.Popen(["open", path])
    else: subprocess.Popen(["xdg-open", path])


def fail(e):
    traceback.print_exc()
    raise gr.Error(str(e) if isinstance(e, ValueError) else f"{type(e).__name__}: {e}")


# ---------------- feedback while a job runs ----------------
# Every action button works the same way: an instant confirmation (button disabled, "⏳ ..." status with a time
# estimate), then the job with its progress bar drawn on that always-visible status area, then the button comes back.
WAIT = "⏳ "
# Seconds of separation work per second of audio, measured on this PC's CPU (much faster on an NVIDIA GPU).
SEP_SPEED = {"htdemucs": 0.3, "htdemucs_ft": 1.2, "htdemucs_6s": 0.4}


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
    if os.path.exists(os.path.join(sep.cache_dir(path, model), "instrumental.wav")): return 0
    d = audio_seconds(path)
    if d is None: return None
    return 15 + d * SEP_SPEED.get(model, 0.4) / (10 if sep.device() == "cuda" else 1)


def need(*paths):
    if not all(paths): raise gr.Error("Choose an audio file first." if len(paths) == 1 else "Choose both tracks first.")


def busy(msg):
    """Button disabled, confirmation message, progress area shown."""
    return gr.update(interactive=False, value="Working…"), WAIT + msg, gr.update(visible=True)


def finished(label):
    def f(status):
        if isinstance(status, str) and status.startswith(WAIT):   # the job raised an error before replacing the status
            status = "❌ Stopped before finishing. The reason is in the red message box."
        return gr.update(interactive=True, value=label), status, gr.update(visible=False)
    return f


def progress_area():
    """Where the progress bar is drawn (below the status message, so both stay readable); visible only while working."""
    return gr.Markdown(visible=False, min_height=64)


def run_button(btn, label, start, start_in, start_out, job, job_in, job_out, status, prog):
    # The quick steps go through the queue (so a gr.Error shows as a message box) with no concurrency limit (so they are
    # never stuck behind another tab's long job); the job itself queues one at a time.
    btn.click(start, start_in, [btn, status, prog] + start_out, concurrency_limit=None, show_progress="hidden") \
       .success(job, job_in, job_out, show_progress_on=[prog]) \
       .then(finished(label), status, [btn, status, prog], concurrency_limit=None, show_progress="hidden")


def start_analyze(path, want_chords, remove_vocals):
    need(path)
    secs = audio_seconds(path) or 240
    t, extra = secs * 0.1 + 5, ""
    if want_chords:
        t += secs * 0.05 + 5
        if remove_vocals and chords.chord_source(path)[0] is None:
            st = sep_seconds(path, "htdemucs")
            t = None if st is None else t + st
            extra = " (including removing the vocals for the chords)"
    return busy(f"Analyzing **{track_name(path)}**{extra}: {about(t)}.")


def start_separate(path, model_label):
    need(path)
    model = sep.MODELS[model_label]
    t = sep_seconds(path, model)
    msg = (f"Exporting the stems of **{track_name(path)}** (already separated with this model, so this is quick)." if t == 0 else
           f"Separating **{track_name(path)}** with the {model_label.split(':')[0]} model: {about(t)} on this "
           f"{'GPU' if sep.device() == 'cuda' else 'computer'}.")
    return busy(msg) + tuple(gr.update(visible=False, value=None) for _ in STEM_ORDER + ["midi files"])


STEM_EXTS = (".wav", ".flac", ".mp3", ".ogg", ".opus", ".aif", ".aiff")


def check_already_split(path, model_label):
    """When a song that was split before is loaded, say so in the pop-up and offer its folder.
    -> (status, progress area, buttons row, pop-up, folder)."""
    if not path: return (gr.update(),) * 5
    found = []
    for label, m in sep.MODELS.items():
        d = sep.stem_dir(path, m)
        if os.path.isdir(d) and any(f.lower().endswith(STEM_EXTS) for f in os.listdir(d)):
            found.append((label, d))
    if not found: return (gr.update(),) * 5
    found.sort(key=lambda x: x[0] != model_label)          # the selected model's folder first
    folder = found[0][1]
    names = [l.split(":")[0] for l, _ in found]
    which = names[0] + " model" if len(names) == 1 else ", ".join(names[:-1]) + f" and {names[-1]} models"
    when = time.strftime("%b %d, %Y", time.localtime(os.path.getmtime(folder)))
    msg = (f"### 📁 Already split\n\n**{track_name(path)}** was split before with the {which} "
           f"(last on {when}). The stems are in `{folder}`.\n\n"
           "Press **Separate** again only to export in another format or to add MIDI.")
    return msg, gr.update(visible=False), gr.update(visible=True), gr.update(visible=True), folder


def _when(path):
    return time.strftime("%b %d, %Y", time.localtime(os.path.getmtime(path)))


def _files(folder, ok=lambda f: True):
    """Files in a folder (not subfolders) that pass `ok`, newest first."""
    if not os.path.isdir(folder): return []
    fs = [os.path.join(folder, f) for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f)) and ok(f)]
    return sorted(fs, key=os.path.getmtime, reverse=True)


def _list(names):
    names = list(names)
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


# Each checker: input paths -> (message, folder to open) when results from an earlier run exist, else None.
def found_analysis(path):
    if not path: return None
    name = track_name(path)
    mid = os.path.join(OUTPUT_DIR, name, "MIDI", f"{name} - Chords.mid")
    if not os.path.exists(mid): return None
    return (f"### 📁 Analyzed before\n\nThe chords of **{name}** were saved on {_when(mid)} in "
            f"`{os.path.dirname(mid)}`.\n\nKey, tempo and loudness aren't saved, so press **Analyze** to see them again."), \
        os.path.dirname(mid)


def found_midi(path):
    if not path: return None
    name = track_name(path)
    folder = os.path.join(OUTPUT_DIR, name, "MIDI")
    mids = _files(folder, lambda f: f.lower().endswith(".mid"))
    if not mids: return None
    parts = [os.path.splitext(os.path.basename(m))[0].removeprefix(f"{name} - ") for m in mids]
    return (f"### 📁 MIDI made before\n\n**{name}** already has MIDI for {_list(parts)} (latest on {_when(mids[0])}), "
            f"in `{folder}`.\n\nPress **Make MIDI** again for another part or other settings. "
            "Making the same part again replaces its file."), folder


def found_mashup(vpath, ipath):
    if not (vpath and ipath): return None
    title = f"{track_name(vpath)} x {track_name(ipath)}"
    folder = os.path.join(OUTPUT_DIR, "Mashups", title)
    outs = _files(folder, lambda f: f.lower().endswith(STEM_EXTS))
    if not outs: return None
    return (f"### 📁 Mashup made before\n\n**{title}** was made on {_when(outs[0])}, in `{folder}`.\n\n"
            "Press **Make mashup** again to remake it with other settings. It replaces the earlier files."), folder


def found_shift(path):
    if not path: return None
    name = track_name(path)
    folder = os.path.join(OUTPUT_DIR, name)
    outs = _files(folder, lambda f: f.startswith(f"{name} (") and f.lower().endswith(STEM_EXTS))
    if not outs: return None
    tags = list(dict.fromkeys(os.path.splitext(os.path.basename(o))[0][len(name) + 2:-1] for o in outs))
    return (f"### 📁 Shifted before\n\n**{name}** already has {'a version' if len(tags) == 1 else 'versions'} at "
            f"{_list(tags)} (latest on {_when(outs[0])}), in `{folder}`.\n\n"
            "Rendering the same settings again replaces that file."), folder


def found_converted(paths):
    if not paths: return None
    folder = os.path.join(OUTPUT_DIR, "Converted")
    have = _files(folder)
    stems = {os.path.splitext(os.path.basename(h))[0] for h in have}
    done = []
    for p in paths:
        n = track_name(p)
        if n in stems or any(s.startswith(f"{n} (") and s[len(n) + 2:-1].isdigit() for s in stems): done.append(n)
    if not done: return None
    head = f"**{done[0]}** is" if len(paths) == 1 else f"{len(done)} of these {len(paths)} files {'is' if len(done) == 1 else 'are'}"
    return (f"### 📁 Converted before\n\n{head} already in `{folder}`"
            f"{'' if len(paths) == 1 else ': ' + _list(done)}.\n\n"
            "Converting again saves a new numbered copy; it doesn't replace the old one."), folder


def done_popup(open_label, checker, triggers, inputs):
    """'Done before' pop-up for a tab: shown when a loaded file already has results, with Open folder and Close."""
    folder = gr.State(OUTPUT_DIR)
    with gr.Column(visible=False, elem_classes="ss-modal") as box:
        with gr.Column(elem_classes="ss-dialog"):
            msg = gr.Markdown()
            with gr.Row():
                op = gr.Button(open_label, variant="primary")
                cl = gr.Button("Close")

    def check(*a):
        r = checker(*a)
        return (gr.update(), gr.update(), gr.update()) if not r else (gr.update(visible=True), r[0], r[1])

    for t in triggers:
        t.change(check, inputs, [box, msg, folder], show_progress="hidden")
    op.click(open_folder, folder, None)
    cl.click(lambda: gr.update(visible=False), None, box, show_progress="hidden")


def start_midi(path, part, full_song):
    need(path)
    if full_song == MIDI_SOURCE[1]:
        model = "htdemucs_6s" if midi.PARTS[part].get("stem") in ("piano", "guitar") else "htdemucs"
        t = sep_seconds(path, model)
        t = None if t is None else t + 30
        how = f"separating the {part.lower()} from the song first, then transcribing"
    else:
        t, how = (audio_seconds(path) or 240) * 0.05 + 25, "transcribing"
    return busy(f"Turning **{track_name(path)}** into MIDI ({how}): {about(t)}.")


def start_mashup(vpath, ipath, model_label):
    need(vpath, ipath)
    model = sep.MODELS[model_label]
    t = [sep_seconds(p, model) for p in (vpath, ipath)]
    total = None if None in t else sum(t) + 60
    return busy(f"Making the mashup of **{track_name(vpath)}** and **{track_name(ipath)}**: {about(total)} "
                f"(separating {sum(1 for x in t if x != 0)} of the 2 songs, then matching and mixing).")


def start_transform(path, semis, bpm):
    need(path)
    if not semis and not bpm: raise gr.Error("Nothing to change: set a key shift or a target BPM.")
    return busy(f"Rendering **{track_name(path)}**: {about((audio_seconds(path) or 240) * 0.15 + 5)}.")


def start_convert(files):
    if not files: raise gr.Error("Add one or more audio files first.")
    n = len(files)
    return busy(f"Converting {n} file{'s' if n != 1 else ''}: {about(n * 8)}.")


# ---------------- handlers ----------------
def do_analyze(path, lo, hi, want_chords, remove_vocals, progress=gr.Progress()):
    try:
        check_input(path)
        d = {}
        share = 0.6 if want_chords else 1.0
        rows = analysis.analyze(path, (lo, hi), lambda f, s="": progress(f * share, desc=s), details=d)
        segs, src, mid = [], "", None
        if want_chords:
            segs, src = chords.from_track(path, d, remove_vocals, lambda f, s="": progress(share + (1 - share) * f, desc=s))
            if any(s["chord"] != "N" for s in segs):
                folder = os.path.join(OUTPUT_DIR, track_name(path), "MIDI")
                os.makedirs(folder, exist_ok=True)
                mid = chords.to_midi(segs, d["grid"]["bpm"], os.path.join(folder, f"{track_name(path)} - Chords.mid"))
        card = analysis_card(track_name(path), rows, d, segs, src, want_chords)
        return (card, gr.update(value=mid, visible=bool(mid)), [[k, v] for k, v in rows.items()],
                gr.update(visible=True), "")
    except Exception as e: fail(e)


def do_separate(path, model_label, midi_labels, fmt, progress=gr.Progress(track_tqdm=True)):
    try:
        check_input(path)
        model = sep.MODELS[model_label]
        has_midi = bool(midi_labels)
        files = sep.export(path, model, fmt, lambda f, d="": progress(f * (0.85 if has_midi else 1), desc=d))
        ups = [gr.update(value=files[s], visible=True, label=STEM_TITLES[s]) if s in files else gr.update(value=None, visible=False)
               for s in STEM_ORDER]
        folder = os.path.dirname(files["vocals"])
        msg, mids = f"### ✅ Stems ready\n\n**{track_name(path)}**: {len(files)} stems saved to `{folder}`", []
        if has_midi:
            wanted = [MIDI_STEMS[m] for m in midi_labels]
            full = sep.separate(path, model)   # full-quality cached stems, whatever the export format
            missing = [STEM_TITLES[s] for s in wanted if s not in full]
            done = midi.stems_to_midi(full, [s for s in wanted if s in full], folder, track_name(path),
                                      lambda f, d="": progress(0.85 + 0.15 * f, desc=d))
            mids = list(done.values())
            msg += f"\n\nMIDI made from: {', '.join(STEM_TITLES[s] for s in done)} (saved next to the audio stems)."
            if missing: msg += f"\n\n{', '.join(missing)}: only the 6-stem model separates these, so no MIDI was made for them."
        return ups + [gr.update(value=mids or None, visible=bool(mids)), msg, folder]
    except Exception as e: fail(e)


def do_midi(path, part, full_song, sensitivity, min_ms, snap_label, progress=gr.Progress(track_tqdm=True)):
    try:
        check_input(path)
        r = midi.audio_to_midi(path, part, full_song == MIDI_SOURCE[1], sensitivity, min_ms, snap_label, gp(progress))
        return r["midi"], r["preview"], r["image"], r["info"] + f"\n\nSaved `{r['midi']}`", r["folder"]
    except Exception as e: fail(e)


def do_mashup(vpath, ipath, arrangement, key, vgain, model_label, fmt, progress=gr.Progress(track_tqdm=True)):
    try:
        check_input(vpath); check_input(ipath)
        arr = "continuous" if arrangement == ARRANGE[1] else "sections"
        P, outs, out_dir, title = mashup.make_mashup(vpath, ipath, key, arr, vgain, sep.MODELS[model_label], fmt, gp(progress))
        return outs["Mashup"], mashup.report(P, vpath, ipath) + f"\n\nSaved to `{out_dir}` (mix plus aligned stems)", out_dir
    except Exception as e: fail(e)


def do_transform(path, semis, bpm, fmt, progress=gr.Progress()):
    try:
        check_input(path)
        out, src, st = transform.change(path, semis, bpm or 0, fmt, gp(progress))
        info = f"Saved `{out}`"
        if src: info += f"\n\nDetected tempo {src:.2f} BPM → {bpm:g} BPM ({100 * (st - 1):+.2f}%)"
        return out, info, os.path.dirname(out)
    except Exception as e: fail(e)


CONVERT_MODES = ["Choose a format and quality", "Fit each file into a target size"]


def do_convert(files, mode, fmt_label, target_mb, target_codec, rate, channels, progress=gr.Progress()):
    try:
        files = [f if isinstance(f, str) else f.name for f in (files or [])]
        if not files: raise ValueError("Add one or more audio files first.")
        fit = mode == CONVERT_MODES[1]
        if fit and not (target_mb and target_mb > 0): raise ValueError("Enter a target size in MB.")
        rows, outs, errors, lossless_from_lossy = [], [], [], []
        for i, f in enumerate(files):
            step = lambda p, d="", i=i: progress((i + p) / len(files), desc=f"{i + 1}/{len(files)}: {d}")
            try:
                r = conv.convert(f, None if fit else fmt_label, rate, channels, target_mb if fit else None, target_codec, progress=step)
            except Exception as e:
                traceback.print_exc(); errors.append(f"- **{os.path.basename(f)}**: {e}"); continue
            outs.append(r["output"])
            if r["lossy_to_lossless"]: lossless_from_lossy.append(os.path.basename(f))
            rows.append([os.path.basename(f), r["format"], f"{r['sample_rate']} Hz, {'mono' if r['channels'] == 1 else 'stereo'}",
                         f"{r['before_mb']:.2f} MB", f"{r['after_mb']:.2f} MB", f"{r['change']:+.0f}%", os.path.basename(r["output"])])
        folder = os.path.dirname(outs[0]) if outs else os.path.join(OUTPUT_DIR, "Converted")
        msg = f"Converted {len(outs)} of {len(files)} file(s) into `{folder}`."
        if lossless_from_lossy:
            msg += ("\n\nNote: " + ", ".join(lossless_from_lossy) + " started as MP3/Ogg/Opus. Converting to WAV, AIFF or FLAC "
                    "makes the file bigger but cannot bring back detail the original compression removed.")
        if errors: msg += "\n\nNot converted:\n" + "\n".join(errors)
        return gr.update(value=rows, visible=bool(rows)), outs, msg, folder
    except Exception as e: fail(e)


# ---------------- Analyze results card ----------------
AN_CSS = """
.an-card{border:1px solid var(--border-color-primary);border-radius:var(--block-radius);padding:16px 18px;background:var(--block-background-fill)}
.an-card h3{margin:0 0 12px;font-size:var(--text-xl)}
.an-empty{color:var(--body-text-color-subdued);text-align:center;padding:42px 12px}
.an-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:14px}
.an-tile{background:var(--background-fill-secondary);border-radius:8px;padding:10px 12px}
.an-tile .l{font-size:var(--text-sm);color:var(--body-text-color-subdued)}
.an-tile .v{font-size:22px;font-weight:600;line-height:1.3}
.an-tile .s{font-size:var(--text-sm);color:var(--body-text-color-subdued)}
.an-sec{font-size:var(--text-sm);color:var(--body-text-color-subdued);margin:12px 0 6px}
.an-prog{font-size:20px;font-weight:600;color:var(--color-accent)}
.an-chips{display:flex;flex-wrap:wrap;gap:6px}
.an-chip{border:1px solid var(--border-color-primary);border-radius:6px;padding:3px 8px;font-size:var(--text-sm)}
.an-chip b{font-weight:600}
.an-chip i{font-style:normal;color:var(--body-text-color-subdued);margin-right:5px}
.an-note{font-size:var(--text-sm);color:var(--body-text-color-subdued);margin-top:10px}
"""
MODAL_CSS = """
.ss-modal{position:fixed!important;inset:0;z-index:1000;background:rgba(0,0,0,.6);align-items:center!important;
  justify-content:center!important;padding:16px!important;margin:0!important;max-width:none!important}
.ss-dialog{flex:none!important;width:min(640px,100%)!important;background:var(--background-fill-primary)!important;
  border:1px solid var(--border-color-primary)!important;border-radius:12px!important;padding:20px 22px!important;
  box-shadow:0 12px 40px rgba(0,0,0,.5)}
.ss-dialog h3{margin-top:0}
.ss-status:has(span.md:empty){display:none!important}   /* an empty status box takes no room above the results */
.ss-dialog [data-testid=status-tracker]:not(.hide){position:static!important;display:flex!important;flex-direction:column;
  align-items:stretch!important;justify-content:flex-start!important;gap:6px;background:none!important;padding:4px 0 0!important}
.ss-dialog .progress-level{display:flex!important;flex-direction:column;width:100%!important;gap:8px}
.ss-dialog .progress-level-inner{font-family:var(--font)!important;font-size:var(--text-md);font-weight:600;
  text-align:left!important;margin:0!important;color:var(--body-text-color)}
.ss-dialog .progress-bar-wrap{width:100%!important;height:10px!important;border-radius:5px!important;overflow:hidden}
.ss-dialog .progress-bar{border-radius:5px}
.ss-dialog .progress-text{display:none!important}
.ss-dialog .ss-elapsed{font-size:var(--text-sm);color:var(--body-text-color-subdued);text-align:left}
"""
AN_EMPTY = ('<div class="an-card an-empty">Drop a track and press <b>Analyze</b>.<br>'
            'Key, tempo, loudness and chords appear here.</div>')


def analysis_card(name, rows, d, segs, src, want_chords):
    e = html.escape
    g = d["grid"]
    length_sub = " · ".join(x for x in (rows.get("Sample rate", ""), rows.get("Channels", "").lower()) if x)
    tiles = [
        ("Key", rows["Key"], f"{rows['Camelot']} · confidence {d['key_conf']:.2f}"),
        ("Tempo", f"{g['bpm']:.2f} BPM", f"half {g['bpm'] / 2:.2f} · double {g['bpm'] * 2:.2f}"),
        ("Loudness", rows["Loudness"], f"peak {rows['Peak']}"),
        ("Length", rows["Duration"], length_sub),
    ]
    out = f'<div class="an-card"><h3>{e(name)}</h3><div class="an-tiles">'
    out += "".join(f'<div class="an-tile"><div class="l">{l}</div><div class="v">{e(v)}</div><div class="s">{e(s)}</div></div>'
                   for l, v, s in tiles) + "</div>"
    if want_chords:
        prog, usage = chords.summary(segs)
        if prog:
            out += f'<div class="an-sec">Main chord progression</div><div class="an-prog">{e(prog)}</div>'
            out += '<div class="an-sec">Most used</div><div class="an-chips">' + "".join(
                f'<span class="an-chip"><b>{e(c)}</b> {p}%</span>' for c, p in usage) + "</div>"
            out += '<div class="an-sec">Chord changes (bar number, then chord)</div><div class="an-chips">' + "".join(
                f'<span class="an-chip"><i>{s["bar"]}{"" if s["beat"] == 1 else "." + str(s["beat"])}</i><b>{e(s["chord"])}</b></span>'
                for s in segs if s["chord"] != "N" and s["bar"] >= 1) + "</div>"
            out += f'<div class="an-note">Chords read from {e(src)}. Bar 1 is the first downbeat. Treat busy sections as a guide.</div>'
        else:
            out += '<div class="an-note">No clear chords found (the track may be mostly drums or speech).</div>'
    return out + "</div>"


# ---------------- UI ----------------
AUDIO_TYPES = "WAV, MP3, FLAC, OGG, Opus or AIFF"
# Split > MIDI (Optional): a checkbox in front of each choice, and a hint in the empty box.
PICK_CSS = ("#midi-pick li.item .inner-item{display:inline-flex!important;visibility:visible!important;align-items:center;"
            "justify-content:center;width:16px;height:16px;margin-right:10px;border:1.5px solid var(--body-text-color-subdued);"
            "border-radius:4px;font-size:0;flex:0 0 16px;box-sizing:border-box;pointer-events:none}"   # clicks reach the row
            "#midi-pick li.item{cursor:pointer}"
            "#midi-pick li.item[aria-selected=true] .inner-item{background:var(--color-accent);border-color:var(--color-accent)}"
            "#midi-pick li.item[aria-selected=true] .inner-item::after{content:'\\2713';font-size:12px;color:#fff;line-height:1}"
            "#midi-pick li.item{display:flex;align-items:center}")
PICK_HINT = "Choose the stems to make MIDI from"
PICK_JS = """<script>
new MutationObserver(() => document.querySelectorAll('#midi-pick input').forEach(i => {
  const want = document.querySelector('#midi-pick .token') ? '' : '%s';   // hint only while nothing is chosen
  if (i.placeholder !== want) i.placeholder = want;
})).observe(document.documentElement, {childList: true, subtree: true});
// Pop-up progress: Gradio's own counter ("5/36 seconds | 13.3s") is hidden; show the elapsed time as m:ss instead.
setInterval(() => document.querySelectorAll('.ss-dialog [data-testid=status-tracker]').forEach(t => {
  const src = t.querySelector('.progress-text'), m = src && src.textContent.match(/([\\d.]+)s\\s*$/);
  let el = t.querySelector('.ss-elapsed');
  if (!m) { if (el) el.remove(); return; }
  if (!el) { el = document.createElement('div'); el.className = 'ss-elapsed'; t.appendChild(el); }
  const s = Math.floor(parseFloat(m[1]));
  el.textContent = 'Elapsed ' + Math.floor(s / 60) + ':' + String(s %% 60).padStart(2, '0');
}), 250);
</script>""" % PICK_HINT
# One icon per tab, in tab order: Analyze, Split, MIDI, Mix, Shift, Encode (names from engine/icons.py).
TAB_CSS = tab_css(["chart-bar", "stack-3", "piano", "adjustments-horizontal", "plus-minus", "file-export"])
with gr.Blocks(title=APP_NAME) as demo:
    gr.Markdown(f"# {APP_NAME}\nAnalyze music, split it into stems, combine the vocals of one song with the music of another, "
                f"and change key or tempo. Everything runs on this computer. Results are saved in `{OUTPUT_DIR}`.")
    with gr.Row():
        fmt = gr.Dropdown(list(FORMATS), value=DEFAULT_FORMAT, label="Output format and quality (applies to every tab)", scale=2)
        gr.Markdown("**WAV/FLAC** are lossless; FLAC is about half the size of WAV. **MP3** is smallest, but its encoder adds "
                    "a few ms of padding, so use WAV or FLAC for stems you will line up in a DAW. "
                    "Stems are kept at full quality internally, so a smaller export never degrades later work.")
    with gr.Tab("Analyze"):
        with gr.Row():
            with gr.Column(scale=1):
                a_in = gr.Audio(type="filepath", label=f"Track ({AUDIO_TYPES})")
                with gr.Accordion("Tempo range", open=False):
                    a_lo = gr.Slider(40, 120, 70, step=1, label="Lowest BPM")
                    a_hi = gr.Slider(120, 220, 180, step=1, label="Highest BPM")
                    gr.Markdown("If a track reads at half or double its real speed, narrow this range to where you expect it, "
                                "e.g. 60–90 for a ballad or 160–180 for drum & bass.")
                a_chords = gr.Checkbox(True, label="Detect chords",
                                       info="Lists the chords bar by bar and saves them as a MIDI file.")
                a_novox = gr.Checkbox(False, label="Remove vocals first (cleaner chords)",
                                      info="Adds a stem split (about a minute or two on a CPU, then reused by every tab). "
                                           "Not needed if you have already split this song.")
                a_btn = gr.Button("Analyze", variant="primary")
            with gr.Column(scale=1):
                a_status = gr.Markdown(elem_classes="ss-status")
                a_prog = progress_area()
                a_card = gr.HTML(AN_EMPTY)
                a_mid = gr.File(label="Chords as MIDI", interactive=False, visible=False)
                with gr.Accordion("All details", open=False, visible=False) as a_more:
                    a_out = gr.Dataframe(headers=["Property", "Value"], interactive=False, wrap=True)
        run_button(a_btn, "Analyze", start_analyze, [a_in, a_chords, a_novox], [], do_analyze,
                   [a_in, a_lo, a_hi, a_chords, a_novox], [a_card, a_mid, a_out, a_more, a_status], a_status, a_prog)
        done_popup("Open MIDI folder", found_analysis, [a_in], [a_in])

    with gr.Tab("Split"):
        s_folder = gr.State(OUTPUT_DIR)
        with gr.Row():
            with gr.Column(scale=1):
                s_in = gr.Audio(type="filepath", label=f"Track ({AUDIO_TYPES})")
                s_model = gr.Dropdown(list(sep.MODELS), value=list(sep.MODELS)[0], label="Model")
                s_midi = gr.Dropdown(list(MIDI_STEMS), value=[], multiselect=True, label="MIDI (Optional)", elem_id="midi-pick")
                gr.Markdown(f"Running on **{sep.device().upper()}**. On a CPU, expect roughly a minute or two per song for Balanced "
                            "and four times that for Best quality. An instrumental (everything except the vocals) is always included.")
                s_btn = gr.Button("Separate", variant="primary")
                s_open = gr.Button("Open stems folder")
            with gr.Column(scale=1):
                s_outs = [gr.Audio(label=STEM_TITLES[s], visible=False, type="filepath", interactive=False) for s in STEM_ORDER]
                s_midi_files = gr.File(label="MIDI files", file_count="multiple", interactive=False, visible=False)
        # Pop-up window: progress while separating, then a confirmation with the result.
        with gr.Column(visible=False, elem_classes="ss-modal") as s_modal:
            with gr.Column(elem_classes="ss-dialog"):
                s_status = gr.Markdown(min_height=72)
                s_prog = progress_area()
                with gr.Row(visible=False) as s_actions:
                    s_mopen = gr.Button("Open stems folder", variant="primary")
                    s_mclose = gr.Button("Close")

        def s_start(path, model_label):
            return start_separate(path, model_label) + (gr.update(visible=True), gr.update(visible=False))

        def s_end(status):
            return finished("Separate")(status) + (gr.update(visible=True),)

        s_btn.click(s_start, [s_in, s_model], [s_btn, s_status, s_prog] + s_outs + [s_midi_files, s_modal, s_actions],
                    concurrency_limit=None, show_progress="hidden") \
             .success(do_separate, [s_in, s_model, s_midi, fmt], s_outs + [s_midi_files, s_status, s_folder],
                      show_progress_on=[s_prog]) \
             .then(s_end, s_status, [s_btn, s_status, s_prog, s_actions], concurrency_limit=None, show_progress="hidden")
        s_in.change(check_already_split, [s_in, s_model], [s_status, s_prog, s_actions, s_modal, s_folder],
                    show_progress="hidden")
        s_open.click(open_folder, s_folder, None)
        s_mopen.click(open_folder, s_folder, None)
        s_mclose.click(lambda: gr.update(visible=False), None, s_modal, show_progress="hidden")

    with gr.Tab("MIDI"):
        x_folder = gr.State(OUTPUT_DIR)
        with gr.Row():
            with gr.Column(scale=1):
                x_in = gr.Audio(type="filepath", label=f"Recording ({AUDIO_TYPES})")
                x_src = gr.Radio(MIDI_SOURCE, value=MIDI_SOURCE[0], label="What is this file?")
                x_part = gr.Dropdown(list(midi.PARTS), value="Vocals / lead melody", label="Part to turn into MIDI")
                with gr.Accordion("Fine-tune", open=False):
                    x_sens = gr.Slider(0, 1, 0.5, step=0.05, label="Sensitivity",
                                       info="Higher finds quieter notes and hits, but also more mistakes")
                    x_min = gr.Slider(30, 300, 80, step=10, label="Shortest note (ms)", info="Ignored for drums")
                    x_snap = gr.Dropdown(list(midi.SNAP), value=list(midi.SNAP)[0], label="Snap to the beat grid")
                gr.Markdown("Works best on one clear part: a vocal, a bass line, a piano or a drum loop. For a whole song, choose "
                            "**A full song** and the part is separated out first (the separation is reused next time). "
                            "Chords from a busy mix give many overlapping notes; use them as a starting point. "
                            "Drums are written as General MIDI kick (C1), snare/clap (D1) and closed hi-hat (F#1).")
                x_btn = gr.Button("Make MIDI", variant="primary")
                x_open = gr.Button("Open MIDI folder")
            with gr.Column(scale=1):
                x_info = gr.Markdown(elem_classes="ss-status")
                x_prog = progress_area()
                x_file = gr.File(label="MIDI file", interactive=False)
                x_prev = gr.Audio(label="Preview (the MIDI played by a simple synth)", type="filepath", interactive=False)
                x_roll = gr.Image(label="Piano roll", type="pil", interactive=False)
        run_button(x_btn, "Make MIDI", start_midi, [x_in, x_part, x_src], [],
                   do_midi, [x_in, x_part, x_src, x_sens, x_min, x_snap], [x_file, x_prev, x_roll, x_info, x_folder], x_info, x_prog)
        x_open.click(open_folder, x_folder, None)
        done_popup("Open MIDI folder", found_midi, [x_in], [x_in])

    with gr.Tab("Mix"):
        m_folder = gr.State(OUTPUT_DIR)
        with gr.Row():
            with gr.Column(scale=1):
                m_voc = gr.Audio(type="filepath", label="Take the vocals from")
                m_ins = gr.Audio(type="filepath", label="Put them over the music of")
                m_arr = gr.Radio(ARRANGE, value=ARRANGE[0], label="Arrangement")
                m_key = gr.Dropdown(["Auto"] + [f"{i:+d}" for i in range(-6, 7)], value="Auto",
                                    label="Vocal key shift in semitones (Auto matches the instrumental's key)")
                m_gain = gr.Slider(-12, 12, 0, step=0.5, label="Vocal level (dB)")
                m_model = gr.Dropdown(list(sep.MODELS)[:2], value=list(sep.MODELS)[0], label="Separation model")
                m_btn = gr.Button("Make mashup", variant="primary")
                m_open = gr.Button("Open mashup folder")
            with gr.Column(scale=1):
                m_out = gr.Audio(label="Mashup", type="filepath", interactive=False)
                m_rep = gr.Markdown(elem_classes="ss-status")
                m_prog = progress_area()
        run_button(m_btn, "Make mashup", start_mashup, [m_voc, m_ins, m_model], [],
                   do_mashup, [m_voc, m_ins, m_arr, m_key, m_gain, m_model, fmt], [m_out, m_rep, m_folder], m_rep, m_prog)
        m_open.click(open_folder, m_folder, None)
        done_popup("Open mashup folder", found_mashup, [m_voc, m_ins], [m_voc, m_ins])

    with gr.Tab("Shift"):
        t_folder = gr.State(OUTPUT_DIR)
        with gr.Row():
            with gr.Column(scale=1):
                t_in = gr.Audio(type="filepath", label=f"Track ({AUDIO_TYPES})")
                t_semi = gr.Slider(-12, 12, 0, step=1, label="Key shift (semitones)")
                t_bpm = gr.Number(value=0, label="Target BPM (0 = keep the tempo; the current tempo is detected for you)")
                t_btn = gr.Button("Render", variant="primary")
                t_open = gr.Button("Open folder")
            with gr.Column(scale=1):
                t_out = gr.Audio(label="Result", type="filepath", interactive=False)
                t_info = gr.Markdown(elem_classes="ss-status")
                t_prog = progress_area()
        run_button(t_btn, "Render", start_transform, [t_in, t_semi, t_bpm], [],
                   do_transform, [t_in, t_semi, t_bpm, fmt], [t_out, t_info, t_folder], t_info, t_prog)
        t_open.click(open_folder, t_folder, None)
        done_popup("Open folder", found_shift, [t_in], [t_in])

    with gr.Tab("Encode"):
        c_folder = gr.State(os.path.join(OUTPUT_DIR, "Converted"))
        with gr.Row():
            with gr.Column(scale=1):
                c_in = gr.File(file_count="multiple", label=f"Audio files ({AUDIO_TYPES}); add as many as you like",
                               file_types=[".wav", ".mp3", ".flac", ".ogg", ".opus", ".aif", ".aiff"], type="filepath")
                c_mode = gr.Radio(CONVERT_MODES, value=CONVERT_MODES[0], label="What to do")
                c_fmt = gr.Dropdown(list(conv.FORMATS), value="MP3 · 320 kbps", label="Output format and quality")
                with gr.Row(visible=False) as c_target_row:
                    c_mb = gr.Number(value=8, minimum=0.1, label="Target size per file (MB)")
                    c_codec = gr.Dropdown(conv.TARGET_CODECS, value=conv.TARGET_CODECS[0], label="Encode as")
                with gr.Accordion("Make it smaller still", open=False):
                    c_rate = gr.Dropdown(list(conv.SAMPLE_RATES), value="Keep original", label="Sample rate")
                    c_ch = gr.Radio(conv.CHANNELS, value=conv.CHANNELS[0], label="Channels")
                gr.Markdown("Lossless (WAV, AIFF, FLAC) keeps every detail; FLAC is about half the size of WAV. MP3, Opus and "
                            "Ogg are much smaller: 320 kbps MP3 is about 2.4 MB per minute, 128 kbps about 1 MB. "
                            "Opus sounds best at low bitrates but older players may not open it. "
                            "Tags such as artist and cover art are not copied. This tab ignores the format at the top.")
                c_btn = gr.Button("Convert", variant="primary")
                c_open = gr.Button("Open converted folder")
            with gr.Column(scale=1):
                c_files = gr.File(label="Converted files", file_count="multiple", interactive=False)
                c_status = gr.Markdown(elem_classes="ss-status")
                c_prog = progress_area()
                c_table = gr.Dataframe(headers=["File", "Now", "Audio", "Before", "After", "Change", "Saved as"],
                                       label="Before and after", show_label=True, interactive=False, wrap=True,
                                       visible=False)
        c_mode.change(lambda m: (gr.update(visible=m == CONVERT_MODES[0]), gr.update(visible=m == CONVERT_MODES[1])),
                      c_mode, [c_fmt, c_target_row])
        run_button(c_btn, "Convert", start_convert, [c_in], [],
                   do_convert, [c_in, c_mode, c_fmt, c_mb, c_codec, c_rate, c_ch], [c_table, c_files, c_status, c_folder], c_status, c_prog)
        c_open.click(open_folder, c_folder, None)
        done_popup("Open converted folder", found_converted, [c_in], [c_in])

    gr.Markdown(f"{APP_NAME} {APP_VERSION} · Only release stems, mashups or edits of music you have the rights to.")


def launch(port, open_browser=False, block=True):
    return demo.queue(default_concurrency_limit=1).launch(
        server_name="127.0.0.1", server_port=port, inbrowser=open_browser, prevent_thread_lock=not block,
        allowed_paths=[OUTPUT_DIR], quiet=not block, footer_links=[], css=TAB_CSS + PICK_CSS + AN_CSS + MODAL_CSS, head=PICK_JS)


def already_running(port=7860):
    import socket
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


if __name__ == "__main__":   # browser mode
    if already_running():
        import webbrowser
        print(f"{APP_NAME} is already running - opening it in your browser.")
        webbrowser.open("http://127.0.0.1:7860")
        sys.exit(0)
    launch(7860, open_browser="--no-browser" not in sys.argv)
