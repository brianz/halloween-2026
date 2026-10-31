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
  (`eleven_v4_turbo`, custom voice `TG2O4Qh067u8gMkJrjhR`, LLM
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
  `temporal_riddle_kiosk/`) to turn it on for that one session. Both run a
  `RecordingAudioInterface` (subclass of the SDK's `DefaultAudioInterface`)
  that tees every raw PCM chunk to `recordings/<session-id>.wav`-ish paths,
  written as soon as `end_session()` returns, no dependency on ElevenLabs'
  own call-recording/retention settings. `<session-id>` is a
  `riddle-session-<uuid>` for the plain kiosk, `riddle-game-<uuid>` (the
  Temporal workflow id) for the Temporal one. **Diverges since 2026-10-30:**
  `pirate_riddle_kiosk.py` writes ONE stereo file,
  `recordings/<session-id>.wav` — left channel the kid's mic, right
  channel the Captain — with each chunk timestamped against session start
  and silence-padded into position before merging (mic input is
  continuous; agent TTS output only arrives in bursts while it's actually
  talking, so the two have no shared clock to interleave against safely).
  `temporal_riddle_kiosk/kiosk_client.py` still writes two separate mono
  files (`..._mic.wav` / `..._agent.wav`) — not yet ported.
- **Force-quitting a wedged session:** Ctrl-C is the normal path for both.
  If the kiosk process itself won't respond to Ctrl-C in its own terminal,
  the plain kiosk drops its pid in `current_riddle_kiosk.pid` so
  `just kill-riddle-kiosk` can send it the same SIGINT from a second
  terminal; the Temporal kiosk drops its workflow id in
  `temporal_riddle_kiosk/current_workflow.txt` so `just kill` (run from
  that directory) can terminate the workflow directly.
- **Both riddle scripts now exit on their own once the game ends** (correct
  guess or out_of_guesses) — the agent hangs up *itself* via the ElevenLabs
  built-in `end_call` tool, called right after the reveal/send-off line
  (`pirate_riddle_prompt_temporal.txt` and, since 2026-10-30,
  `pirate_riddle_prompt.txt` too). The orchestrator closes the websocket,
  the SDK already treats that as a normal `end_session()` — no guessing
  about TTS timing — and `wait_for_session_end()` returns on its own.
  Both scripts also have a background fallback watcher in case the agent
  ever doesn't call `end_call`: `temporal_riddle_kiosk/kiosk_client.py`'s
  `watch_for_workflow_end` waits on `handle.result()` and ends the session,
  immediately on an abnormal end (`just kill`), after a short grace period
  (`WORKFLOW_END_GRACE_SECONDS`) on a clean finish — it also covers paths
  the agent has no reason to call `end_call` for at all ("timed_out"/kid
  walked away, "abandoned"/operator's Ctrl-C). `pirate_riddle_kiosk.py`'s
  `watch_for_game_end` is the same idea without Temporal: a daemon thread
  polling local `state`, force-ending the session `END_CALL_GRACE_SECONDS`
  after the outcome is decided if nothing else has by then (added
  2026-10-30 after a real test hit exactly this gap — see gotchas).
  `pirate_prompt.txt` (password mode) still explicitly tells the agent
  never to call `end_call` — enabling the tool is agent-wide (see gotcha
  below), not per-script, and that script wasn't part of this change.
- **The 3-guess cap, "ask the child's name once" rule, and 5-greeting
  `FIRST_MESSAGES` are ported to both riddle kiosks, not just Temporal.**
  `pirate_riddle_kiosk.py` mirrors `temporal_riddle_kiosk/kiosk_client.py`'s
  `MAX_GUESSES`/`FIRST_MESSAGES` and `pirate_riddle_prompt.txt` mirrors
  `pirate_riddle_prompt_temporal.txt`'s rules (name-once, turn-2-doesn't-
  call-check_guess, guess-cap-overrides-the-clue-ladder) — same known
  minor lag on the exact turn the cap is hit (see gotcha above), same
  fix, same self-correction via check_guess's rejection message. The
  difference is purely *where the cap's state lives*: a local Python
  closure (`state` dict in `make_client_tools`) instead of Temporal
  workflow fields — non-durable, but that was already true of everything
  else in the plain kiosk. `pirate_kiosk.py` (password mode, a different
  game) is untouched — it still ends on turn count alone with a single
  hardcoded `FIRST_MESSAGE`.

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

- **2026-10-30: `pirate_riddle_kiosk.py` had the same "session never ends"
  bug the Temporal kiosk had before its `end_call` fix** — a correct guess
  didn't end anything; the agent just kept re-prompting the child in the
  same still-open conversation. Fixed the same way, not with a new
  mechanism: flipped `pirate_riddle_prompt.txt` from "never call end_call"
  to "call it right after the reveal" (the tool was already enabled
  agent-wide from the Temporal fix). `run_kid_session()` needed no new
  exit logic — `conversation.wait_for_session_end()` already returns on
  its own once the websocket closes, so the script just naturally reaches
  the end of `__main__` and exits, no explicit `sys.exit()` needed.
  Confirmed by calling `run_kid_session()` directly in a scripted
  text-only session and timing how long it took to return with no Ctrl-C
  sent. **Update:** the "no fallback if the agent skips `end_call`" gap
  noted here was real, not theoretical — a second real test hit it (the
  agent revealed and said its send-off line, but never called `end_call`,
  and nothing nudges it afterward since the kid has no reason to guess
  again). Fixed by porting the Temporal kiosk's watcher pattern:
  `watch_for_game_end` polls local `state` in a daemon thread and
  force-ends the session if it's still open `END_CALL_GRACE_SECONDS`
  (8s) after the outcome is decided. This also meant `end_call`, the
  watcher, and Ctrl-C could now all reach `end_session()` on the same
  session — guarded `run_kid_session`'s own call with
  `if not session_ended.is_set()` so a second real call never hits an
  already-closed pyaudio stream.
- **2026-10-30: `worker.py` doesn't hot-reload** — it imports `models.py`/
  `workflows.py`/`activities.py` once at startup, so an edit to any of them
  (e.g. changing `MAX_GUESSES`) has no effect on games started against an
  already-running worker. Caught this mid-testing: lowered `MAX_GUESSES`
  from 5 to 3, reran a scripted session against a worker that had been up
  since before the edit, and the cap was silently still 5. Kill and
  restart `worker.py` after any change to those files before testing or
  running the kiosk for real.
- **2026-10-30: lowering `MAX_GUESSES` surfaced two latent prompt bugs in
  `pirate_riddle_prompt_temporal.txt`** that a cap of 5 had been masking:
  (1) the prompt's old "every turn from turn 2 onward, call check_guess"
  rule meant turn 2 — posing the riddle for the first time, before the
  child has said anything to guess — burned a guess slot on a non-guess;
  with a 3-guess cap that left only 2 real attempts. Fixed by moving the
  mandate to "turn 3 onward" and telling turn 2 explicitly not to call
  check_guess. (2) The turn-based clue ladder's "turn 5+: keep nudging for
  another guess" instruction can fire on the exact same turn check_guess
  returns `out_of_guesses` (3 guesses now lands around turn 5) — the LLM
  sometimes gives one more hint instead of revealing immediately on that
  turn, since it sometimes composes its reply before fully deferring to
  the tool result — confirmed with a scripted text-only session rather
  than assumed. The workflow itself is unaffected (it transitions to
  `out_of_guesses` correctly the instant the 3rd guess lands, regardless
  of what the agent says), and the existing rejection path in
  `check_guess` ("the game's already over — reveal the answer and move
  on", returned whenever a guess is submitted against a workflow that's
  no longer `playing`) means the agent gets told the truth on its very
  next tool call — so the game still always ends correctly on the backend
  and the agent still always reveals and calls `end_call` eventually, just
  sometimes a turn or two later than the ideal. Tried fixing the lag
  itself by telling the agent to "call check_guess before deciding what
  to say" — that made things worse (it started skipping check_guess
  entirely for several turns) and was reverted. Left as a known minor
  imperfection rather than risk another regression.
