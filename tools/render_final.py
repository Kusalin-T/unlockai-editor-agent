"""
Render the FINISHED video from a ButaCut project file — one ffmpeg pass.

Reads the `<video>.edit.json` sidecar (butacut/edit-contract.md) and produces
what the ButaCut preview shows: keeps cut together, `zoom` effects applied to
the picture (ease-in ~0.5s then HOLD), text bursts/subtitles and pop-up cards
burned in, and sound effects mixed into the audio at the right moments.

Run it on the SOURCE video's sidecar (times in edit.json are source seconds):

    python tools/render_final.py --edit footage/sample-talk.edit.json
    python tools/render_final.py --edit footage/sample-talk.edit.json --out outputs/final.mp4

Events that fall inside cut-away material are dropped automatically.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (
    FONTS_DIR, OUTPUTS_DIR, REPO_ROOT,
    filter_path, get_ffmpeg, get_ffprobe, run, setup_console,
)

FPS_DEFAULT = 24
W, H = 1080, 1920           # ASS design space; libass scales to the real video
FONT = "Noto Sans Thai"
RAMP = 0.5                  # zoom ease-in seconds (matches the ButaCut viewer)


def probe(video: Path) -> tuple[int, int, float]:
    result = run([get_ffprobe(), "-v", "error", "-select_streams", "v:0",
                  "-show_entries", "stream=width,height:format=duration",
                  "-of", "json", str(video)])
    if result.returncode != 0:
        print(f"[FAIL] could not read {video.name}: {result.stderr.strip()[:300]}")
        sys.exit(1)
    data = json.loads(result.stdout)
    st = data["streams"][0]
    return int(st["width"]), int(st["height"]), float(data["format"]["duration"])


# ── source-time → output-time remapping ─────────────────────────────────────


def make_remap(keeps: list[dict]):
    """Times in edit.json are SOURCE seconds; the output video only contains
    the keeps. Returns (visible, total): visible(a, b) gives the event's span
    on the output timeline, or None if the cut removed it entirely."""
    spans = []
    cursor = 0.0
    for k in keeps:
        spans.append((k["in"], k["out"], cursor))
        cursor += k["out"] - k["in"]

    def remap(t: float) -> float:
        for a, b, off in spans:
            if t < a:
                return off          # inside cut material -> snap forward
            if t <= b:
                return off + (t - a)
        return cursor

    def visible(a: float, b: float):
        oa, ob = remap(a), remap(b)
        if ob - oa < 0.05:
            return None
        return oa, ob

    return visible, cursor


# ── ASS burn (text bursts, subtitles, pop-up cards) ─────────────────────────


def ass_time(t: float) -> str:
    cs = int(round(t * 100))
    return "%d:%02d:%02d.%02d" % (cs // 360000, cs // 6000 % 60, cs // 100 % 60, cs % 100)


def ass_color(hexstr: str, alpha: int = 0) -> str:
    hexstr = (hexstr or "#94B6EF").lstrip("#")
    r, g, b = hexstr[0:2], hexstr[2:4], hexstr[4:6]
    return "&H%02X%s%s%s" % (alpha, b.upper(), g.upper(), r.upper())


def strip_emoji(text: str) -> str:
    """The bundled Thai font has no emoji glyphs — they'd render as boxes."""
    return "".join(ch for ch in text
                   if ord(ch) < 0x1F000 and not (0x2600 <= ord(ch) <= 0x27BF)).strip()


