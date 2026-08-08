"""
Check that this machine is ready for the workshop.

Run it any time something misbehaves:
    python tools/verify_setup.py

Prints one PASS/FAIL line per check and finishes with READY (or NOT READY
plus what to fix). The final check actually burns a 3-second Thai subtitle
onto the sample video — if that passes, everything real works.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (
    FONTS_DIR,
    FOOTAGE_DIR,
    OUTPUTS_DIR,
    REPO_ROOT,
    get_ffmpeg,
    get_ffprobe,
    load_env,
    run,
    setup_console,
)

SAMPLE = FOOTAGE_DIR / "sample-talk.mp4"
FONT_FILES = [
    "NotoSansThai-Regular.ttf",
    "NotoSansThai-Bold.ttf",
    "NotoSans-Regular.ttf",
    "NotoSans-Bold.ttf",
]

hard_failures: list[str] = []
warnings: list[str] = []


def ok(label: str, detail: str = "") -> None:
    print(f"[PASS] {label}" + (f" — {detail}" if detail else ""))


def fail(label: str, fix: str) -> None:
    print(f"[FAIL] {label}")
    print(f"       fix: {fix}")
    hard_failures.append(label)


def warn(label: str, note: str) -> None:
    print(f"[WARN] {label} — {note}")
    warnings.append(label)


def check_python() -> None:
    v = sys.version_info
    if v >= (3, 10):
        ok("Python version", f"{v.major}.{v.minor}.{v.micro}")
    else:
        fail(f"Python {v.major}.{v.minor} is too old (need 3.10+)",
             "Mac: brew install python@3.12 / Windows: winget install Python.Python.3.12, "
             "then open a new terminal")


def check_ffmpeg() -> str | None:
    try:
        exe = get_ffmpeg()
        ok("ffmpeg found", exe)
        return exe
    except RuntimeError as e:
        fail("ffmpeg not found", str(e).splitlines()[1].strip())
        return None


def check_libass(ffmpeg: str) -> bool:
    result = run([ffmpeg, "-hide_banner", "-filters"])
    if result.returncode == 0 and " subtitles " in result.stdout:
        ok("ffmpeg can burn subtitles (libass)")
        return True
    fail("this ffmpeg build cannot burn subtitles",
         "install the real ffmpeg — Mac: brew install ffmpeg / "
         "Windows: winget install Gyan.FFmpeg — and never use "
         "imageio-ffmpeg or a 'python ffmpeg' package")
    return False


def check_ffprobe() -> None:
    try:
        exe = get_ffprobe()
        ok("ffprobe found", exe)
    except RuntimeError:
        fail("ffprobe not found",
             "it ships with ffmpeg — reinstall ffmpeg, then open a new terminal")


def check_packages() -> None:
    for mod, pkg in (("dotenv", "python-dotenv"), ("pythainlp", "pythainlp")):
        try:
            __import__(mod)
            ok(f"python package '{pkg}'")
        except ImportError:
            fail(f"python package '{pkg}' missing",
                 f"{sys.executable} -m pip install -r requirements.txt")


def check_fonts() -> None:
    missing = [f for f in FONT_FILES if not (FONTS_DIR / f).exists()]
    if not missing:
        ok("Thai fonts bundled", f"{len(FONT_FILES)} files in assets/fonts")
    else:
        fail(f"fonts missing from assets/fonts: {', '.join(missing)}",
             "re-download the workshop folder — do not delete assets/")


def check_sample() -> None:
    if SAMPLE.exists():
        size_mb = SAMPLE.stat().st_size / 1_000_000
        ok("sample video present", f"{SAMPLE.name}, {size_mb:.0f} MB")
    else:
        fail(f"sample video missing ({SAMPLE})",
             "re-download the workshop folder")


def check_api_key() -> None:
    load_env()
    key = os.getenv("GROQ_API_KEY", "").strip()
    if key:
        ok("GROQ_API_KEY set", f"...{key[-4:]}")
    else:
        warn("GROQ_API_KEY not set",
             "transcription will use the slower local mode; add the key to "
             ".env to use the fast cloud mode")


def check_butacut() -> None:
    serve = REPO_ROOT / "butacut" / "serve.py"
    app = REPO_ROOT / "butacut" / "app.html"
    if not (serve.exists() and app.exists()):
        fail("ButaCut timeline UI files missing (butacut/)",
             "re-download the workshop folder")
        return
    import subprocess
    import urllib.request
    url = "http://127.0.0.1:8766/api/config"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            resp.read()
        ok("ButaCut timeline reachable", "already running on port 8766")
        return
    except OSError:
        pass
    proc = subprocess.Popen(
        [sys.executable, str(serve)], cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        import time
        for _ in range(20):
            time.sleep(0.25)
            try:
                with urllib.request.urlopen(url, timeout=2) as resp:
                    resp.read()
                ok("ButaCut timeline starts", "python butacut/serve.py -> port 8766")
                return
            except OSError:
                if proc.poll() is not None:
                    break
        fail("ButaCut timeline did not start",
             "run 'python butacut/serve.py' yourself and read the error")
    finally:
        if proc.poll() is None:
            proc.terminate()


def check_smoke_render(ffmpeg_ok: bool) -> None:
    if not ffmpeg_ok or not SAMPLE.exists():
        print("[SKIP] smoke render (fix the failures above first)")
        return
    print("[..]   smoke render: burning a Thai subtitle onto 3s of the sample...")
    OUTPUTS_DIR.mkdir(exist_ok=True)
    ass_path = OUTPUTS_DIR / "_verify.ass"
    out_path = OUTPUTS_DIR / "_verify.mp4"
    ass_path.write_text(
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\nPlayResY: 1920\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Noto Sans Thai,64,&H00FFFFFF,&H00FFD700,&H00000000,"
        "&H00000000,-1,0,0,0,100,100,0,0,1,3,0,2,60,60,300,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.00,0:00:03.00,Default,,0,0,0,,"
        "ที่นี่มีป้ายกำกับ ระบบพร้อมแล้ว\n",
        encoding="utf-8",
    )
    try:
        from burn_subtitles import burn
        burn(SAMPLE, ass_path, out_path, to_time=3.0)
        if out_path.exists() and out_path.stat().st_size > 10_000:
            ok("smoke render", "Thai subtitles burned successfully")
        else:
            fail("smoke render produced an empty file",
                 "ask your AI agent to run the render again and read the error")
    except Exception as e:  # noqa: BLE001 — report anything to the student
        first_line = str(e).strip().splitlines()[0] if str(e).strip() else repr(e)
        fail(f"smoke render errored: {first_line}",
             "copy this whole output to your AI agent and ask it to fix it")
    finally:
        ass_path.unlink(missing_ok=True)
        out_path.unlink(missing_ok=True)


def main() -> None:
    setup_console()
    print(f"Workshop setup check — {REPO_ROOT}")
    print("-" * 60)
    check_python()
    ffmpeg = check_ffmpeg()
    libass_ok = check_libass(ffmpeg) if ffmpeg else False
    check_ffprobe()
    check_packages()
    check_fonts()
    check_sample()
    check_api_key()
    check_butacut()
    check_smoke_render(bool(ffmpeg) and libass_ok)
    print("-" * 60)
    if hard_failures:
        print(f"NOT READY — {len(hard_failures)} problem(s) to fix (see above).")
        print("Tip: copy this whole output to your AI agent and ask it to fix "
              "everything, then run me again.")
        sys.exit(1)
    if warnings:
        print(f"READY (with {len(warnings)} note(s) above).")
    else:
        print("READY — everything works. See you at the timeline.")


if __name__ == "__main__":
    main()
