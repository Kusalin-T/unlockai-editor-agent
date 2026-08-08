# ButaCut edit contract — v1 (2026-08-08)

The interface between **ButaCut** (the review UI) and **any editing agent** (student tools,
Claude, pipeline scripts) is a JSON sidecar file. Agents write it; ButaCut displays it, lets a
human adjust cuts, and writes it back. Nothing else is shared — no imports, no API, no sockets.
If your tool emits this file correctly, it works with ButaCut.

## 1. File pairing & discovery

For a video `myvideo.mp4`, the edit sidecar is **`myvideo.edit.json` in the same directory**.

ButaCut scans the directories listed in `butacut.config.json` (`media_dirs`; default: the
current working directory and `./media`) for `*.mp4` / `*.mov` / `*.m4v`, non-recursive.
A video without a sidecar is shown as an identity edit (everything kept). Creating or
modifying the sidecar externally is normal operation — ButaCut polls the file's mtime
(~500 ms) and re-renders when it changes.

Optional extra: if `myvideo.boundaries.json` exists (production pipeline format:
`{"clips":[{"source","start","end"}]}`), ButaCut shows a read-only clip-labels track.

## 2. edit.json schema

```json
{
  "version": 1,
  "video": "myvideo.mp4",
  "fps": 24,
  "duration": 63.2,
  "keeps": [
    { "in": 0.0,  "out": 11.86, "origin": "silence_cut" },
    { "in": 13.7, "out": 42.0,  "origin": "agent" }
  ],
  "text": [
    { "in": 3.2, "out": 5.6, "content": "สวัสดีครับ", "origin": "agent" }
  ],
  "sfx": [
    { "at": 12.1, "file": "sfx/pop.wav", "origin": "agent" }
  ],
  "updated": "2026-08-08T17:20:00",
  "by": "student-agent-01"
}
```

Field rules:

| Field | Rules |
|---|---|
| `version` | integer, currently `1`. |
| `video` | filename of the sibling video (basename only). |
| `fps` | optional int, output frame rate for renderers (default 24). |
| `duration` | optional float seconds; informational. ButaCut trusts the actual media. |
| `keeps` | ranges of the SOURCE video that survive, **in source seconds**, sorted, non-overlapping, `out > in`. Missing/empty = keep everything. Everything not covered by a keep is cut. |
| `text` | text overlays, timed **in source seconds** (they survive cut changes). Optional `pos`: `"top"` or `"bottom"` (default bottom) — ButaCut's viewer preview honors it. The preview can be toggled off in the UI (for videos with burned-in captions); renderers burn text for real. |
| `sfx` | sound events at a **source-seconds** timestamp. `file` is relative to the repo root. Display-only in ButaCut v1; renderers mix them. |
| `fx` | motion + infographic events, **in source seconds**. ButaCut simulates them live in the viewer and shows them as a retimeable track. Kinds: `zoom-drift` `{in,out,base,wobble,punch}` (scale = base + sin(t·0.5)·wobble + punch decaying 0.5s after each caption start — mirrors the shorts renderer); `card` `{in,out,label,border,y}`; `chips` `{in,out,items:[{text,color}],y}`; `stats` `{in,out,items:[[emoji,big,small],…],y}`; `image` `{in,out,file,x,yf,w}` (pre-rendered overlay, fractions of frame). `y` values are in 1080-wide render pixels. |
| `origin` | who created this entry: `"silence_cut"`, `"agent"`, `"user"`, or your tool's name. ButaCut sets `"user"` on ranges a human adjusted. |
| `updated`, `by` | optional provenance; set them when you write. |

All times are floats in **seconds on the source-video timeline** — never on the output
timeline. That way text/sfx/fx keep their meaning when cuts change.

Asset paths (`sfx[].file`, `fx[].file`) are relative to the repo root and are served by
ButaCut at `/asset/<path>` (audio + images only, root-contained). SFX audio plays live
during preview; the caption/fx toggle in the transport hides all simulated layers at once.

## 3. Writing rules (multi-writer safety)

1. **Write atomically**: write to a temp file in the same directory, then rename over
   `*.edit.json` (`os.replace`). Never write the file incrementally in place.
2. **Last write wins.** ButaCut saves ~0.6 s after a human edit; your agent may overwrite
   later — that's allowed. Don't hold the file open.
   As of v1.1 the ButaCut UI writes back **`keeps`, `text`, and `sfx`** (humans can retime,
   move, edit and delete text/sfx in the UI; modified entries get `origin: "user"`). Agents
   co-own those arrays — re-read the file before regenerating it, and prefer *adding/updating
   your own entries* over wholesale rewrites so human tweaks survive. Unknown fields are
   preserved by both sides.
3. Readers must **tolerate a mid-write/invalid file**: keep the previous state and retry on
   the next poll. ButaCut does this; your tools should too.
