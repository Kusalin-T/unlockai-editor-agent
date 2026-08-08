# UnlockAI: Editor Agent — prompt registry

Copy-paste these into your agent (Claude Desktop or Codex) exactly as written.
They work the same on Mac and Windows — the agent figures out your machine's
details itself. Numbers match the workshop slides.

> Rule of thumb: **paste the prompt, watch ButaCut, then direct in your own
> words** ("tighter", "bigger", "undo that"). You never need to write code.

---

## Core pipeline (the workshop spine)

**Prompt 1 — Setup** *(slide 9 — the magic prompt; full text in README.md)*
Sets up Python + ffmpeg + this folder, then starts ButaCut and opens it in your
browser. If it asks questions, answer yes.

**Prompt 2 — Cut** *(slide 18)*
> Look at the tools in this folder. I want to cut the silent parts from the sample video — which tool does that? Run it.

**Prompt 3 — Transcribe** *(slide 21)*
> Now I need the words. Transcribe the cut video.

**Prompt 4 — Subtitles** *(slide 22)*
> Turn the transcript into subtitles.

**Prompt 5 — Burn** *(slide 23)*
> Burn the subtitles into the video. Give me the final file.

**Prompt 6 — Make it a skill** *(slide 25)*
> Save the pipeline we just ran as a reusable skill: write a file that records the steps, tools, and my preferred settings, so next time I only have to say "edit this video".

**Prompt 7 — Use the skill** *(slide 26)*
> Edit the sample video with my skill.

**Prompt 8 — Your own video** *(slide 29)*
> Edit the video I just added with my skill.

**Fix-it prompt** *(slide 14 — whenever anything breaks)*
> Here is the error: [paste]. Fix it, then run the setup check again and show me the result.

---

## Level up (free-experiment block — these are how the pros' edits feel)

**Prompt 10 — One-word burst subtitles**
> Change my subtitles into one-word bursts — one big word at a time, centered on the video, timed to exactly when I say each word. Use the real word timestamps from the transcript (never guess or spread timings evenly), and follow the burst rules in butacut/edit-contract.md section 6. Update the project file so I can see and adjust every word in ButaCut.

**Prompt 11 — Effects when I call them**
> Listen to my transcript for the moments where I SAY an effect name — "zoom in", "zoom out", "whoosh", "sound effect", "pop up". Make each effect actually happen at the exact moment I say its word: zoom in should ease in about half a second and HOLD until I say zoom out; add a matching sound for each moment (sound files are in assets). The rules are in butacut/edit-contract.md section 6. Write it all into the project file so the effects show on the ButaCut timeline and I can drag them.

**Prompt 12 — Cut my flubbed takes**
> When I mess up a line I repeat the same word or phrase. Find every place in the transcript where I say the same thing two or more times in a row, keep only the LAST one, and cut the earlier ones (rules in butacut/edit-contract.md section 6). Show me in ButaCut what you cut — I'll restore anything you got wrong.

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
