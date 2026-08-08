"""
Burn a subtitle file (.ass) permanently into a video.

Uses the Thai fonts bundled in assets/fonts (the viewer's machine does not
need any fonts installed). The audio is copied untouched.

Example:
    python tools/burn_subtitles.py outputs/sample-talk-cut.mp4 outputs/sample-talk-cut.ass
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FONTS_DIR, OUTPUTS_DIR, filter_path, get_ffmpeg, run, setup_console


def burn(video: Path, ass: Path, output: Path,
         to_time: float | None = None) -> None:
    """Render `video` with `ass` subtitles burned in, writing `output`.

    to_time: optionally stop after N seconds (used by verify_setup's smoke test).
    """
    vf = (f"subtitles=filename='{filter_path(ass)}'"
          f":fontsdir='{filter_path(FONTS_DIR)}'")
    cmd = [get_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(video)]
    if to_time is not None:
        cmd += ["-t", f"{to_time:.3f}"]
    cmd += [
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        str(output),
    ]
    result = run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg subtitle burn failed:\n{result.stderr}")


def main() -> None:
    setup_console()
    parser = argparse.ArgumentParser(
        description="Burn an .ass subtitle file into a video (final render)."
    )
    parser.add_argument("video", type=Path, help="Input video")
    parser.add_argument("subtitles", type=Path, help="The .ass file from make_subtitles.py")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="Output .mp4 (default: outputs/<video>-final.mp4)")
    args = parser.parse_args()

    for p, label in ((args.video, "video"), (args.subtitles, "subtitle file")):
        if not p.exists():
            print(f"[FAIL] {label} not found: {p}")
            sys.exit(1)

    output = args.output
    if output is None:
        OUTPUTS_DIR.mkdir(exist_ok=True)
        output = OUTPUTS_DIR / f"{args.video.stem}-final.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)

    print(f"[..] burning {args.subtitles.name} into {args.video.name}...")
    burn(args.video, args.subtitles, output)
    size_mb = output.stat().st_size / 1_000_000
    print(f"[OK] wrote {output} ({size_mb:.1f} MB) — this is your final video")


if __name__ == "__main__":
    main()