def build_ass(doc: dict, visible) -> str:
    ivory = "&H00EFF2F4"
    panel = "&H301C120C"
    dark = "&HA0120B06"
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Burst,{FONT},104,{ivory},{ivory},{dark},{dark},1,0,0,0,100,100,0,0,1,5,2,5,40,40,0,1
Style: Sub,{FONT},46,{ivory},{ivory},{dark},{dark},1,0,0,0,100,100,0,0,1,3,1,2,60,60,{int(H * 0.30)},1
Style: Card,{FONT},46,{ivory},{ivory},&H0094B6EF,{panel},1,0,0,0,100,100,0,0,3,10,0,5,40,40,0,1
Style: Chip,{FONT},40,{ivory},{ivory},&H0094B6EF,{panel},1,0,0,0,100,100,0,0,3,8,0,5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines: list[str] = []

    def dlg(style: str, a: float, b: float, text: str, extra: str = "") -> None:
        lines.append("Dialogue: 0,%s,%s,%s,,0,0,0,,%s%s"
                     % (ass_time(a), ass_time(b), style, extra, text))

    for ev in doc.get("text", []):
        span = visible(ev["in"], ev["out"])
        if not span:
            continue
        a, b = span
        content = (ev.get("content") or "").replace("\n", "\\N")
        if not content:
            continue
        if ev.get("style") == "burst":
            pop = r"{\pos(540,%d)\fad(60,40)\fscx82\fscy82\t(0,140,\fscx100\fscy100)}" % int(H * 0.46)
            dlg("Burst", a, b, content, pop)
        elif ev.get("pos") == "top":
            dlg("Sub", a, b, content, r"{\an8\pos(540,%d)}" % int(H * 0.10))
        else:
            dlg("Sub", a, b, content)

    for ev in doc.get("fx", []):
        kind = ev.get("kind")
        if kind in ("zoom", "zoom-drift"):
            continue                 # zooms are handled by the video chain
        span = visible(ev["in"], ev["out"])
        if not span:
            continue
        a, b = span
        y = int(ev.get("y", 430))
        border = ass_color(ev.get("border", "#94B6EF"))
        popin = r"\fad(80,60)\fscx80\fscy80\t(0,160,\fscx100\fscy100)"
        if kind == "card":
            label = strip_emoji(ev.get("label", ""))
            if label:
                dlg("Card", a, b, label, r"{\pos(540,%d)\3c%s%s}" % (y + 60, border, popin))
        elif kind == "chips":
            for i, it in enumerate(ev.get("items", [])):
                label = strip_emoji(it.get("text", ""))
                if not label:
                    continue
                c = ass_color(it.get("color", "#94B6EF"))
                dlg("Chip", a + i * 0.14, b, label,
                    r"{\pos(540,%d)\3c%s%s}" % (y + 50 + i * 96, c, popin))
        elif kind == "stats":
            items = ev.get("items", [])
            n = len(items)
            for i, it in enumerate(items):
                big = strip_emoji(str(it[1] if len(it) > 1 else ""))
                small = strip_emoji(str(it[2] if len(it) > 2 else ""))
                x = 540 + (i - (n - 1) / 2.0) * 320
                dlg("Chip", a + 0.2 + i * 0.3, b, "%s\\N%s" % (big, small),
                    r"{\pos(%d,%d)\3c%s%s}" % (int(x), y + 80, ass_color("#E68C3A"), popin))
    return header + "\n".join(lines) + "\n"


# ── zoom expression (flat by default, ease-in then HOLD) ────────────────────


def zoom_expr(doc: dict, visible, fps: int):
    parts = []
    for ev in doc.get("fx", []):
        if ev.get("kind") != "zoom":
            continue
        span = visible(ev["in"], ev["out"])
        if not span:
            continue
        a, b = span
        f0 = float(ev.get("from", 1.0))
        f1 = float(ev.get("to", 1.25))
        ramp = min(RAMP, max(0.15, b - a))
        parts.append(
            "if(between(T,{a:.3f},{b:.3f}),"
            "{f0:.4f}+({f1:.4f}-{f0:.4f})*min(1,(T-{a:.3f})/{r:.3f}),".format(
                a=a, b=b, f0=f0, f1=f1, r=ramp))
    if not parts:
        return None
    expr = "".join(parts) + "1.0" + ")" * len(parts)
    return expr.replace("T", "(in/%d)" % fps)


# ── main ────────────────────────────────────────────────────────────────────