- **2026-10-30: enabled the agent's built-in `end_call` system tool** to
  fix the Temporal kiosk never hanging up after a correct guess. The SDK's
  `Conversation` has no "agent finished speaking" callback — only text
  events (`agent_response`) and raw audio chunks — so there was no clean
  signal for when it was safe to hang up after the reveal; the old fix was
  a flat `WORKFLOW_END_GRACE_SECONDS` sleep guessing how long the line
  would take to play. `end_call` is a real ElevenLabs system tool
  (`BuiltInToolsInput.end_call` / `EndCallToolConfig` in the SDK types)
  that lets the agent close the call itself once the LLM decides to invoke
  it; ElevenLabs' orchestrator then closes the websocket, and the SDK's
  `_run()` loop already treats `ConnectionClosedOK` as a normal
  `end_session()` — so `wait_for_session_end()` returns the instant the
  agent is actually done talking. Enabled via the same one-off `PATCH
  /v1/convai/agents/{agent_id}` pattern as the TTS model switch below,
  setting `conversation_config.agent.prompt.built_in_tools.end_call` with
  `pre_tool_speech: "force"` (so it always speaks its line before hanging
  up, never hangs up silently) — confirmed via GET afterward that
  `check_guess` and the TTS config were untouched. **This is agent-level,
  not per-session** — the password and plain riddle kiosks share this same
  agent and would otherwise gain the ability to self-hang-up with no
  prompt awareness of it, so `pirate_prompt.txt` and
  `pirate_riddle_prompt.txt` both got an explicit "never call end_call"
  line to keep them Ctrl-C-only, matching their existing design. Only
  `pirate_riddle_prompt_temporal.txt` instructs the agent to call it (right
  after the reveal line, correct or out_of_guesses).
