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
> Turn the transcript into subtitles — normal readable phrases (plain style), not one-word bursts.

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
*(bursts are now `make_subtitles.py`'s default — Prompt 4 already gives you
this. Use this prompt if your subtitles came out as lines, or to rebuild.)*
> Remake my subtitles as one-word bursts — one big word at a time, centered, timed to exactly when I say each word. Use the built-in burst style: run the subtitles tool with --style burst on my transcript, then burn a new video. The rules are built into the tool — verify them, don't reinvent: timings come from the real transcript word timestamps (never spread evenly), bursts never overlap, none shorter than 0.16s, and no burst starts with a Thai vowel or tone mark. Update the project file so I can see every word in ButaCut, and give me the new burned file.

**Prompt 11 — Effects when I call them**
> Read my transcript and find every moment where I SAY an effect name: "zoom in", "zoom out", "whoosh", "sound effect", "pop up". Write fx/sfx events into the project file (edit.json) exactly per section 6 of butacut/edit-contract.md: each event fires at that word's start timestamp. "Zoom in" ramps ease-out over ~0.5s to 1.3x and HOLDS until I say "zoom out", which releases back to 1.0 — pair them, and add the whoosh sound to both. "Whoosh" plays assets/sfx/whoosh.mp3, "sound effect" plays assets/sfx/ding.mp3, "pop up" is a card pop-up plus assets/sfx/pop.mp3. Zoom scales only the video — subtitles stay unzoomed. Show me the events on the ButaCut timeline before rendering anything.

**Prompt 12 — Cut my flubbed takes**
> When I mess up a line I repeat the same word or phrase. Find every repeated take in my transcript: consecutive identical words or phrases (ignore case and punctuation, at least 2 characters, repeats within 2.5 seconds of each other). Keep only the LAST occurrence and cut the earlier ones by updating the keeps in the project file, per section 6 of butacut/edit-contract.md: pad the cut 0.05s before the flubbed take, end it 0.03s before the kept take, and never let a cut eat a word that stays in. List every cut you made with its timestamp — I'll restore anything you got wrong in ButaCut.

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
