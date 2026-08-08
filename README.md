# UnlockAI: Editor Agent — workshop kit

Edit talking-head videos with an AI agent: cut the silences, transcribe the
speech, and burn Thai subtitles — all by talking to Claude (or Codex) on your
own laptop.

This is the student kit for the **UnlockAI: Editor Agent** workshop by
[@butabuilds](https://www.instagram.com/butabuilds/).

## Quick start (the whole setup is one prompt)

1. Install the **Claude Desktop app** (Claude Pro) or the **Codex app**
   (ChatGPT Plus) and allow it to access files and run commands when it asks.
2. Paste this into a new conversation — then let the agent work. It will ask
   for your password when it installs things; that's normal.

```text
You are setting up my computer for a video-editing workshop. Do everything
yourself; only ask me when you need a choice or a password. Steps:

1. Detect my operating system, then check the package manager exists:
   - Mac: if "brew" is missing, install Homebrew with its official
     installer script (it will ask for my password), then activate it:
     eval "$(/opt/homebrew/bin/brew shellenv)"
   - Windows: if "winget" is missing, open the Microsoft Store page
     ms-windows-store://pdp/?ProductId=9NBLGGH4NNS1 for me to install
     "App Installer", then use a NEW terminal.
   If bootstrapping fails, read
   https://raw.githubusercontent.com/Kusalin-T/unlockai-editor-agent/main/SETUP-HELP.md
   and follow its direct-download fallbacks; as a last resort open the
   relevant download page in my browser so I can install it by hand.
2. Make sure real ffmpeg is installed:
   - Mac: brew install ffmpeg
   - Windows: winget install Gyan.FFmpeg
   Never install imageio-ffmpeg or any "python ffmpeg" package — those
   builds cannot burn subtitles. After installing, use a fresh shell so
   PATH updates apply.
3. Make sure Python 3.11+ is installed:
   - Mac: brew install python@3.12
   - Windows: winget install Python.Python.3.12
4. Download https://github.com/Kusalin-T/unlockai-editor-agent/archive/refs/heads/main.zip
   and unzip it into a folder called "workshop" in my Documents folder.
   Work inside that folder from now on.
5. Install the Python packages: python -m pip install -r requirements.txt
6. Copy .env.example to .env and put in the API key I give you
   (GROQ_API_KEY=...). Ask me for the key now.
7. Run: python tools/verify_setup.py — and fix anything that fails.
8. Start the timeline UI in the background: python butacut/serve.py
   — then open http://127.0.0.1:8766 in my default browser.
9. When every check passes, say "READY" and show me the check output.
```

3. When your agent says **READY**, you're done. In the workshop you'll also
   start the timeline UI (ButaCut) — your agent knows how.

## What's inside

```
tools/            the editing tools (each does one job — run with --help)
footage/          sample-talk.mp4 — the practice clip
assets/fonts/     Thai fonts, bundled so subtitles render on any machine
outputs/          everything you produce lands here
butacut/          the live timeline UI
AGENTS.md         instructions your AI agent reads automatically
```

## Manual setup (fallback, if the prompt route fails)

<details>
<summary>Click to expand</summary>

**Mac**
1. Install Homebrew: https://brew.sh
2. `brew install ffmpeg python@3.12`
3. Download + unzip this repo (green "Code" button → Download ZIP)
4. In Terminal, `cd` into the folder, then:
   `python3 -m pip install -r requirements.txt`
5. `cp .env.example .env` and put your key in `.env`
6. `python3 tools/verify_setup.py`

**Windows**
1. In PowerShell: `winget install Gyan.FFmpeg` and
   `winget install Python.Python.3.12`
2. Close PowerShell, open a NEW one (PATH updates)
3. Download + unzip this repo (green "Code" button → Download ZIP) — unzip
   to a simple path like `Documents\workshop`
4. `cd` into the folder, then: `python -m pip install -r requirements.txt`
5. `copy .env.example .env` and put your key in `.env` (edit with Notepad)
6. `python tools\verify_setup.py`

</details>

## Transcription: free vs better

- **Workshop default**: Groq cloud Whisper — free tier, fast. The class key
  dies after the workshop; make your own free key at
  https://console.groq.com → API Keys, and put it in `.env`.
- **No key at all**: `python tools/transcribe.py <video> --backend local`
  runs Whisper on your machine (needs `pip install faster-whisper`; first
  run downloads a few hundred MB).
- **Better quality**: bigger/paid transcription APIs exist — ask your agent
  to swap the backend when you're ready.

## The one rule

If anything breaks: `python tools/verify_setup.py` — then paste the whole
output to your agent and say "fix this."
