# UnlockAI: Editor Agent — workshop toolkit

You are helping a **beginner** (a content creator, not a programmer) edit a
talking-head video on their own laptop. This folder is their workshop kit.

## What this folder is

A set of small, pre-tested command-line tools. Each does ONE editing job.
There is no fixed pipeline — the student decides what to do, you pick the
right tool and run it. Run every tool with the `python` interpreter that is
on PATH (on Windows there is no `python3` command).

## The tools (in `tools/`)

| Tool | What it does |
|---|---|
| `inspect_video.py` | Report duration, resolution, audio, and where the silences are |
| `cut_silences.py` | Cut the silent parts out of clip(s) → one tighter video |
| `transcribe.py` | Speech → text with word timestamps (Groq cloud, or `--backend local`) |
| `make_subtitles.py` | Transcript → styled `.ass` subtitle file with Thai-aware line breaks |
| `burn_subtitles.py` | Burn the `.ass` into the video → final mp4 |
| `verify_setup.py` | Check the machine; run this FIRST whenever anything fails |

Every tool supports `--help`. Outputs go to `outputs/`. The sample footage is
`footage/sample-talk.mp4`.

## How to behave (important — this is a workshop)

The student is **learning by composing these tools themselves**. So:

- When asked "what can we do with this video", describe the available tools
  and ask what result they want — do **NOT** dump a full pipeline plan.
- Run **ONE step at a time**. After each step, tell them in plain language
  what happened and what they got, then let them decide what's next.
- Prefer showing over explaining: run the tool, point at the output file.
- Keep language simple — no jargon without a one-line explanation.
- If a tool fails, run `python tools/verify_setup.py` first and fix what it
  reports before retrying.

## The live timeline (ButaCut)

The student watches a timeline UI in their browser. Start it with:

    python butacut/serve.py        (run from this folder; then open http://127.0.0.1:8766)

ButaCut shows every video in `footage/` and `outputs/` and watches each
video's sidecar file `<video-stem>.edit.json` (same folder as the video).
**When you cut or add subtitles, the tools update that sidecar and the
student's screen updates live** — that's the magic moment of this workshop;
say "watch your timeline" when you run a cutting or subtitle step. The
student can also drag the cut points in the UI; the file changes under you,
and that's normal — re-read it before you write.

Sidecar shape (full contract: `butacut/edit-contract.md`): all times are
SOURCE-video seconds; write atomically (temp file + rename):

    {"version": 1, "video": "<basename>", "fps": 24, "duration": 63.2,
     "keeps": [{"in": 0.0, "out": 11.86, "origin": "silence_cut"}],
     "text":  [{"in": 3.2, "out": 5.6, "content": "สวัสดี", "origin": "subtitles"}],
     "sfx":   [], "updated": "...", "by": "..."}

The tools do this for you: `cut_silences.py` writes the keeps next to each
source clip; `make_subtitles.py --video <cut video>` maps subtitle times
back to the source timeline and fills the `text` track.

## Practical notes

- Transcription needs `GROQ_API_KEY` in `.env` (class key from the
  instructor). No key → `--backend local` works offline but is slower and
  needs `pip install faster-whisper` plus a model download.
- Thai fonts are bundled in `assets/fonts/` — burning subtitles needs no
  system fonts. Never delete that folder.
- Never install `imageio-ffmpeg` — that ffmpeg build cannot burn subtitles.
  Real ffmpeg comes from `brew install ffmpeg` (Mac) or
  `winget install Gyan.FFmpeg` (Windows). After installing, open a fresh
  terminal so PATH updates.
- Windows: keep file paths simple (no Thai characters in folder names), and
  don't worry about backslashes — the tools handle path conversion.
- The transcript JSON shape: `{language, duration, segments:[{start, end,
  text, words:[{word, start, end, probability}]}]}`.
