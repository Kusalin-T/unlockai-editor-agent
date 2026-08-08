"""
Transcribe the speech in a video into text with word-level timestamps.

Two backends:
  groq   — Groq Cloud Whisper (fast, needs GROQ_API_KEY in .env)
  local  — faster-whisper on this machine (no key; slower; first run
           downloads the model, requires: pip install faster-whisper)

Default is auto: groq if a key is set, otherwise local.

Output: outputs/<video>.transcript.json (machine-readable, used by
make_subtitles.py) plus outputs/<video>.transcript.txt (human-readable).

Examples:
    python tools/transcribe.py outputs/sample-talk-cut.mp4
    python tools/transcribe.py outputs/sample-talk-cut.mp4 --backend local
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import OUTPUTS_DIR, get_ffmpeg, load_env, run, setup_console

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3"
LOCAL_MODEL = "small"


def _extract_audio_mp3(video: Path, mp3: Path, bitrate: str = "64k") -> None:
    cmd = [
        get_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video),
        "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "libmp3lame", "-b:a", bitrate,
        str(mp3),
    ]
    r = run(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extract failed:\n{r.stderr}")


def _embed_words_in_segments(segments: list[dict], top_words: list[dict]) -> list[dict]:
    """Groq returns words and segments separately; nest each word into the
    segment whose [start, end) window contains the word's start time."""
    out = []
    wi = 0
    for seg in segments:
        s_start = float(seg.get("start", 0))
        s_end = float(seg.get("end", s_start))
        words: list[dict] = []
        while wi < len(top_words):
            w = top_words[wi]
            try:
                w_start = float(w["start"])
            except (KeyError, TypeError):
                wi += 1
                continue
            if w_start >= s_end:
                break
            words.append({
                "word": w["word"],
                "start": float(w["start"]),
                "end": float(w["end"]),
                "probability": float(w.get("confidence", w.get("probability", 1.0))),
            })
            wi += 1
        out.append({
            "start": s_start,
            "end": s_end,
            "text": seg.get("text", "").strip(),
            "words": words,
        })
    return out


def transcribe_groq(video_path: Path, language: str, api_key: str) -> dict:
    """Send audio to Groq's Whisper endpoint; return the transcript dict."""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        mp3 = Path(f.name)
    try:
        _extract_audio_mp3(video_path, mp3)
        fields = {
            "model": GROQ_MODEL,
            "language": language,
            "response_format": "verbose_json",
            "temperature": "0",
        }
        boundary = "----groqclient"
        body = b""
        for k, v in fields.items():
            body += (f'--{boundary}\r\nContent-Disposition: form-data; '
                     f'name="{k}"\r\n\r\n{v}\r\n').encode()
        # Both timestamp granularities so we get word-level timing in segments.
        for gran in ("word", "segment"):
            body += (f'--{boundary}\r\nContent-Disposition: form-data; '
                     f'name="timestamp_granularities[]"\r\n\r\n{gran}\r\n').encode()
        body += (
            f'--{boundary}\r\nContent-Disposition: form-data; '
            f'name="file"; filename="{mp3.name}"\r\n'
            f"Content-Type: audio/mpeg\r\n\r\n"
        ).encode()
        body += mp3.read_bytes()
        body += f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            GROQ_URL, data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                # Groq sits behind Cloudflare which 403s python's default UA.
                "User-Agent": "curl/8.5.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                result = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            if e.code == 401:
                raise RuntimeError(
                    "Groq rejected the API key (401). Check GROQ_API_KEY in .env."
                ) from e
            raise RuntimeError(f"Groq API error {e.code}:\n{detail}") from e
    finally:
        mp3.unlink(missing_ok=True)

    segments = result.get("segments") or []
    words = result.get("words") or []
    embedded = _embed_words_in_segments(segments, words) if (segments and words) else [
        {**s, "text": s.get("text", "").strip(), "words": []} for s in segments
    ]
    return {
        "language": result.get("language", language),
        "duration": float(result.get("duration", 0.0)),
        "segments": embedded,
    }


def transcribe_local(video_path: Path, language: str, model_name: str) -> dict:
    """Transcribe with faster-whisper on this machine (no API key needed)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError(
            "Local transcription needs faster-whisper. Install it with:\n"
            f"  {sys.executable} -m pip install faster-whisper\n"
            "(first run also downloads the speech model — a few hundred MB)"
        )
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        mp3 = Path(f.name)
    try:
        _extract_audio_mp3(video_path, mp3)
        print(f"[..] loading local model '{model_name}' "
              "(first run downloads it — please wait)")
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segments_iter, info = model.transcribe(
            str(mp3), language=language, word_timestamps=True, vad_filter=True
        )
        segments = []
        for seg in segments_iter:
            segments.append({
                "start": float(seg.start),
                "end": float(seg.end),
                "text": seg.text.strip(),
                "words": [
                    {"word": w.word, "start": float(w.start), "end": float(w.end),
                     "probability": float(w.probability)}
                    for w in (seg.words or [])
                ],
            })
        return {
            "language": info.language,
            "duration": float(info.duration),
            "segments": segments,
        }
    finally:
        mp3.unlink(missing_ok=True)


def main() -> None:
    setup_console()
    load_env()
    parser = argparse.ArgumentParser(
        description="Transcribe a video's speech to text with word timestamps."
    )
    parser.add_argument("video", type=Path, help="Video (or audio) file")
    parser.add_argument("--backend", choices=["auto", "groq", "local"],
                        default="auto",
                        help="auto (default): groq if GROQ_API_KEY is set, "
                             "else local")
    parser.add_argument("--language", default="th",
                        help="Spoken language code (default: th = Thai)")
    parser.add_argument("--model", default=LOCAL_MODEL,
                        help=f"Local model size (default: {LOCAL_MODEL})")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="Output .transcript.json "
                             "(default: outputs/<video>.transcript.json)")
    args = parser.parse_args()

    if not args.video.exists():
        print(f"[FAIL] video not found: {args.video}")
        sys.exit(1)

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    backend = args.backend
    if backend == "auto":
        backend = "groq" if api_key else "local"
        print(f"[..] backend auto -> {backend}")
    if backend == "groq" and not api_key:
        print("[FAIL] GROQ_API_KEY is not set in .env — "
              "add the key, or use --backend local")
        sys.exit(1)

    print(f"[..] transcribing {args.video.name} ({backend})...")
    if backend == "groq":
        transcript = transcribe_groq(args.video, args.language, api_key)
    else:
        transcript = transcribe_local(args.video, args.language, args.model)

    output = args.output
    if output is None:
        OUTPUTS_DIR.mkdir(exist_ok=True)
        output = OUTPUTS_DIR / f"{args.video.stem}.transcript.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    txt_path = output.with_name(output.name.replace(".json", ".txt"))
    lines = [seg["text"] for seg in transcript["segments"] if seg["text"]]
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    n_words = sum(len(s["words"]) for s in transcript["segments"])
    print(f"[OK] wrote {output} "
          f"({len(transcript['segments'])} segments, {n_words} timed words)")
    print(f"[OK] wrote {txt_path} (read this one)")


if __name__ == "__main__":
    main()
