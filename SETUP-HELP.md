# Setup help — when the normal install path fails

For the AI agent (and humans) fixing a machine that can't follow the main
setup prompt. Work top-to-bottom inside the failing section; after any fix,
re-run `python tools/verify_setup.py`.

## Mac: Homebrew is not installed

1. Install it (asks for the user's password; also installs Apple's command
   line tools automatically — that part can take several minutes):

   ```
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```

2. After installing, activate it in the current shell (Apple Silicon):

   ```
   eval "$(/opt/homebrew/bin/brew shellenv)"
   ```

3. Then: `brew install ffmpeg python@3.12`
4. **Fallback if the installer fails** (network/permission problems): open
   https://brew.sh in the browser for the human, and while they read it, use
   the no-Homebrew route below.

### Mac without Homebrew at all (last resort)

- Python: open https://www.python.org/downloads/ — the human downloads and
  runs the macOS installer (3.12+), then use `python3` from a fresh shell.
- ffmpeg: no reliable no-brew build with subtitle support — prefer fixing
  Homebrew. If truly stuck, pair the student with a neighbor's machine for
  the render step.

## Windows: winget is not installed / not recognized / hangs

Do NOT stop to install winget — nothing in this workshop needs winget
itself, only the two things it would have installed. Skip it and install
those directly:

1. **ffmpeg**: download https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip ,
   extract it, and copy the archive's inner `bin` folder to `C:\ffmpeg\bin`
   (so `C:\ffmpeg\bin\ffmpeg.exe` exists). The workshop tools look there
   automatically — no PATH editing needed.
2. **Python**: download the official 3.12 installer from
   https://www.python.org/downloads/windows/ and run it with
   `/quiet PrependPath=1` (or the human runs it and MUST tick
   "Add python.exe to PATH"). Then open a NEW terminal.

Last resort only (direct downloads blocked, e.g. a managed machine):
install "App Installer" from the Microsoft Store —
`start ms-windows-store://pdp/?ProductId=9NBLGGH4NNS1` or
https://aka.ms/getwinget — open a NEW terminal, then retry `winget`.

## Either OS: installed, but a fresh shell still can't find it

- Close ALL terminal windows and open a new one (PATH updates only apply to
  new shells). In agent apps, start a new command rather than reusing an
  old shell session.
- Windows: `where ffmpeg` / Mac: `which ffmpeg` to confirm.
- The tools also self-locate ffmpeg in the usual install folders even when
  PATH is stale — run `python tools/verify_setup.py` to see what they find.

## Still stuck

Copy the full error output into the agent chat with:
"Here is the error: [paste]. Fix it, then run python tools/verify_setup.py
and show me the result."