- **2026-10-30: switched the agent's TTS model from `eleven_v3_conversational`
  to `eleven_v4_turbo`** (ElevenLabs' v3 → v4 upgrade; v4 Turbo is the variant
  tuned for agents/real-time, ~100ms median inference latency, more reliable
  audio-tag following). Done via a one-off `PATCH
  /v1/convai/agents/{agent_id}` with `conversation_config.tts.model_id`
  (same "already done, via API" category as the rest of "One-time agent
  setup" below — not something `pirate_kiosk.py` sets in code, since the
  kiosk's `conversation_config_override` only ever touches prompt/first
  message/ASR keywords). Verified with a scripted text-only session
  (`send_user_message` + `audio_interface=None`, two wrong guesses then a
  correct one) and a second run swapping in a file-writing `AudioInterface`
  to capture the real `eleven_v4_turbo` audio — both came back indistinguishable
  from v3 in game logic (clue ladder, `check_guess` short-circuit, audio-tag
  whitelist all intact). Left `expressive_mode: true` and
  `enable_phoneme_tags: true` as-is on the agent even though both were
  v3-specific settings per ElevenLabs' docs (expressive mode defaults on for
  v3 Conversational; phoneme tags are documented as only compatible with
  `eleven_flash_v2`, v4 uses slash-wrapped IPA instead) — neither appeared to
  cause problems, but they're the first things to check if audio behaves
  oddly.
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
- `pirate_riddle_prompt_temporal.txt` originally kept the plain kiosk's
  `turn 6 or later: reveal the answer` rule from `pirate_riddle_prompt.txt`
  — which is load-bearing there (no guess cap exists in that version, so
  it's the only thing that ends a losing game) but was a live bug once
  copied into the Temporal version: the agent could reveal the answer and
  hang up purely on turn count, without ever calling `check_guess` with a
  final result, leaving the workflow stuck in `outcome="playing"` forever
  (confirmed against a real workflow: `outcome="abandoned"` with only 4 of
  5 guesses used, and a `WorkflowExecutionSignaled`/Ctrl-C the only thing
  that ever closed it). Fixed by making reveal strictly conditional on
  `check_guess` returning "correct" or "out_of_guesses" — never on turn
  count — in the Temporal prompt only; the plain prompt is unaffected and
  intentionally different.

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
  all night, kiosk restarted per kid). Shares the root project's venv and
  `uv.lock` (one `uv sync` at the repo root installs `temporalio` alongside
  everything else); has its own `justfile` only, with `worker`/`kiosk`
  recipes invoking `../.venv/bin/python`. See its `README.md` for the full
  runbook, including `just kill` to force-terminate a stuck kid's game from
  a second terminal.
</content>
