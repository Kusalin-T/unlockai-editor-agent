"""
ButaCut server — portable, stdlib-only. Works on macOS and Windows, py3.8+.

Run from anywhere:
    python serve.py            (or: python butacut/serve.py from a repo root)

Config (optional): butacut.config.json in the current working directory, else
next to this file:
    { "media_dirs": [".", "media"], "port": 8766,
      "render_cmd": ["python", "tools/render.py", "--edit", "{edit}", "--out", "{output}"] }

Contract for edit sidecars and renderers: see edit-contract.md (same folder).
The server never assumes it is the only writer of *.edit.json — files are
re-read on demand, written atomically, and invalid/mid-write JSON is reported
to the UI as a transient state, never a crash.
"""

import glob
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

try:  # utf-8 console on Windows (cp1252 default would die on Thai in JSON logs)
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

HERE = Path(__file__).resolve().parent
VIDEO_EXTS = {".mp4", ".mov", ".m4v"}
DEFAULT_CONFIG = {"media_dirs": [".", "media"], "port": 8766, "render_cmd": None}

_jobs = {}
_locks = {}
_locks_guard = threading.Lock()
_duration_cache = {}


def _lock_for(key):
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


# ------------------------------------------------------------------ config

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    for candidate in (Path.cwd() / "butacut.config.json", HERE / "butacut.config.json"):
        if candidate.exists():
            try:
                cfg.update(json.loads(candidate.read_text(encoding="utf-8")))
                cfg["_config_path"] = str(candidate)
                break
            except (json.JSONDecodeError, OSError) as exc:
                print("WARN: cannot read %s: %s" % (candidate, exc))
    return cfg


CONFIG = load_config()
ROOT = Path.cwd().resolve()
CACHE_DIR = HERE / "cache"


def media_dirs():
    out = []
    for entry in CONFIG.get("media_dirs", ["."]):
        for hit in sorted(glob.glob(str((ROOT / entry)))) or [str(ROOT / entry)]:
            p = Path(hit)
            if p.is_dir() and p not in out:
                out.append(p)
    return out


# ------------------------------------------------------------------ ffmpeg

def _find_tool(name):
    hit = None
    try:
        import shutil
        hit = shutil.which(name)
    except ImportError:
        pass
    if hit:
        return hit
    exe = name + (".exe" if os.name == "nt" else "")
    candidates = []
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", "")
        candidates += [
            Path(local) / "Microsoft" / "WinGet" / "Links" / exe,
            Path("C:/ffmpeg/bin") / exe,
        ]
    else:
        candidates += [Path("/opt/homebrew/bin") / exe, Path("/usr/local/bin") / exe]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


FFMPEG = _find_tool("ffmpeg")
FFPROBE = _find_tool("ffprobe")


def get_duration(video):
    key = (str(video), video.stat().st_mtime)
    if key in _duration_cache:
        return _duration_cache[key]
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=True).stdout.strip()
    dur = float(out)
    _duration_cache[key] = dur
    return dur


# ------------------------------------------------------------------ edits

def edit_path(video):
    return video.with_name(video.stem + ".edit.json")


def boundaries_path(video):
    return video.with_name(video.stem + ".boundaries.json")


def read_json_tolerant(path):
    """Return (doc, valid). Invalid/missing/mid-write -> (None, False/True)."""
    if not path.exists():
        return None, True
    try:
        return json.loads(path.read_text(encoding="utf-8")), True
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None, False


def normalize_keeps(keeps, duration):
    ks = []
    for k in keeps or []:
        try:
            a, b = float(k["in"]), float(k["out"])
        except (KeyError, TypeError, ValueError):
            continue
        a, b = max(0.0, min(a, duration)), max(0.0, min(b, duration))
        if b - a >= 0.05:
            ks.append({"in": a, "out": b, "origin": k.get("origin", "agent")})
    ks.sort(key=lambda k: k["in"])
    merged = []
    for k in ks:
        if merged and k["in"] <= merged[-1]["out"] + 0.001:
            merged[-1]["out"] = max(merged[-1]["out"], k["out"])
        else:
            merged.append(k)
    return merged


