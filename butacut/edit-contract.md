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
| `text` | text overlays, timed **in source seconds** (they survive cut changes). Display-only in ButaCut v1; renderers burn them. |
| `sfx` | sound events at a **source-seconds** timestamp. `file` is relative to the repo root. Display-only in ButaCut v1; renderers mix them. |
| `origin` | who created this entry: `"silence_cut"`, `"agent"`, `"user"`, or your tool's name. ButaCut sets `"user"` on ranges a human adjusted. |
| `updated`, `by` | optional provenance; set them when you write. |

All times are floats in **seconds on the source-video timeline** — never on the output
timeline. That way text/sfx keep their meaning when cuts change.

## 3. Writing rules (multi-writer safety)

1. **Write atomically**: write to a temp file in the same directory, then rename over
   `*.edit.json` (`os.replace`). Never write the file incrementally in place.
2. **Last write wins.** ButaCut saves ~0.6 s after a human edit; your agent may overwrite
   later — that's allowed. Don't hold the file open.
3. Readers must **tolerate a mid-write/invalid file**: keep the previous state and retry on
   the next poll. ButaCut does this; your tools should too.
4. Don't reformat times beyond 3 decimal places; keep the file human-diffable
   (`indent=2`, `ensure_ascii=False`).

## 4. Render contract

ButaCut's **Apply** button runs a render:

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

## 6. Compatibility

- ButaCut also reads the legacy `{"drops": [[in, out], ...]}` form (complement of keeps)
  and converts it; new writers must emit `keeps`.
- Schema changes bump `version`; v1 readers ignore unknown fields — additive fields are safe.
