"""
Turn a transcript into a subtitle file (.ass) with Thai-aware line breaks.

Reads the .transcript.json produced by transcribe.py, groups the words into
readable on-screen chunks (using pythainlp to find real Thai word boundaries
— Thai has no spaces between words, so naive splitting produces garbage),
and writes a styled .ass subtitle file ready for burn_subtitles.py.

Also updates the edit.json project file (if one sits next to the video) so
ButaCut shows the subtitle chunks on its timeline.

Examples:
    python tools/make_subtitles.py outputs/sample-talk-cut.transcript.json --video outputs/sample-talk-cut.mp4
    python tools/make_subtitles.py outputs/sample-talk-cut.transcript.json --video outputs/sample-talk-cut.mp4 --style pop --font-size 72
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import OUTPUTS_DIR, get_ffprobe, run, setup_console

# ── Data ────────────────────────────────────────────────────────────────────


@dataclass
class Word:
    word: str
    start: float
    end: float


@dataclass
class Chunk:
    words: list[Word]
    _start_override: float | None = None
    _end_override: float | None = None

    @property
    def start(self) -> float:
        if self._start_override is not None:
            return self._start_override
        return self.words[0].start

    @property
    def end(self) -> float:
        if self._end_override is not None:
            return self._end_override
        return self.words[-1].end

    @property
    def text(self) -> str:
        return "".join(w.word for w in self.words).strip()


# ── Chunking ────────────────────────────────────────────────────────────────

MAX_WORD_DURATION = 2.0  # cap: whisper sometimes gives one char a huge duration


def _sanitize_words(words: list[Word]) -> list[Word]:
    out: list[Word] = []
    for w in words:
        end = w.end
        if end - w.start > MAX_WORD_DURATION:
            end = w.start + MAX_WORD_DURATION
        out.append(Word(word=w.word, start=w.start, end=end))
    return out


def _flatten_words(transcript: dict) -> list[Word]:
    out: list[Word] = []
    for seg in transcript.get("segments", []):
        for w in seg.get("words", []):
            out.append(Word(word=w["word"], start=float(w["start"]), end=float(w["end"])))
    return _sanitize_words(out)


def chunk_by_duration(transcript: dict, max_seconds: float) -> list[Chunk]:
    flat = _flatten_words(transcript)
    chunks: list[Chunk] = []
    current: list[Word] = []
    current_start: float | None = None
    for w in flat:
        if current_start is None:
            current_start = w.start
        if w.end - current_start > max_seconds and current:
            chunks.append(Chunk(words=current))
            current = []
            current_start = w.start
        current.append(w)
    if current:
        chunks.append(Chunk(words=current))
    return chunks


def chunk_by_thai_semantic(transcript: dict, n_words: int = 5) -> list[Chunk]:
    """
    Group whisper's character-level Thai "words" into chunks of N real words.

    Whisper segments Thai at the character/cluster level (Thai script has no
    spaces between words). This strategy reconstructs each segment's text,
    tokenizes it with pythainlp, maps tokens back to whisper's per-character
    timing, then slices into chunks at natural pauses, sentence connectors
    (และ/หรือ/แต่), clause boundaries (whitespace), or the N-word cap.
    """
    from pythainlp.tokenize import word_tokenize

    all_chunks: list[Chunk] = []
    for seg in transcript.get("segments", []):
        whisper_words_raw = seg.get("words") or []
        if not whisper_words_raw:
            continue

        whisper_words = []
        for w in whisper_words_raw:
            start = float(w["start"])
            end = float(w["end"])
            if end - start > MAX_WORD_DURATION:
                end = start + MAX_WORD_DURATION
            whisper_words.append({"word": w["word"], "start": start, "end": end})

        full_text = "".join(w["word"] for w in whisper_words)
        if not full_text.strip():
            continue

        char_to_widx: list[int] = []
        for wi, w in enumerate(whisper_words):
            for _ in w["word"]:
                char_to_widx.append(wi)

        tokens = word_tokenize(full_text, engine="newmm", keep_whitespace=True)

        # Build timed tokens; trailing whitespace attaches to the previous
        # token so spaces between Thai/English survive in the rendered text.
        seg_words: list[Word] = []
        char_pos = 0
        pending_ws = ""
        for tok in tokens:
            tok_len = len(tok)
            if not tok.strip():
                pending_ws += tok
                char_pos += tok_len
                continue
            tok_start_char = char_pos
            tok_end_char = min(char_pos + tok_len - 1, len(char_to_widx) - 1)
            char_pos += tok_len
            if tok_start_char >= len(char_to_widx):
                break
            start_widx = char_to_widx[tok_start_char]
            end_widx = char_to_widx[tok_end_char]
            if pending_ws and seg_words:
                seg_words[-1] = Word(
                    word=seg_words[-1].word + pending_ws,
                    start=seg_words[-1].start,
                    end=seg_words[-1].end,
                )
            pending_ws = ""
            seg_words.append(Word(
                word=tok,
                start=float(whisper_words[start_widx]["start"]),
                end=float(whisper_words[end_widx]["end"]),
            ))

        # Slice into chunks. Three break conditions:
        #   1. inter-word gap > GAP_THRESHOLD (real pause) — hard break
        #   2. next token is a sentence connector (และ/หรือ/แต่) — hard break
        #   3. clause boundary (whitespace in transcript) or N-word cap — soft
        # Soft breaks allow the one-word-orphan merge below; hard breaks don't.
        GAP_THRESHOLD = 0.35
        SENTENCE_CONNECTORS = {"และ", "หรือ", "แต่"}
        MIN_PRE_CONNECTOR_CHUNK_DURATION = 0.55
        chunks_in_seg: list[list[Word]] = []
        break_was_hard: list[bool] = []
        current: list[Word] = []
        for w in seg_words:
            if current:
                bare_tok = w.word.lstrip()
                prev_ends_with_space = current[-1].word != current[-1].word.rstrip()
                gap = w.start - current[-1].end
                if gap > GAP_THRESHOLD:
                    chunks_in_seg.append(current)
                    break_was_hard.append(True)
                    current = [w]
                    continue
                if bare_tok in SENTENCE_CONNECTORS and len(current) >= 1:
                    chunk_duration = current[-1].end - current[0].start
                    if chunk_duration >= MIN_PRE_CONNECTOR_CHUNK_DURATION:
                        chunks_in_seg.append(current)
                        break_was_hard.append(True)
                        current = [w]
                        continue
                if prev_ends_with_space and len(current) >= 2:
                    chunk_duration = current[-1].end - current[0].start
                    if chunk_duration >= MIN_PRE_CONNECTOR_CHUNK_DURATION:
                        chunks_in_seg.append(current)
                        break_was_hard.append(False)
                        current = [w]
                        continue
                if len(current) >= n_words:
                    chunks_in_seg.append(current)
                    break_was_hard.append(False)
                    current = [w]
                    continue
            current.append(w)
        if current:
            chunks_in_seg.append(current)

        # Merge one-word chunks into a neighbour across SOFT breaks only —
        # kills the "single word flashes for 0.3s" pattern.
        changed = True
        while changed:
            changed = False
            i = 0
            while i < len(chunks_in_seg):
                if len(chunks_in_seg[i]) > 1:
                    i += 1
                    continue
                if i > 0 and not break_was_hard[i - 1]:
                    chunks_in_seg[i - 1].extend(chunks_in_seg.pop(i))
                    break_was_hard.pop(i - 1)
                    changed = True
                    continue
                if i < len(chunks_in_seg) - 1 and not break_was_hard[i]:
                    chunks_in_seg[i].extend(chunks_in_seg.pop(i + 1))
                    break_was_hard.pop(i)
                    changed = True
                    continue
                i += 1

        for block in chunks_in_seg:
            if block:
                all_chunks.append(Chunk(words=block))

    return all_chunks


# ── ASS writing ─────────────────────────────────────────────────────────────


def _ass_time(t: float) -> str:
    if t < 0:
        t = 0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    cs = int(round((t - int(t)) * 100))
    if cs == 100:
        cs = 0
        s += 1
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _hex_to_ass_color(hex_str: str) -> str:
    h = hex_str.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"Expected #RRGGBB, got {hex_str}")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


@dataclass
class AssStyleParams:
    font_name: str = "Noto Sans Thai"
    font_size: int = 64
    primary_color: str = "#FFFFFF"
    secondary_color: str = "#FFD700"
    outline_color: str = "#000000"
    back_color: str = "#000000"
    outline: int = 3
    shadow: int = 0
    bold: bool = True
    alignment: int = 2
    margin_l: int = 60
    margin_r: int = 60
    margin_v: int = 80
    play_res_x: int = 1080
    play_res_y: int = 1920


def write_ass_header(params: AssStyleParams) -> str:
    primary = _hex_to_ass_color(params.primary_color)
    secondary = _hex_to_ass_color(params.secondary_color)
    outline = _hex_to_ass_color(params.outline_color)
    back = _hex_to_ass_color(params.back_color)
    bold = -1 if params.bold else 0
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {params.play_res_x}\n"
        f"PlayResY: {params.play_res_y}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{params.font_name},{params.font_size},"
        f"{primary},{secondary},{outline},{back},"
        f"{bold},0,0,0,100,100,0,0,1,{params.outline},{params.shadow},"
        f"{params.alignment},{params.margin_l},{params.margin_r},{params.margin_v},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def _block_text_plain(chunk: Chunk) -> str:
    # Fade-in only — a fade-out overlaps the next chunk and libass stacks them.
    return f"{{\\fad(40,0)}}{chunk.text}"


def _block_text_pop(chunk: Chunk) -> str:
    return (f"{{\\fad(50,0)\\t(0,180,\\fscx115\\fscy115)"
            f"\\t(180,260,\\fscx100\\fscy100)}}{chunk.text}")


def _block_text_karaoke(chunk: Chunk) -> str:
    parts: list[str] = []
    for w in chunk.words:
        cs = max(1, int(round((w.end - w.start) * 100)))
        parts.append(f"{{\\kf{cs}}}{w.word}")
    return "{\\fad(40,0)}" + "".join(parts)


_STYLE_BUILDERS = {
    "plain": _block_text_plain,
    "pop": _block_text_pop,
    "karaoke": _block_text_karaoke,
}


def render_dialogue(chunk: Chunk, style: str) -> str:
    text = _STYLE_BUILDERS[style](chunk)
    return (
        f"Dialogue: 0,{_ass_time(chunk.start)},{_ass_time(chunk.end)},"
        f"Default,,0,0,0,,{text}\n"
    )


CHUNK_GAP_SECONDS = 0.04       # keeps consecutive chunks from overlapping
SUBTITLE_LEAD_SECONDS = 0.20   # captions land slightly before the voice
MIN_CHUNK_DURATION = 0.55      # no unreadable flashes
MAX_CHUNK_DURATION = 4.0       # no stuck captions


def _ensure_gaps(chunks: list[Chunk]) -> list[Chunk]:
    """Give every chunk display-time overrides: slight lead before the audio,
    a readability floor, and strict non-overlap with its neighbours."""
    n = len(chunks)
    if n == 0:
        return []
    out: list[Chunk] = []
    last_displayed_end = -1.0
    for i, c in enumerate(chunks):
        if not c.words:
            out.append(c)
            continue
        natural_start = c.words[0].start
        natural_end = c.words[-1].end
        start = max(0.0, natural_start - SUBTITLE_LEAD_SECONDS)
        start = max(start, last_displayed_end + CHUNK_GAP_SECONDS)
        end = max(natural_end, start + MIN_CHUNK_DURATION)
        if i + 1 < n and chunks[i + 1].words:
            next_displayed_start = chunks[i + 1].words[0].start - SUBTITLE_LEAD_SECONDS
            end = min(end, next_displayed_start - CHUNK_GAP_SECONDS)
        end = min(end, start + MAX_CHUNK_DURATION)
        if end <= start:
            end = start + 0.30
        out.append(Chunk(words=c.words, _start_override=start, _end_override=end))
        last_displayed_end = end
    return out


def write_ass_file(
    chunks: Iterable[Chunk], style: str, out_path: Path, style_params: AssStyleParams
) -> tuple[Path, list[Chunk]]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    chunk_list = _ensure_gaps(list(chunks))
    body = [write_ass_header(style_params)]
    for chunk in chunk_list:
        body.append(render_dialogue(chunk, style))
    out_path.write_text("".join(body), encoding="utf-8")
    return out_path, chunk_list


# ── edit.json update (ButaCut timeline) ─────────────────────────────────────


def update_edit_json_text(video: Path, chunks: list[Chunk], ass_path: Path) -> Path | None:
    """If an edit.json project file sits next to the video, write the subtitle
    chunks into its `text` track so ButaCut displays them."""
    edit_path = video.with_name(video.stem + ".edit.json")
    if not edit_path.exists():
        return None
    try:
        doc = json.loads(edit_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(doc, dict):
        return None
    doc["text"] = [
        {
            "start": round(c.start, 3),
            "end": round(c.end, 3),
            "text": c.text,
            "origin": "subtitles",
            "asset": ass_path.name,
        }
        for c in chunks
    ]
    edit_path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return edit_path


# ── CLI ─────────────────────────────────────────────────────────────────────


def _probe_resolution(video: Path) -> tuple[int, int] | None:
    cmd = [get_ffprobe(), "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height", "-of", "csv=p=0", str(video)]
    result = run(cmd)
    if result.returncode != 0:
        return None
    m = re.match(r"(\d+),(\d+)", result.stdout.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


POSITION_TO_ALIGNMENT = {"bottom": 2, "top": 8, "center": 5}


def main() -> None:
    setup_console()
    parser = argparse.ArgumentParser(
        description="Turn a transcript into a styled .ass subtitle file "
                    "(Thai-aware line breaks)."
    )
    parser.add_argument("transcript", type=Path,
                        help="The .transcript.json from transcribe.py")
    parser.add_argument("--video", type=Path, default=None,
                        help="The video these subtitles are for — used to match "
                             "resolution and update its ButaCut project file")
    parser.add_argument("--style", choices=list(_STYLE_BUILDERS), default="plain",
                        help="plain (default) | pop (bounce in) | "
                             "karaoke (highlights the current word)")
    parser.add_argument("--chunk-by", choices=["thai_words", "duration"],
                        default="thai_words",
                        help="thai_words (default): N real Thai words per "
                             "subtitle. duration: time-based")
    parser.add_argument("--chunk-size", type=float, default=5,
                        help="N words (thai_words) or seconds (duration). "
                             "Default: 5")
    parser.add_argument("--position", choices=list(POSITION_TO_ALIGNMENT),
                        default="bottom")
    parser.add_argument("--font-size", type=int, default=64)
    parser.add_argument("--color", type=str, default="#FFFFFF")
    parser.add_argument("--outline", type=int, default=3)
    parser.add_argument("--margin-v", type=int, default=None,
                        help="Distance (px) from the screen edge. Default: "
                             "1/3 of video height for vertical video, 80 for "
                             "horizontal")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="Output .ass path (default: outputs/<name>.ass)")
    args = parser.parse_args()

    if not args.transcript.exists():
        print(f"[FAIL] transcript not found: {args.transcript}")
        sys.exit(1)

    transcript = json.loads(args.transcript.read_text(encoding="utf-8"))

    if args.chunk_by == "thai_words":
        try:
            chunks = chunk_by_thai_semantic(transcript, max(1, int(args.chunk_size)))
        except ImportError:
            print("[FAIL] pythainlp is not installed. Run: "
                  f"{sys.executable} -m pip install -r requirements.txt")
            sys.exit(1)
    else:
        chunks = chunk_by_duration(transcript, float(args.chunk_size))

    if not chunks:
        print("[FAIL] transcript has no timed words — re-run transcribe.py")
        sys.exit(1)

    play_x, play_y = 1080, 1920
    if args.video and args.video.exists():
        res = _probe_resolution(args.video)
        if res:
            play_x, play_y = res

    margin_v = args.margin_v
    if margin_v is None:
        # Vertical video: sit at ~1/3 from the bottom (clear of IG/TikTok UI).
        margin_v = round(play_y / 3) if play_y > play_x else 80

    style_params = AssStyleParams(
        font_name="Noto Sans Thai",
        font_size=args.font_size,
        primary_color=args.color,
        outline=args.outline,
        bold=True,
        alignment=POSITION_TO_ALIGNMENT[args.position],
        margin_v=margin_v,
        play_res_x=play_x,
        play_res_y=play_y,
    )

    output = args.output
    if output is None:
        OUTPUTS_DIR.mkdir(exist_ok=True)
        stem = args.transcript.name.replace(".transcript.json", "")
        output = OUTPUTS_DIR / f"{stem}.ass"

    _, final_chunks = write_ass_file(chunks, args.style, output, style_params)
    print(f"[OK] wrote {output} ({len(final_chunks)} subtitle chunks, "
          f"style={args.style}, {play_x}x{play_y})")

    if args.video:
        edit_path = update_edit_json_text(args.video, final_chunks, output)
        if edit_path:
            print(f"[OK] project file {edit_path.name} updated "
                  "(ButaCut will show the subtitles)")


if __name__ == "__main__":
    main()
