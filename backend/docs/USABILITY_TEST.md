# Fieldbase Usability Test — Can they use it without being taught?

A 30-minute moderated think-aloud session to find out whether a coordinator or an
enumerator — seeing Fieldbase for the first time, with **no walkthrough** — can build
the right mental model and get real work done.

| | |
|---|---|
| **Length** | ~30 min per participant |
| **Participants** | 1 coordinator + 1 enumerator (minimum) |
| **Team** | Facilitator (talks) + notetaker (silent, scores) |
| **Method** | Think-aloud, task-based |
| **Where** | Staging, with seeded data |

There is a printable, run-from-the-page version of this script as a Claude artifact
(single-session link, shareable from its own menu). This file is the versioned copy.

---

## The one thing we're measuring

Everything below rolls up to a single question: **does the product teach itself, or does
it lean on someone explaining it?** You are not testing whether the participant is smart —
you're testing whether Fieldbase makes its model discoverable on its own:

> collect in ODK Collect → sync → **endorse** (Gate 1) → **validate** (Gate 2) → **approved**

**The moment you have to explain something is a finding, not a failure.** Write down the
exact sentence you used — that sentence belongs in the product.

---

## 1. Before you run it

- **Fresh account per participant.** Use a brand-new login on staging so the
  getting-started checklist and the first-run tour actually appear (they hide after first use).
- **Seed realistic data:**
  - Coordinator's project: a handful of synced submissions — some clean, **at least one with a
    flagged issue**, **at least one already endorsed and awaiting validation**.
  - Enumerator: a few assignments (**one overdue**) and **one flagged submission of their own**.
- **Two people.** Facilitator talks; notetaker stays silent and scores. Record screen + audio
  with consent.
- **Don't demo first.** No tour from you. Drop them at the login screen and go.

---

## 2. Read this aloud to start

> "Thanks for helping. I want to be clear: we're testing the software, not you — if something's
> confusing, that's the software's fault, and it's exactly what we need to find. Please think out
> loud the whole time: what you're looking at, what you expect, what you're trying to do. I'll
> mostly stay quiet and I might not answer questions — that's on purpose, so we see what the screen
> tells you. There are no wrong answers."

**Warm-up (before any clicking):**

1. What's your role, and what do you do day to day?
2. How comfortable are you with apps like this — and what tools do you use for field data now?

### ⚠️ The golden rule

Let them struggle. Stay silent for ~15 seconds before offering anything. If you **do** help,
write down exactly what you said — **a task you had to help with counts as a task the product
failed to explain.**

---

## Coordinator track — 5 tasks

The primary case: the coordinator is the role most likely to need explaining, because they live
in the review flow. Run the tasks in order. Each task's **enumerator variant** is listed under it —
skip those when testing a coordinator.

Use language exactly as written; it deliberately avoids the product's own button names, so you're
testing the design, not their memory.

### Task 0 — First impressions, before touching anything
*Probe: does the entry point convey the model?*

> "Take a look at this screen. Before you click anything — what do you think this platform is for,
> and where do you think the data inside it comes from?"

- **Looks right if…** they mention field data / monitoring, and sense the data arrives from
  elsewhere (phones / ODK / the field) rather than being typed here.
- **Watch for:** "I have no idea." Assuming they enter data *in* this app. Whether they read the
  login line at all.
- **Enumerator variant:** same question, their words — what is this, and what's your job in it?

### Task 1 — Find the work that needs you
*Probe: wayfinding to the daily job.*

> "You've just logged in. A colleague messaged: 'Some new data came in from the field and needs
> checking.' Show me how you'd find it."

