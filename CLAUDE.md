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

The student has a timeline UI open in their browser (ButaCut). It watches the
project file `outputs/<video>.edit.json` — **whenever you cut or add
subtitles, the tools update that file and the student's screen updates
live**. That's the magic moment of this workshop; mention it ("watch your
timeline") when you run a cutting or subtitle step. If you modify
`edit.json` yourself, keep its shape: `{source, fps, keeps:[{in, out,
origin}], text:[...], sfx:[...]}` and write it atomically (full valid JSON).

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