4. Don't reformat times beyond 3 decimal places; keep the file human-diffable
   (`indent=2`, `ensure_ascii=False`).

## 4. Render contract

ButaCut's **Apply** button opens an **agent handoff modal** by default: a copy-paste prompt
(template: `agent_prompt` in `butacut.config.json`, placeholders `{video}` `{edit}`
`{output}`) that instructs an AI agent to render the edit with the real pipeline
(e.g. Remotion) so the result matches the preview, then reveal the file. The modal's
"Rough cut only" button runs a render directly instead:

- **Default (no config):** built-in ffmpeg render — concatenates the `keeps` ranges,
  re-encoded CFR at `fps`, H.264 + AAC, to `<stem>-cut.mp4` next to the source.
  It ignores `text` and `sfx` (cut preview only).
- **Pluggable (classroom mode):** set `render_cmd` in `butacut.config.json`:

```json
{
  "media_dirs": ["media"],
  "render_cmd": ["python", "tools/render.py", "--edit", "{edit}", "--out", "{output}"]
}
```

Placeholders substituted by ButaCut: `{video}` (source path), `{edit}` (edit.json path),
`{output}` (suggested output path `<stem>-cut.mp4`). Your renderer must: read the edit.json,
produce the output file, exit 0 on success (non-zero + stderr on failure — ButaCut shows it).

Renderer implementation notes (Windows-safe): find ffmpeg with `shutil.which`, pass paths
with `pathlib` and use `.as_posix()` for any path embedded **inside a filter string**
(e.g. `subtitles=`), keep console output ASCII.

## 5. Minimal writer example (python, stdlib only)

```python
import json, os, tempfile
from pathlib import Path

def write_edit(video: Path, keeps, text=(), sfx=(), by="my-agent"):
    doc = {"version": 1, "video": video.name,
           "keeps": [{"in": round(a, 3), "out": round(b, 3), "origin": by} for a, b in keeps],
           "text": list(text), "sfx": list(sfx), "by": by}
    target = video.with_name(video.stem + ".edit.json")
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, target)   # atomic
```

## 6. House editing defaults (decided 2026-08-08 — implement these unless told otherwise)

These are the tuned parameters and semantics from the owner's editing sessions. Any tool or
agent producing edit.json should follow them; they are what makes the edit "feel right".

**Silence cutting (tight profile)**
- Auto-calibrate the noise floor: try −46 dB first, step through −42/−38/−34/−30/−26 until
  real pauses appear; in tight mode go one step past the first hit as long as total silence
  stays under 50% of the clip. Phone recordings with room tone need −30 to −38.
- min silence 0.2 s · keep-margin 0.02 s · min speech 0.5 s (0.35 s tight).
- Never let a cut eat a spoken word: every transcript word's onset must fall inside a keep.

**Word-burst subtitles (`style:"burst"`, `pos:"mid"`)**
- Source of truth = whisper word timestamps. Tokenize Thai with pythainlp `newmm` when
  available, anchoring each token's time to the real fragment times (never proportional).
- Folding rules: never merge across a speech gap ≥ 0.35 s; a burst must never start with a
  Thai combining mark (fold it into the previous burst); minimum burst duration 0.16 s;
  bursts must not overlap (clip `out` to the next burst's `in`).

**Repeated-word mistakes ("พูดซ้ำ")**
- Consecutive identical tokens (normalized: lowercase, strip punctuation; ≥ 2 chars;
  within 2.5 s of each other) are a retake — **keep the LAST occurrence, cut the earlier
  ones** (pad 0.05 s before the first, end the cut 0.03 s before the survivor).

**Zoom semantics (`fx` kind `zoom`)**
- Picture is FLAT (scale 1.0) by default — no ambient drift unless explicitly asked.
- A zoom event ramps with an ease-out over ~0.5 s to `to`, then **HOLDS** until its `out`.
- "Zoom in … zoom out" = two paired events: in→1.3 hold, then 1.3→1.0 release.
- Zoom applies to the video layer only; text/fx overlays stay unzoomed. The viewport frame
  never changes size — the content scales inside it.

**Keyword-triggered effects**
- When the speaker names an effect, fire it AT that word's start time (from word
  timestamps): "zoom in/out" → paired zoom events (+whoosh sfx), "whoosh" → whoosh sfx,
  "sound effect" → ding, "pop up" → card fx + pop sfx.

**Multi-writer etiquette (recap)**
- Atomic writes; re-read before regenerating; update your own entries instead of wholesale
  rewrites; preserve fields you don't understand; keeps/text/sfx/fx you didn't author may
  have been human-tuned (`origin:"user"`) — don't regress them.

## 7. Compatibility

- ButaCut also reads the legacy `{"drops": [[in, out], ...]}` form (complement of keeps)
  and converts it; new writers must emit `keeps`.
- Schema changes bump `version`; v1 readers ignore unknown fields — additive fields are safe.