def main() -> None:
    setup_console()
    ap = argparse.ArgumentParser(
        description="Render the finished video (cuts + zooms + burned text + "
                    "sfx) from a ButaCut edit.json.")
    ap.add_argument("--edit", required=True, type=Path,
                    help="The <video>.edit.json sidecar (next to the source video)")
    ap.add_argument("--out", type=Path, default=None,
                    help="Output mp4 (default: outputs/<video-stem>-final.mp4)")
    args = ap.parse_args()

    edit_path = args.edit
    doc = json.loads(edit_path.read_text(encoding="utf-8"))
    video = edit_path.parent / doc["video"]
    if not video.exists():
        print(f"[FAIL] source video not found next to the edit file: {video}")
        sys.exit(1)
    out_path = args.out
    if out_path is None:
        OUTPUTS_DIR.mkdir(exist_ok=True)
        out_path = OUTPUTS_DIR / f"{video.stem}-final.mp4"

    fps = int(doc.get("fps", FPS_DEFAULT))
    vw, vh, duration = probe(video)

    keeps = doc.get("keeps") or [{"in": 0.0, "out": duration}]
    keeps = sorted(({"in": max(0.0, float(k["in"])), "out": min(duration, float(k["out"]))}
                    for k in keeps), key=lambda k: k["in"])
    keeps = [k for k in keeps if k["out"] > k["in"]]
    visible, total = make_remap(keeps)

    tmpdir = Path(tempfile.mkdtemp(prefix="butacut-render-"))
    ass_path = tmpdir / "burn.ass"
    ass_path.write_text(build_ass(doc, visible), encoding="utf-8")

    # ---- video: cut -> zoom -> burn ----
    fc: list[str] = []
    vlabels, alabels = [], []
    for i, k in enumerate(keeps):
        fc.append("[0:v]trim=start=%.3f:end=%.3f,setpts=PTS-STARTPTS[v%d]"
                  % (k["in"], k["out"], i))
        fc.append("[0:a]atrim=start=%.3f:end=%.3f,asetpts=PTS-STARTPTS[a%d]"
                  % (k["in"], k["out"], i))
        vlabels.append("[v%d]" % i)
        alabels.append("[a%d]" % i)
    fc.append("".join(v + a for v, a in zip(vlabels, alabels)) +
              "concat=n=%d:v=1:a=1[vcut][acut]" % len(keeps))

    vchain = "[vcut]"
    zexpr = zoom_expr(doc, visible, fps)
    if zexpr:
        # Normalize to the target fps FIRST — zoompan re-times frames rather
        # than resampling, so feeding it e.g. 30fps footage at fps=24 would
        # stretch the video into slow motion.
        fc.append("%sfps=%d[vfps]" % (vchain, fps))
        fc.append("[vfps]zoompan=z='%s':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                  ":d=1:fps=%d:s=%dx%d[vz]" % (zexpr, fps, vw, vh))
        vchain = "[vz]"
    fc.append("%ssubtitles=filename='%s':fontsdir='%s'[vout]"
              % (vchain, filter_path(ass_path), filter_path(FONTS_DIR)))

    # ---- audio: cut + delayed sfx ----
    inputs = [get_ffmpeg(), "-v", "error", "-y", "-i", str(video)]
    mix = ["[acut]"]
    n_in = 1
    for ev in doc.get("sfx", []):
        f = ev.get("file")
        span = visible(ev["at"], ev["at"] + 0.2)
        if not f or not span:
            continue
        # Contract: sfx paths are relative to the repo root.
        cand = Path(f) if Path(f).is_absolute() else REPO_ROOT / f
        if not cand.exists():
            cand = edit_path.parent / f
        if not cand.exists():
            print(f"[WARN] sfx file missing, skipping: {f}")
            continue
        inputs += ["-i", str(cand)]
        fc.append("[%d:a]adelay=%d:all=1,volume=0.7[s%d]"
                  % (n_in, int(span[0] * 1000), n_in))
        mix.append("[s%d]" % n_in)
        n_in += 1
    if len(mix) > 1:
        fc.append("".join(mix) +
                  "amix=inputs=%d:duration=first:normalize=0[aout]" % len(mix))
        amap = "[aout]"
    else:
        amap = "[acut]"

    cmd = inputs + ["-filter_complex", ";".join(fc),
                    "-map", "[vout]", "-map", amap, "-r", str(fps),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                    str(out_path)]
    proc = run(cmd)
    if proc.returncode != 0:
        print("[FAIL] ffmpeg render failed:")
        sys.stderr.write((proc.stderr or "")[-1500:] + "\n")
        sys.exit(1)
    n_text = len(doc.get("text", []))
    print(f"[OK] rendered {out_path} ({total:.1f}s, {len(keeps)} keeps, "
          f"{n_text} text events, {n_in - 1} sfx)")


if __name__ == "__main__":
    main()
