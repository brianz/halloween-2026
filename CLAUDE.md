# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Haunted Pirates — Captain Barnaby Bones

Voice password/riddle game for a Halloween trick-or-treat kiosk. A kid talks to
"Captain Barnaby Bones," a ghost pirate; after a few turns he reveals a
password (or the kid solves a riddle) that's brought to a treasure chest for
candy. The repo also has two unrelated ESP32 hardware props (lit treasure
chests) and a Temporal-based thought exercise — see "Other subprojects" below.

## Architecture (the point of this project — keep it this way)

- **The ElevenLabs hosted Conversational AI agent does ASR + TTS + voice**
  (`eleven_v3_conversational`, custom voice `TG2O4Qh067u8gMkJrjhR`, LLM
  `claude-haiku-4-5`). It runs in the ElevenLabs cloud — realtime streaming,
  interruption handling, good latency. We do NOT run local ASR/TTS loops.
  (Earlier iterations did: ElevenLabs Speech-Engine sketch, then a Scribe
  batch ASR + Bedrock + batch TTS localhost console. Both were retired —
  the batch pipeline had ~seconds of serial round-trip latency per turn,
  and the hosted agent with programmatic control does everything better.)
- **One process per kid = fresh state by construction.** `pirate_kiosk.py`
  picks the password with plain `random.choice` locally, then starts one
  Conversation. No session-memory problem, no state cleanup, no Temporal.
- **The kiosk owns the game logic, the LLM only wordsmiths:**
  - The full system prompt lives in `pirate_prompt.txt` (version-controlled,
    not buried in the ElevenLabs console) and is injected per session via
    the **system-prompt override**; the password goes in as a **dynamic
    variable** (`{{password}}`), turn counting uses the platform's
    `{{system__agent_turns}}`.
  - The **`check_guess` client tool** is registered in `pirate_kiosk.py`
    and called by the agent every turn; the deterministic whole-word
    match (`_guess_correct`) runs locally, and a correct guess
    short-circuits straight to the reveal.
  - **ASR keywords override** passes the whole password pool per session
    so mumbled guesses transcribe reliably.
- **Audio tags** (`[laughs]`, `[triumphantly]`, …) are interpreted by
  ElevenLabs TTS itself — the prompt whitelists the exact tags and forbids
  any other bracketed text (anything else would be read aloud as words).
- The agent id is the default in `pirate_kiosk.py` ("Ghost Pirate Captain",
  `agent_5401m084pnhxf0z8bdyzj8depdes`; `PIRATE_AGENT_ID` overrides). The
  direnv var `ELEVEN_LABS_AGENT_KEY_ID` misleadingly holds an API *key* id —
  it is unused by the kiosk.

### Riddle mode variant

`pirate_riddle_kiosk.py` + `pirate_riddle_prompt.txt` are the same
architecture as above, but the kid solves a riddle instead of guessing a
bare password: `RIDDLE_POOL` holds `{riddle, answer}` pairs, `check_guess`
word-matches against the chosen riddle's `answer`, and the ASR override
boosts every riddle's answer words. Shares the same ElevenLabs agent and
`check_guess` client tool as the password game — only the kiosk script and
prompt file differ.

`pirate_riddle_kiosk.py` and `temporal_riddle_kiosk/kiosk_client.py` are
meant to operate identically from the operator's side — same controls, same
recordings — the Temporal version only changes *where guess-checking state
lives*, not how you run or control a session:
- **Recording:** off by default; pass `--record` to either script (e.g.
  `just riddle-kiosk --record`, `just kiosk --record` from
  `temporal_riddle_kiosk/`) to turn it on for that one session. When on,
  both run a `RecordingAudioInterface` (subclass of the SDK's
  `DefaultAudioInterface`) that tees every raw PCM chunk to two local WAV
  files per session — `recordings/<session-id>_mic.wav` (the kid) and
  `..._agent.wav` (the Captain) — written as soon as `end_session()`
  returns, no dependency on ElevenLabs' own call-recording/retention
  settings. `<session-id>` is a `riddle-session-<uuid>` for the plain
  kiosk, `riddle-game-<uuid>` (the Temporal workflow id) for the Temporal
  one.
- **Force-quitting a wedged session:** Ctrl-C is the normal path for both.
  If the kiosk process itself won't respond to Ctrl-C in its own terminal,
  the plain kiosk drops its pid in `current_riddle_kiosk.pid` so
  `just kill-riddle-kiosk` can send it the same SIGINT from a second
  terminal; the Temporal kiosk drops its workflow id in
  `temporal_riddle_kiosk/current_workflow.txt` so `just kill` (run from
  that directory) can terminate the workflow directly.