def load_edit(video, duration):
    """Return (edit_doc_with_normalized_keeps, mtime, valid)."""
    p = edit_path(video)
    doc, valid = read_json_tolerant(p)
    mtime = p.stat().st_mtime if p.exists() else 0
    if doc is None:
        return None, mtime, valid
    if "keeps" not in doc and "drops" in doc:  # legacy drops format
        keeps, cursor = [], 0.0
        for d in sorted(doc.get("drops", [])):
            if d[0] > cursor:
                keeps.append({"in": cursor, "out": float(d[0]), "origin": "user"})
            cursor = max(cursor, float(d[1]))
        if cursor < duration:
            keeps.append({"in": cursor, "out": duration, "origin": "user"})
        doc["keeps"] = keeps
    doc["keeps"] = normalize_keeps(doc.get("keeps"), duration)
    doc.setdefault("text", [])
    doc.setdefault("sfx", [])
    return doc, mtime, valid


def save_keeps(video, keeps, duration):
    """Merge new keeps into the on-disk doc (preserving text/sfx from other
    writers), write atomically, return new mtime."""
    p = edit_path(video)
    doc, _valid = read_json_tolerant(p)
    if not isinstance(doc, dict):
        doc = {}
    doc["version"] = 1
    doc["video"] = video.name
    doc["keeps"] = [
        {"in": round(float(k["in"]), 3), "out": round(float(k["out"]), 3),
         "origin": k.get("origin", "user")}
        for k in normalize_keeps(keeps, duration)]
    doc.setdefault("text", [])
    doc.setdefault("sfx", [])
    doc["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    doc["by"] = "butacut-ui"
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    return p.stat().st_mtime


# ------------------------------------------------------------------ discovery

def discover_videos():
    out, seen = [], set()
    for d in media_dirs():
        for f in sorted(d.iterdir()):
            if f.suffix.lower() not in VIDEO_EXTS or f.stem.endswith("-cut"):
                continue
            rp = f.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            try:
                dur = get_duration(f)
            except (subprocess.CalledProcessError, ValueError, OSError):
                continue
            edit, _m, _v = load_edit(f, dur)
            keeps = edit["keeps"] if edit else []
            kept = sum(k["out"] - k["in"] for k in keeps) if keeps else dur
            rel = os.path.relpath(str(f), str(ROOT))
            out.append({
                "id": Path(rel).as_posix(),
                "name": f.stem,
                "dir": Path(rel).parent.as_posix(),
                "duration": dur,
                "kept": round(kept, 3),
                "has_edit": edit_path(f).exists(),
                "has_boundaries": boundaries_path(f).exists(),
                "cut_exists": f.with_name(f.stem + "-cut.mp4").exists(),
            })
    return out


def resolve_id(vid):
    p = (ROOT / vid).resolve()
    ok = any(str(p).startswith(str(d.resolve()) + os.sep) or p.parent == d.resolve()
             for d in media_dirs())
    if not ok or p.suffix.lower() not in VIDEO_EXTS or not p.exists():
        raise FileNotFoundError(vid)
    return p


# ------------------------------------------------------------------ peaks / strip

def _cache_file(video, kind, ext):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = str(video.resolve()).replace(os.sep, "__").replace(":", "")
    return CACHE_DIR / ("%s.%s.%s" % (safe[-140:], kind, ext))


def get_peaks(video):
    out = _cache_file(video, "peaks", "json")
    with _lock_for(str(out)):
        if out.exists() and out.stat().st_mtime >= video.stat().st_mtime:
            return out
        proc = subprocess.run(
            [FFMPEG, "-v", "error", "-i", str(video),
             "-ac", "1", "-ar", "4000", "-f", "s16le", "-"],
            capture_output=True, check=True)
        from array import array
        samples = array("h")
        raw = proc.stdout
        samples.frombytes(raw[: len(raw) // 2 * 2])
        peaks = []
        for i in range(0, len(samples), 200):
            chunk = samples[i:i + 200]
            peaks.append(round(max(abs(x) for x in chunk) / 32768.0, 3) if len(chunk) else 0)
        out.write_text(json.dumps({"buckets_per_sec": 20, "peaks": peaks}))
        return out


def get_strip(video):
    out = _cache_file(video, "strip", "jpg")
    with _lock_for(str(out)):
        if out.exists() and out.stat().st_mtime >= video.stat().st_mtime:
            return out
        dur = max(0.5, get_duration(video))
        count = max(20, min(120, int(dur)))
        subprocess.run(
            [FFMPEG, "-v", "error", "-y", "-i", str(video),
             "-vf", "fps=%.6f,scale=-2:54,tile=%dx1" % (count / dur, count),
             "-frames:v", "1", "-q:v", "5", str(out)],
            capture_output=True, check=True)
        return out


# ------------------------------------------------------------------ render

def builtin_render(video, keeps, output, fps):
    """Concat the keep ranges, re-encoded CFR — same trim+concat shape as the
    production pipeline, implemented standalone."""
    parts, maps = [], []
    for i, k in enumerate(keeps):
        parts.append(
            "[0:v]trim=start=%.3f:end=%.3f,setpts=PTS-STARTPTS[v%d];"
            "[0:a]atrim=start=%.3f:end=%.3f,asetpts=PTS-STARTPTS[a%d]"
            % (k["in"], k["out"], i, k["in"], k["out"], i))
        maps.append("[v%d][a%d]" % (i, i))
    fc = ";".join(parts) + (";%sconcat=n=%d:v=1:a=1[v][a]" % ("".join(maps), len(keeps)))
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-i", str(video), "-filter_complex", fc,
         "-map", "[v]", "-map", "[a]", "-r", str(fps),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output)],
        capture_output=True, check=True, text=True)


