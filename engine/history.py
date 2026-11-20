"""Finds results from earlier runs, so the app can say "done before" and offer the folder instead of redoing the work.
Each check -> dict(title, body (Markdown), folder) when something exists, else None."""
import os, time
from .common import output_root, track_name
from . import separate as sep

AUDIO_EXTS = (".wav", ".flac", ".mp3", ".ogg", ".opus", ".aif", ".aiff")


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


def _found(title, body, folder):
    return dict(title=title, body=body, folder=folder)


def split(path, model_label=None):
    if not path: return None
    found = []
    for label, m in sep.MODELS.items():
        d = sep.stem_dir(path, m)
        if _files(d, lambda f: f.lower().endswith(AUDIO_EXTS)): found.append((label, d))
    if not found: return None
    found.sort(key=lambda x: x[0] != model_label)          # the selected model's folder first
    folder = found[0][1]
    names = [l.split(":")[0] for l, _ in found]
    which = names[0] + " model" if len(names) == 1 else _list(names) + " models"
    return _found("Already Split",
                  f"**{track_name(path)}** was split before with the {which}, last on {_when(folder)}. "
                  f"The stems are in `{folder}`.\n\nPress **Start** again only to export in another format or to add MIDI.",
                  folder)


def analysis(path):
    if not path: return None
    name = track_name(path)
    mid = os.path.join(output_root(), name, "MIDI", f"{name} - Chords.mid")
    if not os.path.exists(mid): return None
    return _found("Analyzed Before",
                  f"The chords of **{name}** were saved on {_when(mid)} in `{os.path.dirname(mid)}`.\n\n"
                  "Key, tempo and loudness aren't saved, so press **Start** to see them again.", os.path.dirname(mid))


def midi(path):
    if not path: return None
    name = track_name(path)
    folder = os.path.join(output_root(), name, "MIDI")
    mids = _files(folder, lambda f: f.lower().endswith(".mid"))
    if not mids: return None
    parts = [os.path.splitext(os.path.basename(m))[0].removeprefix(f"{name} - ") for m in mids]
    return _found("MIDI Made Before",
                  f"**{name}** already has MIDI for {_list(parts)}, latest on {_when(mids[0])}, in `{folder}`.\n\n"
                  "Press **Start** again for another part or other settings. Making the same part again replaces its file.",
                  folder)


def mashup(vpath, ipath):
    if not (vpath and ipath): return None
    title = f"{track_name(vpath)} x {track_name(ipath)}"
    folder = os.path.join(output_root(), "Mashups", title)
    outs = _files(folder, lambda f: f.lower().endswith(AUDIO_EXTS))
    if not outs: return None
    return _found("Mashup Made Before",
                  f"**{title}** was made on {_when(outs[0])}, in `{folder}`.\n\n"
                  "Press **Start** again to remake it with other settings. It replaces the earlier files.", folder)


def shift(path):
    if not path: return None
    name = track_name(path)
    folder = os.path.join(output_root(), name)
    outs = _files(folder, lambda f: f.startswith(f"{name} (") and f.lower().endswith(AUDIO_EXTS))
    if not outs: return None
    tags = list(dict.fromkeys(os.path.splitext(os.path.basename(o))[0][len(name) + 2:-1] for o in outs))
    return _found("Shifted Before",
                  f"**{name}** already has {'a version' if len(tags) == 1 else 'versions'} at {_list(tags)}, "
                  f"latest on {_when(outs[0])}, in `{folder}`.\n\nRendering the same settings again replaces that file.",
                  folder)


def converted(paths):
    if not paths: return None
    folder = os.path.join(output_root(), "Converted")
    stems = {os.path.splitext(os.path.basename(h))[0] for h in _files(folder)}
    done = []
    for p in paths:
        n = track_name(p)
        if n in stems or any(s.startswith(f"{n} (") and s[len(n) + 2:-1].isdigit() for s in stems): done.append(n)
    if not done: return None
    head = (f"**{done[0]}** is" if len(paths) == 1 else
            f"{len(done)} of these {len(paths)} files {'is' if len(done) == 1 else 'are'}")
    return _found("Converted Before",
                  f"{head} already in `{folder}`{'' if len(paths) == 1 else ': ' + _list(done)}.\n\n"
                  "Converting again saves a new numbered copy; it doesn't replace the old one.", folder)
