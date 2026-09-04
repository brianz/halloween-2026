# Haunted Pirates — Captain Barnaby Bones

Voice password game for a Halloween trick-or-treat kiosk. A kid talks to
"Captain Barnaby Bones," a ghost pirate; after a few turns he reveals a
password the kid brings to a treasure chest for candy.

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

## Files

| File | Role |
| --- | --- |
| `pirate_kiosk.py` | One kid's session: pick password, start Conversation with overrides + ASR keywords, register `check_guess`, print transcript to stdout |
| `pirate_prompt.txt` | The full system prompt (persona, clue ladder, reveal rules, audio-tag whitelist). The single source of truth for agent behavior |

## Environment variables

| Variable | Needed for |
| --- | --- |
| `ELEVEN_LABS_API_KEY` | Key with **ElevenAgents: Read + Write** permission |
| `PIRATE_AGENT_ID` | Optional agent-id override (default: the Ghost Pirate Captain id baked into `pirate_kiosk.py`) |

## Commands

```bash
just deps     # uv sync — install elevenlabs[pyaudio] into .venv
just kiosk    # one kid's session (mic + speakers); Ctrl-C to end, rerun for next kid
```

Raw: `.venv/bin/python pirate_kiosk.py`

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
