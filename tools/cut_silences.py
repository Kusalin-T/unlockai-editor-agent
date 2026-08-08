"""
Cut the silent parts out of one or more video clips.

Detects silences with ffmpeg, keeps only the spoken parts (with a little
breathing room around each), and writes ONE combined video. Also writes an
edit.json project file next to the output so ButaCut can show the cuts.

Examples:
    python tools/cut_silences.py footage/sample-talk.mp4
    python tools/cut_silences.py footage/sample-talk.mp4 --margin 0.5
    python tools/cut_silences.py clip1.mp4 clip2.mp4 -o outputs/combined.mp4
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import OUTPUTS_DIR, get_ffmpeg, get_ffprobe, run, setup_console

SILENCE_START_RE = re.compile(r"silence_start:\s*([\d.]+)")
SILENCE_END_RE = re.compile(r"silence_end:\s*([\d.]+)")


def get_duration(clip_path: Path) -> float:
    cmd = [get_ffprobe(), "-v", "error", "-show_entries", "format=duration",
           "-of", "csv=p=0", str(clip_path)]
    result = run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    return float(result.stdout.strip())


def _amplitude_to_db(amplitude: float) -> float:
    if amplitude <= 0:
        return -100.0
    return 20.0 * math.log10(amplitude)


def detect_silences(
    clip_path: Path, noise_db: float, min_duration: float = 0.3
) -> list[tuple[float, float]]:
    """Run ffmpeg silencedetect; return list of (start, end) silence ranges."""
    cmd = [
        get_ffmpeg(), "-hide_banner", "-nostats",
        "-i", str(clip_path),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_duration}",
        "-f", "null", "-",
    ]
    result = run(cmd)
    silences: list[tuple[float, float]] = []
    current_start: float | None = None
    for line in result.stderr.splitlines():
        m = SILENCE_START_RE.search(line)
        if m:
            current_start = float(m.group(1))
            continue
        m = SILENCE_END_RE.search(line)
        if m and current_start is not None:
            silences.append((current_start, float(m.group(1))))
            current_start = None
    return silences


def compute_keep_ranges(
    duration: float, silences: list[tuple[float, float]], margin: float
) -> list[tuple[float, float]]:
    """Invert silences -> speech keep ranges, padded by `margin` seconds."""
    keeps: list[tuple[float, float]] = []
    cursor = 0.0
    for s_start, s_end in silences:
        if s_start > cursor:
            keeps.append((cursor, s_start))
        cursor = s_end
    if cursor < duration:
        keeps.append((cursor, duration))

    padded = [(max(0.0, s - margin), min(duration, e + margin)) for s, e in keeps]
    if not padded:
        return []

    merged = [padded[0]]
    for s, e in padded[1:]:
        ls, le = merged[-1]
        if s <= le:
            merged[-1] = (ls, max(le, e))
        else:
            merged.append((s, e))
    return merged


def filter_keep_ranges(
    keeps: list[tuple[float, float]], min_duration: float
) -> list[tuple[float, float]]:
    """Drop keep ranges shorter than min_duration (clicks/noise, not speech)."""
    return [k for k in keeps if (k[1] - k[0]) >= min_duration]


def _build_trim_filter(keep_ranges: list[tuple[float, float]], fps: int = 24) -> str:
    # The fps=N filter at the end is critical — without it, trim+concat produces
    # slightly variable frame timing that accumulates drift and breaks lip-sync.
    parts = []
    for i, (start, end) in enumerate(keep_ranges):
        parts.append(
            f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{i}];"
            f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{i}]"
        )
    streams = "".join(f"[v{i}][a{i}]" for i in range(len(keep_ranges)))
    parts.append(
        f"{streams}concat=n={len(keep_ranges)}:v=1:a=1[v_concat][a];"
        f"[v_concat]fps={fps}[v]"
    )
    return ";".join(parts)


def _silence_cut_one(
    clip_path: Path, output_path: Path, keep_ranges: list[tuple[float, float]]
) -> None:
    """Re-encode a clip down to the given keep ranges in a single ffmpeg pass."""
    if not keep_ranges:
        raise ValueError(f"No keep ranges for {clip_path.name}")
    cmd = [
        get_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(clip_path),
        "-filter_complex", _build_trim_filter(keep_ranges),
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        str(output_path),
    ]
    result = run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg cut failed for {clip_path.name}:\n{result.stderr}")


def _concat_with_ffmpeg(clip_paths: list[Path], output_path: Path) -> None:
    """Concatenate clips via the concat demuxer + stream copy."""
    with tempfile.NamedTemporaryFile(
        "w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        for p in clip_paths:
            # Forward slashes work on every platform; backslashes break the
            # concat list parser on Windows.
            escaped = p.resolve().as_posix().replace("'", r"\'")
            f.write(f"file '{escaped}'\n")
        list_file = Path(f.name)
    try:
        cmd = [
            get_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            str(output_path),
        ]
        result = run(cmd)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg concat failed:\n{result.stderr}")
    finally:
        list_file.unlink(missing_ok=True)


def write_edit_json(
    source: Path,
    keeps: list[tuple[float, float]],
    fps: int,
    duration: float,
) -> Path:
    """
    Write/update the ButaCut edit.json sidecar NEXT TO THE SOURCE video
    (per the ButaCut edit-contract v1). Keep ranges are in source seconds.
    ButaCut watches this file — the timeline updates live. Preserves any
    existing text/sfx tracks; write is atomic.
    """
    from _common import edit_sidecar, read_json_tolerant, write_json_atomic
    edit_path = edit_sidecar(source)
    doc = read_json_tolerant(edit_path) or {}
    doc["version"] = 1
    doc["video"] = source.name
    doc["fps"] = fps
    doc["duration"] = round(duration, 3)
    doc["keeps"] = [
        {"in": round(s, 3), "out": round(e, 3), "origin": "silence_cut"}
        for s, e in keeps
    ]
    doc.setdefault("text", [])
    doc.setdefault("sfx", [])
    doc["updated"] = _now_iso()
    doc["by"] = "cut_silences"
    write_json_atomic(edit_path, doc)
    return edit_path


def _now_iso() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def main() -> None:
    setup_console()
    parser = argparse.ArgumentParser(
        description="Cut silent parts out of video clips and combine into one video."
    )
    parser.add_argument("inputs", nargs="+", type=Path,
                        help="One or more video files, in order.")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="Output .mp4 (default: outputs/<firstclip>-cut.mp4)")
    parser.add_argument("--margin", type=float, default=0.3,
                        help="Seconds of breathing room kept around each spoken "
                             "part (default 0.3; smaller = tighter cut)")
    parser.add_argument("--threshold", type=float, default=0.005,
                        help="Loudness (0.0-1.0) below which audio counts as "
                             "silence (default 0.005; raise if background noise "
                             "stops silences being detected)")
    parser.add_argument("--min-silence", type=float, default=0.3,
                        help="Ignore silences shorter than this many seconds "
                             "(default 0.3)")
    parser.add_argument("--min-speech", type=float, default=0.5,
                        help="Drop kept parts shorter than this many seconds — "
                             "usually clicks, not speech (default 0.5)")
    parser.add_argument("--fps", type=int, default=24)
    args = parser.parse_args()

    for clip in args.inputs:
        if not clip.exists():
            print(f"[FAIL] input not found: {clip}")
            sys.exit(1)

    output = args.output
    if output is None:
        OUTPUTS_DIR.mkdir(exist_ok=True)
        output = OUTPUTS_DIR / f"{args.inputs[0].stem}-cut.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)

    noise_db = _amplitude_to_db(args.threshold)
    total_in = 0.0
    total_kept = 0.0
    edit_paths: list[Path] = []

    with tempfile.TemporaryDirectory(prefix="cut-") as tmp:
        tmp_dir = Path(tmp)
        cut_clips: list[Path] = []
        for i, clip in enumerate(args.inputs):
            duration = get_duration(clip)
            total_in += duration
            print(f"[..] {clip.name}: {duration:.1f}s, detecting silences...")
            silences = detect_silences(clip, noise_db, args.min_silence)
            keeps = compute_keep_ranges(duration, silences, args.margin)
            keeps = filter_keep_ranges(keeps, args.min_speech)
            if not keeps:
                print(f"[..] {clip.name}: no speech found, skipping")
                continue
            kept = sum(e - s for s, e in keeps)
            total_kept += kept
            print(f"[OK] {clip.name}: keeping {len(keeps)} parts, "
                  f"{kept:.1f}s of {duration:.1f}s")
            out = tmp_dir / f"cut-{i:03d}.mp4"
            _silence_cut_one(clip, out, keeps)
            cut_clips.append(out)
            # ButaCut sidecar next to each source (keeps in source seconds).
            edit_paths.append(write_edit_json(clip, keeps, args.fps, duration))

        if not cut_clips:
            print("[FAIL] no speech found in any input")
            sys.exit(1)

        _concat_with_ffmpeg(cut_clips, output)

    removed = total_in - total_kept
    print(f"[OK] wrote {output}")
    for p in edit_paths:
        print(f"[OK] project file {p} updated (watch the ButaCut timeline)")
    print(f"[OK] removed {removed:.1f}s of silence "
          f"({total_in:.1f}s -> {total_kept:.1f}s)")


if __name__ == "__main__":
    main()
