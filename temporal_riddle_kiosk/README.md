# Riddle kiosk, Temporal edition

This started as a thought exercise and is now the version actually run on
the night. It is not a different voice pipeline from `../pirate_riddle_kiosk.py`
— the top-level `CLAUDE.md` already explains why a batch/local orchestration
loop was tried and retired (seconds of serial latency per turn), and
ElevenLabs' hosted agent still does all ASR/TTS/voice here, same as the
plain kiosk. What's different is *where the game's state machine lives*:
instead of a Python closure matching guesses in-process, each guess is a
**Temporal Workflow Update** against a workflow running on a local dev
server — which is also what makes "force-quit this one kid's game without
touching anything else" a clean operation (see "Running it" below) rather
than something you'd have to hand-roll.

## Why try this

Three things Temporal gives you for free that the plain-Python version has
to hand-roll or simply doesn't have:

- **Each guess is a small, independently durable step.** A Workflow Update
  is recorded in the workflow's history the moment it's accepted — if the
  worker process dies mid-game, the next worker to pick it up resumes with
  every guess so far intact. The current kiosk's state lives only in a
  Python variable in a process that Ctrl-C kills outright.
- **The 5-guess cap is real, enforced state — not turn-counting.** The
  original prompt tracks "turn 2, turn 3, ... turn 6" and trusts the LLM to
  count correctly and to only call `check_guess` on actual guesses. Here,
  `submit_guess`'s **Update validator** flatly rejects a 6th guess; the cap
  can't be talked around by chatter that doesn't look like a guess.
- **Live visibility into a running game.** `temporal workflow show
  --workflow-id riddle-game-...` or the local Web UI
  (http://localhost:8233) lets you watch a kid's game — riddle, guesses,
  outcome — from a different terminal while it's in progress. The plain
  kiosk only has whatever you can read off stdout.

## Trade-offs vs. the plain kiosk

- It adds two more long-running local processes (`temporal server
  start-dev`, `worker.py`) that have to be up before the first trick-or-treater
  rings the bell, and that need their own "is this still alive" monitoring
  on the night of. Running everything on one laptop (server, worker, and the
  kiosk client all local) keeps that monitoring to "are these two terminals
  still there."
- It does **not** reduce ASR/TTS latency — that was never the bottleneck
  here; the hosted agent already handles it well. Everything Temporal buys
  here is durability and observability of the *guess-checking* logic, plus
  an operational win that matters for running this live: a clean,
  immediate way to kill one kid's game without touching the other
  processes (see "Running it" below).
- It adds a real wrinkle: ElevenLabs' `Conversation` runs its own event loop
  and calls `check_guess` synchronously from its own thread, so
  `kiosk_client.py` has to bridge into a separate asyncio loop for every
  Temporal call (`TemporalBridge` in `kiosk_client.py`). That's inherent
  complexity the plain kiosk doesn't have, because its guess-checking is
  just a local function call.

## Architecture

```
kiosk_client.py                  worker.py
  |  start_workflow                 |  polls task queue
  |  query(get_riddle)   ------>  RiddleGameWorkflow
  |  (builds prompt/ASR               - picks riddle: workflow.random()
  |   override from the riddle)       - submit_guess (Update): match guess,
  |                                     cap at 5, log via record_guess activity
  |  ElevenLabs Conversation          - end_session (Signal): kid walked off
  |    check_guess tool  ------>      - get_riddle / get_state (Query)
  |    execute_update(submit_guess)
  v
Temporal dev server (localhost:7233)
```

- `models.py` — riddle pool + pure, deterministic guess-matching logic.
  Shared by the workflow and the kiosk; no I/O, no randomness. Each
  `RiddleDef` carries a `difficulty` (1 easiest .. 5 hardest); tier 1 is the
  original "Parrot" riddle, tiers 2-5 trade concreteness for pirate lore and
  multi-word answers ("Treasure Chest" → "Jolly Roger" → "Message in a
  Bottle" → "Davy Jones' Locker"). Selection is still a uniform
  `workflow.random().choice()` across all 5 — difficulty is tracked and
  logged but doesn't yet bias which riddle a kid gets.
- `workflows.py` — `RiddleGameWorkflow`: picks the riddle, exposes
  `submit_guess` (Update), `end_session` (Signal), `get_riddle`/`get_state`
  (Queries).
- `activities.py` — `record_guess`: the one real I/O operation (an audit
  log line per guess), kept out of the deterministic workflow on purpose.
- `worker.py` — the Temporal worker process.
- `kiosk_client.py` — the ElevenLabs session driver, Temporal-flavored
  sibling of `../pirate_riddle_kiosk.py`.
- `pirate_riddle_prompt_temporal.txt` — same persona/clue-ladder as
  `../pirate_riddle_prompt.txt`, with one addition: an explicit
  `out_of_guesses` path, since the workflow (not turn-counting) now owns
  the 5-guess limit.

## Running it

Needs the Temporal CLI (`brew install temporal`) and its own venv (kept
separate from the root project's — see this directory's `pyproject.toml`).

```bash
just deps              # uv sync — installs temporalio + elevenlabs here

just server            # terminal 1: temporal server start-dev
just worker            # terminal 2: the worker process
ELEVEN_LABS_API_KEY=... just kiosk   # terminal 3: one kid's session
```

All on one laptop: `temporal server start-dev` and `worker.py` are started
once and left running for the whole night; only `kiosk_client.py` (terminal
3) is restarted per kid. Only run one `kiosk_client.py` at a time — it's
built as "one process = one kid's game," not a server that handles several
kids concurrently.

Mic control (on/off between kids) is left to normal macOS input device
settings — `DefaultAudioInterface` just opens whatever the OS's default
input device is, there's nothing kiosk-specific to toggle.

**Ending a kid's game and resetting for the next one:**
- Normal case (kid finishes, or walks away): Ctrl-C in the kiosk terminal.
  This ends the ElevenLabs session and signals `end_session` to the
  workflow, which finishes it immediately (`outcome="abandoned"` if it
  wasn't already won) instead of idling out the 10-minute timeout.
- Then just rerun `just kiosk` — it starts a brand-new
  `riddle-game-<uuid>` workflow with fresh state, same "one process per
  kid" guarantee as the plain kiosk.
- If the kiosk process itself is wedged and Ctrl-C in its terminal won't
  land, force-terminate the in-progress game from a second terminal:
  ```bash
  just kill
  ```
  (reads the workflow id `kiosk_client.py` wrote to `current_workflow.txt`
  at session start, same uuid it printed to stdout). Then kill/restart the
  stuck kiosk process and rerun `just kiosk`.

Watch a game live while it's running:

```bash
temporal workflow show --workflow-id riddle-game-<uuid-from-kiosk-output>
# or open http://localhost:8233
```

Every accepted guess also appends a line to `guess_log.jsonl` in this
directory (written by the `record_guess` activity).
