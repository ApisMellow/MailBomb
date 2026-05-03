# Voice Control — The Triage Accelerator

Voice control in the review UI is not a gimmick. When you are staring down
10,000 senders to sort into keep/trash/rule, saying **"toss, toss, keep, toss,
rule"** is measurably faster — and less stressful on your hands — than
clicking or even hitting keyboard shortcuts. This document explains what it
can do, what it needs, and how to drive it well.

## Why voice matters for this workflow

Triaging a large mailbox is the kind of task that gets abandoned halfway
through because the user's wrists give out or their attention wanders. The
review UI is deliberately designed as a one-card-at-a-time flow so that:

- You only have to decide about one sender at a time.
- You only have to say one word to move on.
- Your eyes can stay on the sender card — the subject samples, the snippet,
  the size — without your hands leaving anywhere in particular.

Speaking is faster than clicking when each decision is a single word, and
continuous speech recognition means you keep flow state across hundreds of
cards in a row.

## Requirements

- A Chromium-based browser (Chrome, Edge, Brave, etc.). The UI uses the
  **Web Speech API** (`window.SpeechRecognition` / `webkitSpeechRecognition`);
  see `mailbomb/templates/review.html` around the `setupVoice` function.
- A working microphone and OS-level mic permission for the browser.
- The MailBomb review server running locally (`mailbomb review`), which
  serves the UI at `http://localhost:5050` by default.

Safari and Firefox currently have partial or no Web Speech support. If your
browser lacks it, the mic button will display **"No mic support"**, and the
rest of the UI still works with keyboard shortcuts.

## Turning it on

1. Run `mailbomb review` in your terminal.
2. When the browser opens, click the **mic icon** in the header (top right of
   the review page).
3. Your browser will ask for microphone permission — approve it.
4. The indicator turns green and the label changes to **Listening**.

The mic stays on continuously: as soon as one utterance finishes, recognition
restarts automatically, so you can just keep talking at your own pace.

## The command vocabulary

Each phrase below is matched as a substring of what you said. You don't have
to say the word in isolation — "toss it" works as well as "toss".

| Say | Action |
|---|---|
| `toss` *or* `trash` | Move all messages from the current sender to Gmail Trash |
| `keep` | Mark sender as reviewed, leave their mail alone |
| `skip` *or* `next` | Come back to this sender later |
| `rule` | Trash *and* create a permanent rule for this sender/list |
| `show` *or* `full` | Open the full-message overlay for the current sample |
| `back` *or* `previous` | Go to the previous card |
| `forward` | Advance to the next card without dispositioning |
| `close` | Dismiss any open overlay |
| `quit` *or* `done` *or* `stop` *or* `end` | Jump to the session summary screen |

Source: `mailbomb/templates/review.html` — the `recognition.onresult` handler.

All of the same actions are also bound to keyboard shortcuts:

| Key | Action |
|---|---|
| `T` | Trash |
| `K` | Keep |
| `S` | Skip |
| `R` | Rule |
| `F` | Show full message |
| `Q` | Quit / session summary |

You can mix voice and keyboard freely in the same session.

## Feedback — how you know it heard you

- **Green "Heard: ..."** pill at the bottom of the card with a soft beep
  confirms a matched command.
- **Red "Didn't understand: ..."** pill with a buzz indicates the utterance
  came through cleanly but didn't match any known command. Check the
  transcript and try again.
- The **mic dot** pulses while the browser is actively listening.

The buzz-vs-beep distinction matters: it tells you whether the problem is
recognition (you need to enunciate) or vocabulary (you used a word MailBomb
doesn't know).

## Safety notes for voice

Voice commands are not bypasses — every voice-triggered action calls the same
HTTP endpoint (`/api/trash`, `/api/rule`, etc.) that the on-screen buttons
call. Specifically:

- `toss` / `rule` both **trash, not permanently delete**. The review UI has no
  permanent-delete path at all. Messages go to Gmail Trash and are recoverable
  for 30 days. See [safety.md](safety.md).
- The session tracks every voice-trashed message ID. The session summary
  screen (`quit` / `Q`) lets you restore individual messages from trash before
  closing the session.

So if you misspeak and say "toss" when you meant "keep", you can recover. But
stay deliberate — the whole point of voice is that it is fast, and fast means
you can sort 500 senders before you notice a mistake.

## Tips for a good session

- **Work in a quiet room.** Continuous recognition picks up background
  conversation and can misfire on "keep" vs. "next".
- **Pause between commands.** Let the green pill appear before issuing the
  next command. Each `onresult` event resolves on a final transcript, so
  rushing does not help.
- **Use `skip` liberally.** If a sender isn't an obvious yes/no, `skip`. Come
  back with fresher eyes.
- **`rule` for recurring junk.** Once you've decided a sender is never worth
  keeping, `rule` stores it so future scans can auto-flag them.
- **Turn the mic off when you walk away.** Voice stays on across tab focus
  changes. Click the mic indicator to stop listening before lunch.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Mic label says "No mic support" | Browser lacks Web Speech API | Use Chrome/Edge |
| Mic label stays on "Mic off" | Browser denied mic permission | Re-enable in browser settings |
| Green indicator but no response | Recognition hit the quiet-timeout and the `onend` handler is restarting it | Wait one second and try again |
| Everything buzzes red | Recognition is working but phrasing is off | Say a single vocabulary word, clearly |
| Browser freezes when switching tabs | Known quirk with long-running continuous recognition | Toggle the mic off and back on |

## Scope

Voice only operates inside the review UI. It does not affect the CLI, does not
trigger scans, and does not interact with any command outside the vocabulary
listed above.
