"""
Report what's inside a video file: duration, resolution, frame rate, audio,
and where the silences are.

A good first step before cutting — it shows how much dead air the clip has.

Example:
    python tools/inspect_video.py footage/sample-talk.mp4
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import get_ffprobe, run, setup_console
from cut_silences import _amplitude_to_db, compute_keep_ranges, detect_silences, get_duration


def probe(video: Path) -> dict:
    cmd = [get_ffprobe(), "-v", "error",
           "-show_entries",
           "stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
           "-show_entries", "format=duration,size",
           "-of", "json", str(video)]
    result = run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    return json.loads(result.stdout)


def main() -> None:
    setup_console()
    parser = argparse.ArgumentParser(description="Show what's inside a video file.")
    parser.add_argument("video", type=Path)
    parser.add_argument("--threshold", type=float, default=0.005,
                        help="Silence loudness threshold (same as cut_silences.py)")
    parser.add_argument("--min-silence", type=float, default=0.3)
    args = parser.parse_args()

    if not args.video.exists():
        print(f"[FAIL] file not found: {args.video}")
        sys.exit(1)

    info = probe(args.video)
    duration = float(info["format"]["duration"])
    size_mb = int(info["format"]["size"]) / 1_000_000

    print(f"file:      {args.video}")
    print(f"duration:  {duration:.1f}s")
    print(f"size:      {size_mb:.1f} MB")
    for s in info.get("streams", []):
        if s["codec_type"] == "video":
            fps = s.get("r_frame_rate", "?")
            if "/" in fps:
                num, den = fps.split("/")
                try:
                    fps = f"{float(num) / float(den):.2f}"
                except ZeroDivisionError:
                    pass
            print(f"video:     {s.get('width')}x{s.get('height')} "
                  f"@ {fps} fps ({s.get('codec_name')})")
        elif s["codec_type"] == "audio":
            print(f"audio:     {s.get('codec_name')}, "
                  f"{s.get('sample_rate')} Hz, {s.get('channels')} channel(s)")

    print("[..] detecting silences...")
    silences = detect_silences(args.video, _amplitude_to_db(args.threshold),
                               args.min_silence)
    total_silence = sum(e - s for s, e in silences)
    keeps = compute_keep_ranges(duration, silences, margin=0.0)
    print(f"silences:  {len(silences)} "
          f"({total_silence:.1f}s = {100 * total_silence / duration:.0f}% of the clip)")
    if silences:
        longest = max(silences, key=lambda p: p[1] - p[0])
        print(f"longest:   {longest[1] - longest[0]:.1f}s "
              f"(at {longest[0]:.1f}s)")
    print(f"speech:    {len(keeps)} spoken parts, "
          f"{duration - total_silence:.1f}s total")
    print()
    print("Tip: cut the dead air with tools/cut_silences.py")


if __name__ == "__main__":
    main()