- **Known divergence:** `temporal_riddle_kiosk/kiosk_client.py` exits on
  its own once the workflow ends, for any reason — a background watcher
  (`watch_for_workflow_end`) waits on `handle.result()` and ends the
  ElevenLabs session when it resolves: immediately on an abnormal end
  (`just kill`), after a short grace period (`WORKFLOW_END_GRACE_SECONDS`)
  on a clean finish (correct guess, out_of_guesses, timed_out) so the agent
  gets to actually say the reveal line — workflow completion lands in the
  same instant as the deciding guess, before the agent has said anything
  about it. `pirate_riddle_kiosk.py` has no separate orchestration layer to
  watch this way, so it still always needs an explicit Ctrl-C per session.

## Files

| File | Role |
| --- | --- |
| `pirate_kiosk.py` | One kid's session (password mode): pick password, start Conversation with overrides + ASR keywords, register `check_guess`, print transcript to stdout |
| `pirate_prompt.txt` | System prompt for password mode (persona, clue ladder, reveal rules, audio-tag whitelist) |
| `pirate_riddle_kiosk.py` | One kid's session (riddle mode): same flow as `pirate_kiosk.py`, but picks a riddle and matches on its answer |
| `pirate_riddle_prompt.txt` | System prompt for riddle mode |
| `barnaby_tts.py` | One-off script to render arbitrary text to an mp3 via ElevenLabs' plain TTS API (not the hosted agent) — ad-hoc voice testing, not used by either kiosk |

## Environment variables

| Variable | Needed for |
| --- | --- |
| `ELEVEN_LABS_API_KEY` | Key with **ElevenAgents: Read + Write** permission |
| `PIRATE_AGENT_ID` | Optional agent-id override (default: the Ghost Pirate Captain id baked into `pirate_kiosk.py`) |

## Commands

```bash
just deps                   # uv sync — install elevenlabs[pyaudio] into .venv
just kiosk                  # one kid's session, password mode (mic + speakers); Ctrl-C to end, rerun for next kid
just riddle-kiosk           # one kid's session, riddle mode
just riddle-kiosk --record  # same, but also save mic + agent audio to recordings/ (off by default)
just kill-riddle-kiosk      # force-quit a wedged riddle-kiosk session from a second terminal (same SIGINT as Ctrl-C)
```

Raw: `.venv/bin/python pirate_kiosk.py` / `.venv/bin/python pirate_riddle_kiosk.py`

## One-time agent setup (already done, via API — don't redo)

- Platform settings → overrides enabled: system prompt, first message,
  ASR keywords.
- Client tool `check_guess` (string param `guess`) added to the agent.
- `pyaudio` needs portaudio: `brew install portaudio`.

## Gotchas learned the hard way

- The agent-scoped API key can't read/write agents unless **ElevenAgents
  Read/Write** is enabled on it (the console's no-code view hid all of:
  dynamic variables, overrides, client tools — that's why the hosted agent
  "felt simplistic" before; it isn't).
- Overrides are off by default for security; enabling them is a one-time
  platform-settings update (the SDK models make you pass
  `"prompt": {"prompt": True}`, not just `True`).
- The SDK's `Conversation` manages its own event loop — don't wrap its
  lifecycle in `asyncio.run`; use `start_session()` / `wait_for_session_end()`
  / `signal` handling like `pirate_kiosk.py` does.
- Each audio tag colors only ~4-5 words of speech; cap them at 1-2 per line.
- Port 8000 on this machine is taken by an unrelated project (picklecraft).

## Other subprojects

- **`gold-chest-lights/`** and **`gold-chest-lights-rgb/`** — two unrelated
  ESP32 + MicroPython props, each a slow amber "breathing" pulse for a
  treasure chest (WS2812B strip and a DotStar/APA102 strip respectively, on
  separate boards). No ASR/TTS, no ElevenLabs — they share this repo's root
  `.venv` only for the `esptool`/`mpremote` flashing CLIs. Each has its own
  `CLAUDE.md` and `README.md` with wiring and upload steps; read those
  before touching either directory.
- **`temporal_riddle_kiosk/`** — started as a thought exercise, now the
  version actually run on the night. Same riddle game and hosted ElevenLabs
  agent as `pirate_riddle_kiosk.py`, but guess-checking lives in a Temporal
  Workflow (via Workflow Updates) instead of a local Python closure. Run
  entirely on one laptop: `temporal server start-dev`, `worker.py`, and
  `kiosk_client.py` are three local terminals (server + worker left running
  all night, kiosk restarted per kid). Has its own
  `pyproject.toml`/`.venv`/`justfile`, independent of the root project. See
  its `README.md` for the full runbook, including `just kill` to
  force-terminate a stuck kid's game from a second terminal.
</content>