def _shift_time(t, drops):
    offset = 0.0
    for s, e in drops:
        if t >= e:
            offset += e - s
        elif t > s:
            return s - offset
        else:
            break
    return t - offset


def remap_boundaries(video, keeps, output, new_dur):
    """If a production boundaries sidecar exists, write a remapped one for the cut."""
    doc, valid = read_json_tolerant(boundaries_path(video))
    if not doc or not valid:
        return
    dur = get_duration(video)
    drops, cursor = [], 0.0
    for k in keeps:
        if k["in"] > cursor:
            drops.append((cursor, k["in"]))
        cursor = max(cursor, k["out"])
    if cursor < dur:
        drops.append((cursor, dur))
    clips = []
    for c in doc.get("clips", []):
        ns, ne = _shift_time(float(c["start"]), drops), _shift_time(float(c["end"]), drops)
        if ne - ns > 0.05:
            clips.append({"source": c["source"], "start": round(ns, 3), "end": round(ne, 3)})
    boundaries_path(output).write_text(json.dumps(
        {"video": output.name, "duration": round(new_dur, 3), "clips": clips},
        ensure_ascii=False, indent=2))


def _apply_job(vid, video):
    try:
        dur = get_duration(video)
        edit, _m, valid = load_edit(video, dur)
        if not edit or not valid:
            raise ValueError("edit.json missing or invalid")
        keeps = edit["keeps"]
        if not keeps:
            raise ValueError("no keeps in edit.json")
        output = video.with_name(video.stem + "-cut.mp4")
        cmd = CONFIG.get("render_cmd")
        if cmd:
            final = [str(a).replace("{video}", str(video))
                     .replace("{edit}", str(edit_path(video)))
                     .replace("{output}", str(output)) for a in cmd]
            proc = subprocess.run(final, capture_output=True, text=True)
            if proc.returncode != 0:
                raise RuntimeError((proc.stderr or proc.stdout or "renderer failed")[-400:])
        else:
            builtin_render(video, keeps, output, int(edit.get("fps", 24)))
        new_dur = get_duration(output)
        remap_boundaries(video, keeps, output, new_dur)
        _jobs[vid] = {"status": "done",
                      "output": Path(os.path.relpath(str(output), str(ROOT))).as_posix(),
                      "duration": new_dur,
                      "renderer": "custom" if cmd else "built-in",
                      "note": "built-in render is cuts-only (text/sfx ignored)" if not cmd else ""}
    except subprocess.CalledProcessError as exc:
        _jobs[vid] = {"status": "error",
                      "error": (exc.stderr or str(exc))[-400:] if hasattr(exc, "stderr") else str(exc)}
    except Exception as exc:
        _jobs[vid] = {"status": "error", "error": str(exc)}


# ------------------------------------------------------------------ handler

