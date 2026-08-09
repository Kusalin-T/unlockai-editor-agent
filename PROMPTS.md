# UnlockAI: Editor Agent — prompt registry

Copy-paste these into your agent (Claude Desktop or Codex) exactly as written.
They work the same on Mac and Windows — the agent figures out your machine's
details itself. Numbers match the workshop slides.

> Rule of thumb: **paste the prompt, watch ButaCut, then direct in your own
> words** ("tighter", "bigger", "undo that"). You never need to write code.

---

## Core pipeline (the workshop spine)

**Prompt 1 — Setup** *(the magic prompt; full text in README.md)*
Sets up Python + ffmpeg + this folder, then starts ButaCut and opens it in your
browser. If it asks questions, answer yes.

**Prompt 2 — Hear the words (transcribe)**
> I want to edit the sample video. First, get me the words: transcribe the sample video so every word has its exact time. Use Groq cloud transcription with the key in .env — I approve uploading the audio to Groq, so don't stop to ask.

**Prompt 3 — Cut the silences**
> Look at the tools in this folder. I want to cut the silent parts from the sample video — which tool does that? Run it.

**Prompt 3b — Cut tighter** *(optional — only if the first cut kept noise or left long pauses)*
> The silence cut isn't tight enough: it counted some background noise as me talking, and it left the pauses too long. Run the silence-cut tool again with stricter settings — raise --threshold one step so background noise counts as silence, and lower --min-silence to 0.2 so shorter pauses get cut too. Replace the previous cut and tell me the before/after duration — I'll check the timeline in ButaCut.

**Prompt 4 — Cut the mistakes (repeated takes)**
> When I mess up a line I repeat the same word or phrase. Find every repeated take in my transcript: consecutive identical words or phrases (ignore case and punctuation, at least 2 characters, repeats within 2.5 seconds of each other). Keep only the LAST occurrence and cut the earlier ones by updating the keeps in the project file, per section 6 of butacut/edit-contract.md: pad the cut 0.05s before the flubbed take, end it 0.03s before the kept take, and never let a cut eat a word that stays in. List every cut you made with its timestamp — I'll restore anything you got wrong in ButaCut.

**Prompt 5 — One-word burst subtitles**
> Turn the transcript into subtitles — one big word at a time, timed to exactly when I say each word (the burst style, the tool's default).

**Prompt 6 — Effects when I call them**
> Read my transcript and find every moment where I SAY an effect name: "zoom in", "zoom out", "whoosh", "sound effect", "pop up". Write fx/sfx events into the project file (edit.json) exactly per section 6 of butacut/edit-contract.md: each event fires at that word's start timestamp. "Zoom in" ramps ease-out over ~0.5s to 1.3x and HOLDS until I say "zoom out", which releases back to 1.0 — pair them, and add the whoosh sound to both. "Whoosh" plays assets/sfx/whoosh.mp3, "sound effect" plays assets/sfx/ding.mp3, "pop up" is a card pop-up plus assets/sfx/pop.mp3. Zoom scales only the video — subtitles stay unzoomed. Show me the events on the ButaCut timeline before rendering anything.

**Prompt 7 — Review the cut (fix & iterate, then the retro)**
*(first: watch your whole cut in ButaCut and fix anything that bugs you — drag it in ButaCut or tell your agent in your own words. When you're happy, paste this.)*
> I just finished fixing my first cut — I made changes in ButaCut and asked you for corrections in this chat. Re-read the project file (edit.json), compare it with what you originally wrote, and go back through my corrections. List every issue I had to fix, then identify the RECURRING ones and the exact fix that worked for each (example: a subtitle staying on screen after the word is already finished → end each subtitle at the word's end timestamp, not at the next word's start). Save the recurring issues and their fixes to review-notes.md — we'll bake them into my skill next.

**Prompt 8 — Make it a skill**
> Save the pipeline we just ran as a reusable skill named butabuilds-editor-skill. Look back through this whole conversation and collect every step we ran, every preference I stated, and every correction I made along the way — those are my editing preferences. Write them into the skill file together with the tools, the settings that worked, and the recurring fixes from review-notes.md, so next time I only have to say "edit this video".

**Prompt 8b — Make effects intentional** *(update the skill for real videos)*
> Update butabuilds-editor-skill so it chooses effects intelligently for real videos instead of only adding them when the transcript literally says an effect name. Add an effect-planning checkpoint after transcription, cuts, and subtitles but before any fx/sfx are written: read the transcript and propose a short plan for where zoom in, zoom out, whoosh, sound effect, or pop up would strengthen emphasis, pacing, or clarity. For each suggestion, show the timestamp, the transcript phrase, the effect, and one short reason. Use effects sparingly; it is okay to suggest none. Show me the plan and wait for my approval or changes. Only after I approve may you write the effects to edit.json and render. Save this rule in the skill.

**Prompt 9 — Use the skill**
> delete the final version. now edit the sample video again with butabuilds-editor-skill

**Prompt 10 — Your own video**
> [video path] edit this video with butabuilds-editor-skill

## Extra Homework — Add the Remotion layer

> Upgrade this workshop project with a separate Remotion workspace. Preserve every existing ButaCut, Python, footage, skill, and output file; do not replace the current workflow.
>
> 1. Detect my operating system and architecture. Check node, npm, and npx. If any are missing, install the current Node.js LTS (not Current) from official sources only: on Mac use Homebrew or the official Node installer; on Windows use "winget install OpenJS.NodeJS.LTS" or the official nodejs.org MSI. Open a fresh shell and verify all three versions.
> 2. From the current project root, create "remotion-studio" with:
>    npx create-video@latest --yes --blank --no-tailwind remotion-studio
>    Keep it inside this project and do not create or keep a nested Git repository.
> 3. Install the official Remotion skill at project scope:
>    npx skills add remotion-dev/skills --skill remotion-best-practices
>    Choose the agent I am using if prompted.
> 4. Configure a vertical starter composition named CreatorVideo at 1080x1920, 30fps, with public/media, src/components, src/compositions, and out folders. Add scripts for Remotion Studio, a one-frame still, a full render, and typecheck. Use frame-driven Remotion animation, not CSS animation.
> 5. Add a rule to butabuilds-editor-skill: keep transcription and cut decisions in ButaCut/FFmpeg; use Remotion for captions, motion graphics, overlays, compositing, and final rendering when it improves the result. Before rendering, show which layer each tool will handle and wait for my approval.
> 6. Install dependencies, run typecheck, render a still to out/setup-check.png, start Remotion Studio in the background, open it in my browser, and say READY only when every check passes. Show the versions, paths, and check results.

**Fix-it prompt** *(whenever anything breaks)*
> Here is the error: [paste]. Fix it, then run the setup check again and show me the result.

---

## Level up (free-experiment block)

**Prompt 13 — Finish**
Click **Apply cut** in ButaCut → it shows a prompt written for your project →
copy it → paste it to your agent. It renders the final video and opens it.

---

## The director's phrasebook (type these in your own words, anytime)

- "Leave more breathing room" · "Cut harder"
- "That cut at [time] is wrong — put it back"
- "Subtitles bigger / higher / lower"
- "Move that whoosh half a second later"
- "Undo that" · "Show me before and after"

Your agent re-reads the project file before every change and never touches your
original footage — everything is reversible, so direct boldly.
