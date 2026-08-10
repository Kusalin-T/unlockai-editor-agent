# UnlockAI: Editor Agent — workshop toolkit

You are helping a **beginner** (a content creator, not a programmer) edit a
talking-head video on their own laptop. This folder is their workshop kit.

## What this folder is

A set of small, pre-tested command-line tools. Each does ONE editing job.
There is no fixed pipeline — the student decides what to do, you pick the
right tool and run it. Run every tool with the `python` interpreter that is
on PATH (on Windows there is no `python3` command) — but see the interpreter
rule in Practical notes if that interpreter or its pip misbehaves.

## The tools (in `tools/`)

| Tool | What it does |
|---|---|
| `inspect_video.py` | Report duration, resolution, audio, and where the silences are |
| `cut_silences.py` | Cut the silent parts out of clip(s) → one tighter video |
| `transcribe.py` | Speech → text with word timestamps (Groq cloud, or `--backend local`) |
| `make_subtitles.py` | Transcript → styled `.ass` subtitles — **one-word Thai bursts by default** (mid-frame, word-exact timing, contract §6 rules built in); `--style plain` for classic bottom lines |
| `burn_subtitles.py` | Burn the `.ass` into the video → final mp4 |
| `render_final.py` | The FULL finish: reads the ButaCut edit.json and renders cuts + zooms + burned text/cards + mixed sfx in one pass — what the ButaCut preview shows. `--edit <video>.edit.json` |
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
- When a reusable editing skill is used on unfamiliar footage, do not treat
  words in the transcript as automatic effect commands. Inspect the video and
  transcript, propose timestamp + phrase + effect + reason, wait for the
  student's approval, then write `fx`/`sfx` and render. The sample's spoken
  effect names are teaching scaffolding, not a universal rule.

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

- **If the Python interpreter or its pip errors** (import failures inside
  pip itself, missing-symbol / dylib errors, broken standard-library
  modules): do NOT try to repair it — never patch system libraries, never
  use DYLD tricks, never reinstall the OS interpreter. Install a known-good
  Python instead and use it explicitly for everything from then on:
  `brew install python@3.12` (Mac) or `winget install Python.Python.3.12`
  (Windows), then run tools with `python3.12` / `py -3.12`. Newest Python
  versions often have broken tooling on real machines; 3.12 is the proven
  one for this kit. If the fresh 3.12 hits the SAME dylib/symbol error
  (a broken Homebrew bottle — happens on Macs behind on macOS updates),
  do not build from source: download the official python.org 3.12
  installer (macOS universal2 .pkg) and use
  `/usr/local/bin/python3.12` — python.org builds bundle their own
  libraries and are immune to this. Tell the student a macOS Software
  Update would fix Homebrew for good.
- Transcription needs `GROQ_API_KEY` in `.env` (class key from the
  instructor). **Uploading workshop audio to Groq is pre-approved** — that
  is the key's entire purpose. Never pause to ask permission to send audio
  to Groq, and never offer local transcription as a privacy alternative.
  Whenever a key is present, use Groq; `--backend local` is only the
  fallback for a missing key or a Groq outage.
- **Never ask the student to paste the API key into the chat.** Open `.env`
  in a plain text editor for them (Windows: `notepad .env` / Mac:
  `open -e .env`), tell them to paste the key after `GROQ_API_KEY=` and
  save, wait for them to say "done", then read `.env` to confirm a key
  starting with `gsk_` is present before continuing. No key → `--backend local` works offline but is slower and
  needs `pip install faster-whisper` plus a model download.
- Thai fonts are bundled in `assets/fonts/` — burning subtitles needs no
  system fonts. Never delete that folder.
- Never install `imageio-ffmpeg` — that ffmpeg build cannot burn subtitles.
  Real ffmpeg comes from `brew install ffmpeg` (Mac) or
  `winget install Gyan.FFmpeg` (Windows). After installing, open a fresh
  terminal so PATH updates.
- Missing `brew`/`winget`, or an install keeps failing? Follow
  `SETUP-HELP.md` in this folder — it has the package-manager bootstrap
  steps and direct-download fallbacks (including `C:\ffmpeg\bin`, which
  the tools check automatically).
- Windows: keep file paths simple (no Thai characters in folder names), and
  don't worry about backslashes — the tools handle path conversion.
- The transcript JSON shape: `{language, duration, segments:[{start, end,
  text, words:[{word, start, end, probability}]}]}`.