CTYPES = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, ctype, cache=False):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if cache:
            self.send_header("Cache-Control", "max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    def _qs(self):
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    def _range_file(self, path):
        size = path.stat().st_size
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng and rng.startswith("bytes="):
            part = rng.split("=", 1)[1].split(",")[0].strip()
            s, _, e = part.partition("-")
            if s:
                start = int(s)
                end = int(e) if e else size - 1
            elif e:
                start = max(0, size - int(e))
            end = min(end, size - 1)
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */%d" % size)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        length = end - start + 1
        self.send_response(206 if rng else 200)
        self.send_header("Content-Type", CTYPES.get(path.suffix.lower(), "video/mp4"))
        self.send_header("Accept-Ranges", "bytes")
        if rng:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.send_header("Content-Length", str(length))
        self.end_headers()
        with path.open("rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(1024 * 512, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    return
                remaining -= len(chunk)

    def do_GET(self):
        try:
            route = urlparse(self.path).path
            if route in ("/", "/index.html"):
                self._file(HERE / "app.html", "text/html; charset=utf-8")
            elif route == "/api/videos":
                self._json(discover_videos())
            elif route == "/api/config":
                self._json({"renderer": "custom" if CONFIG.get("render_cmd") else "built-in"})
            elif route == "/api/video":
                video = resolve_id(self._qs()["id"])
                dur = get_duration(video)
                edit, mtime, valid = load_edit(video, dur)
                bdoc, _bvalid = read_json_tolerant(boundaries_path(video))
                self._json({
                    "id": Path(os.path.relpath(str(video), str(ROOT))).as_posix(),
                    "duration": dur,
                    "edit": edit, "edit_mtime": mtime, "edit_valid": valid,
                    "clips": (bdoc or {}).get("clips", []),
                })
            elif route == "/api/poll":
                video = resolve_id(self._qs()["id"])
                p = edit_path(video)
                mtime = p.stat().st_mtime if p.exists() else 0
                _doc, valid = read_json_tolerant(p)
                self._json({"mtime": mtime, "valid": valid})
            elif route == "/api/peaks":
                self._file(get_peaks(resolve_id(self._qs()["id"])), "application/json", cache=True)
            elif route == "/api/strip":
                self._file(get_strip(resolve_id(self._qs()["id"])), "image/jpeg", cache=True)
            elif route == "/api/applystatus":
                self._json(_jobs.get(self._qs().get("id", ""), {"status": "idle"}))
            elif route.startswith("/media/"):
                self._range_file(resolve_id(unquote(route[len("/media/"):])))
            else:
                self._json({"error": "not found"}, 404)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            self._json({"error": str(exc)}, 404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_POST(self):
        try:
            route = urlparse(self.path).path
            body = self._body()
            if route == "/api/edit":
                video = resolve_id(body["id"])
                mtime = save_keeps(video, body.get("keeps", []), get_duration(video))
                self._json({"ok": True, "saved": time.strftime("%H:%M:%S"), "mtime": mtime})
            elif route == "/api/apply":
                vid = body["id"]
                video = resolve_id(vid)
                if _jobs.get(vid, {}).get("status") == "running":
                    self._json({"error": "already running"}, 409)
                    return
                _jobs[vid] = {"status": "running", "started": time.time()}
                threading.Thread(target=_apply_job, args=(vid, video), daemon=True).start()
                self._json({"ok": True, "status": "running"})
            else:
                self._json({"error": "not found"}, 404)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            self._json({"error": str(exc)}, 400)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


def main():
    if not FFMPEG or not FFPROBE:
        print("ERROR: ffmpeg/ffprobe not found.")
        print("  macOS:   brew install ffmpeg")
        print("  Windows: winget install ffmpeg   (then restart the terminal)")
        sys.exit(1)
    port = int(CONFIG.get("port", 8766))
    try:
        vids = discover_videos()
    except Exception as exc:
        vids = []
        print("WARN: discovery failed: %s" % exc)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("ButaCut  http://127.0.0.1:%d" % port)
    print("  python: %s" % sys.executable)
    print("  ffmpeg: %s" % FFMPEG)
    print("  media dirs: %s" % ", ".join(str(d) for d in media_dirs()))
    print("  videos found: %d" % len(vids))
    print("  renderer: %s" % ("custom render_cmd" if CONFIG.get("render_cmd") else "built-in (cuts only)"))
    server.serve_forever()


if __name__ == "__main__":
    main()