- **Looks right if…** they reach the review queue (or a project's incoming submissions) without prompting.
- **Watch for:** hunting through the sidebar; confusing "Review", "Submissions", "Monitor"; landing
  somewhere and not knowing if they're in the right place.
- **Enumerator variant:** "Find out what you've been asked to collect — and whether any of it is
  urgent." (Watch: do they spot overdue / due-soon?)

### Task 2 — Where does this data come from?
*Probe: the critical mental-model check.*

> "Looking at these submissions — where was this data actually entered, and if a new plot needed
> recording today, where would that happen?"

- **Looks right if…** they understand collection happens in **ODK Collect in the field**, and this
  app receives it — not that they'd add records here.
- **Watch for:** looking for an "Add submission" button here. This is the single most important
  thing the product must convey unaided — note their exact words.
- **Enumerator variant:** "Where would you actually fill in a form to collect data?" (Right answer:
  ODK Collect, not this app.)

### Task 3 — Move one submission toward "approved"
*Probe: the core job + the two-gate model.*

> "Pick one of these submissions and do whatever you think is needed to move it toward becoming
> final, approved data. Talk me through what you're deciding."

- **Looks right if…** they open it, judge it, and endorse (Gate 1) — and grasp that it isn't final
  yet; someone else validates next.
- **Watch for:** do they understand what "Endorse (Gate 1)" means before clicking? Do they notice
  the next item appears? Do they expect it to be instantly "approved"?
- **Enumerator variant:** "One of your records was flagged with a problem — find it and work out
  what you're supposed to do about it."

### Task 4 — Fix a value that looks wrong
*Probe: editing + raw-vs-authoritative.*

> "Say one number in this submission looks clearly wrong. Correct it — and tell me what you think
> happens to the original value the enumerator entered."

- **Looks right if…** they edit the field, and understand the raw source value is preserved while
  their corrected value becomes authoritative (and syncs back).
- **Watch for:** fear of "breaking" the original; not finding the edit; not noticing the save
  confirmation or the "edited" marker.
- **Enumerator variant:** skip — enumerators correct data in ODK Collect and resubmit. Instead ask:
  "How would you fix a flagged record?" (Right answer: redo it in ODK Collect.)

### Task 5 — Explain it back, and look it up if unsure
*Probe: can they explain the model + find help.*

> "In your own words: what has to happen for a piece of data to become 'approved'? If you're not
> sure, find the answer using the platform — don't ask me."

- **Looks right if…** they describe the two-gate flow (endorse, then a *different* person validates)
  — or find it fast via Help, the review legend, or the tour.
- **Watch for:** whether "Help" / "How Fieldbase works" is discoverable; whether they can articulate
  *why* two people; confusion between endorse and validate.
- **Enumerator variant:** "In your own words, what happens to your data after you submit it in the field?"

---

## 3. Debrief — ask after the tasks

1. What was the most confusing moment, and what did you expect instead?
2. Would you have needed someone to walk you through this before using it for real? What part?
3. What did "endorse" and "validate" mean to you? When did that click — if it did?
4. If you could change one thing to make it easier to pick up, what would it be?
5. On a scale of 1–10, how easy was this to learn on your own? Why that number?

---

## 4. Notetaker's score sheet

Mark each task **Completed** unaided / **Partial** / **Failed** / **Helped** (helped = failed for
this purpose). Capture one verbatim quote per task — quotes persuade far better than scores.

| Task | Outcome | Time | Ease 1–7 | Key quote / where they stuck |
|---|---|---|---|---|
| 0 · First impressions | ☐ done ☐ partial ☐ fail ☐ helped | | | |
| 1 · Find the work | ☐ done ☐ partial ☐ fail ☐ helped | | | |
| 2 · Where data comes from | ☐ done ☐ partial ☐ fail ☐ helped | | | |
| 3 · Move toward approved | ☐ done ☐ partial ☐ fail ☐ helped | | | |
| 4 · Fix a value | ☐ done ☐ partial ☐ fail ☐ helped | | | |
| 5 · Explain it back | ☐ done ☐ partial ☐ fail ☐ helped | | | |

### The headline call

**Could this person operate Fieldbase unaided?** Circle one — this is the number that answers the
whole test:

- **Yes** — built the model alone
- **Mostly** — one nudge needed
- **Partly** — several nudges
- **No** — needed it explained

---

## 5. Reading the results

**Good signal:** Task 2 answered right without help (they know collection is ODK, not here).
Endorse→validate described in their own words by Task 5. Few or no nudges.

**Red flags:** looking for an "add data" button here; expecting one click to approve; can't say why
two people review; you had to explain the model (note the exact sentence — it belongs in the product).

Two participants won't give you statistics — they'll give you the **two or three places every cold
user trips.** Fix those, run two more. That loop beats any amount of internal review.
