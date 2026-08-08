"""
Shared helpers for all workshop tools.

Every tool imports from here. Keep this file small — it only knows how to:
  - find ffmpeg/ffprobe on Mac and Windows
  - make a file path safe for use inside an ffmpeg filter argument
  - run subprocesses with UTF-8 output (Thai text in ffmpeg stderr is normal)
  - load the .env file (GROQ_API_KEY)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = REPO_ROOT / "assets" / "fonts"
OUTPUTS_DIR = REPO_ROOT / "outputs"
FOOTAGE_DIR = REPO_ROOT / "footage"


def setup_console() -> None:
    """Force UTF-8 console output so Thai text prints on Windows (cp1252 default)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _windows_extra_dirs() -> list[Path]:
    """Places winget puts ffmpeg that may not be on PATH in the current shell."""
    dirs: list[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(Path(local) / "Microsoft" / "WinGet" / "Links")
        pkgs = Path(local) / "Microsoft" / "WinGet" / "Packages"
        if pkgs.is_dir():
            for pkg in pkgs.glob("Gyan.FFmpeg*"):
                dirs.extend(pkg.glob("ffmpeg-*/bin"))
    return dirs


def _candidates(name: str) -> list[str]:
    """All places the binary might live, in preference order, deduplicated."""
    found: list[str] = []
    exe = shutil.which(name)
    if exe:
        found.append(exe)
    if sys.platform == "win32":
        extra = _windows_extra_dirs()
        suffix = f"{name}.exe"
    else:
        extra = [
            Path("/opt/homebrew/opt/ffmpeg-full/bin"),  # full build first on Mac
            Path("/opt/homebrew/bin"),
            Path("/usr/local/bin"),
        ]
        suffix = name
    for d in extra:
        cand = d / suffix
        if cand.exists():
            found.append(str(cand))
    seen: set[str] = set()
    return [f for f in found if not (f in seen or seen.add(f))]


def _has_subtitles_filter(ffmpeg: str) -> bool:
    try:
        r = subprocess.run(
            [ffmpeg, "-hide_banner", "-filters"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=15,
        )
        return r.returncode == 0 and " subtitles " in r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


_FFMPEG_CACHE: dict[str, str] = {}


def get_ffmpeg() -> str:
    """Return an ffmpeg binary, preferring a build that can burn subtitles
    (libass). Some machines have several ffmpeg builds and the one on PATH
    may be a slim build without the subtitles filter."""
    if "ffmpeg" in _FFMPEG_CACHE:
        return _FFMPEG_CACHE["ffmpeg"]
    cands = _candidates("ffmpeg")
    if not cands:
        raise RuntimeError(
            "ffmpeg not found. Install it first:\n"
            "  Mac:     brew install ffmpeg\n"
            "  Windows: winget install Gyan.FFmpeg\n"
            "then open a NEW terminal window so PATH updates apply.\n"
            "(Do NOT install imageio-ffmpeg / 'python ffmpeg' — that build "
            "cannot burn subtitles.)"
        )
    chosen = next((c for c in cands if _has_subtitles_filter(c)), cands[0])
    _FFMPEG_CACHE["ffmpeg"] = chosen
    return chosen


def get_ffprobe() -> str:
    cands = _candidates("ffprobe")
    if cands:
        return cands[0]
    raise RuntimeError(
        "ffprobe not found (it ships with ffmpeg). Install ffmpeg:\n"
        "  Mac:     brew install ffmpeg\n"
        "  Windows: winget install Gyan.FFmpeg\n"
        "then open a NEW terminal window."
    )


def filter_path(p: Path | str) -> str:
    """
    Make a path safe for use inside an ffmpeg filter argument
    (subtitles=filename=..., fontsdir=...).

    Windows backslashes confuse the filter parser even when escaped, so we
    convert to forward slashes FIRST (ffmpeg accepts them on all platforms),
    then escape the drive-colon and any quotes.
    """
    posix = Path(p).resolve().as_posix()
    return posix.replace(":", r"\:").replace("'", r"\'")


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """subprocess.run with UTF-8 capture (ffmpeg stderr may contain Thai)."""
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("encoding", "utf-8")
    kwargs.setdefault("errors", "replace")
    return subprocess.run(cmd, **kwargs)


def write_json_atomic(path: Path, doc: dict) -> None:
    """Write JSON atomically (temp file + rename) — required by the ButaCut
    edit-contract so the UI never sees a half-written file."""
    import json
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def read_json_tolerant(path: Path) -> dict | None:
    """Read JSON, returning None on missing/invalid/mid-write files."""
    import json
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, ValueError):
        return None


def edit_sidecar(video: Path) -> Path:
    """The ButaCut edit.json sidecar path for a video (same dir, same stem)."""
    return video.with_name(video.stem + ".edit.json")


def load_env() -> None:
    """Load .env from the repo root. Works even if python-dotenv is missing."""
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / ".env")
        return
    except ImportError:
        pass
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
