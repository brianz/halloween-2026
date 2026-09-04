# Haunted Pirates — Captain Barnaby Bones

Voice password game for a Halloween trick-or-treat kiosk. A kid talks to
"Captain Barnaby Bones," a ghost pirate; after 5 turns he reveals a
password the kid brings to a treasure chest for candy.

## Architecture (the point of this project — keep it this way)

- **ElevenLabs does ASR + TTS only** (Speech Engine). No LLM on their side.
- **A Temporal workflow owns ALL conversation state**: which password, turn
  count, done-flag, conversation history, optional child name. Runs on a
  local Temporal dev server so the night is not dependent on home internet.
- **The LLM call is a Temporal Activity, never workflow code.** Workflow
  code must stay deterministic (no network, no wall-clock, no stdlib
  `random` — use `workflow.random()`).
- The workflow decides WHAT may be said each turn (structured "clue
  budget": `vague_riddle` → `sea_theme` → `first_letter` → `word_count` →
  `reveal`). The Activity only wordsmiths that budget into one line.
- The child's utterance is also checked each turn (`_guess_correct`,
  whole-word match) against the password. A correct guess short-circuits
  straight to a `correct_guess` reveal — the game doesn't force the
  remaining clue turns just because the budget isn't exhausted yet.
- The conversation opens with `greet()` (a separate update from
  `submit_utterance`), a dynamically generated line that asks the child's
  name. It isn't part of the clue-turn budget — the child's reply to it is
  captured as their name (`_extract_name`, best-effort heuristic) and
  becomes clue turn 1, not a wasted extra turn.
- **Never trust LLM output**: after the Activity returns, the workflow
  leak-checks the line (`_password_leaked` in `temporal_workflows.py`:
  case-insensitive substring, reversed, spelled-out letter-by-letter). On
  leak, timeout (4s `schedule_to_close_timeout`), exception, or empty
  output, it falls back to the static `CLUE_TEMPLATES`. This is a live
  outdoor kiosk with a line of kids — it must never hang or go silent.
- Password is picked with `workflow.random().choice()` exactly once per
  run (see `_ensure_password`), so crash-replay re-derives the same
  password. Don't move this out of the workflow.
- Persona/style rules live in `pirate_activities.py:SYSTEM_PROMPT`. Do not
  re-add game-flow rules there (turn limits, reveal timing) — the LLM
  doesn't make those decisions.

## Files

| File | Role |
| --- | --- |
| `temporal_workflows.py` | `PirateConversation` workflow — state, clue budgets, leak check, fallback |
| `pirate_activities.py` | `generate_pirate_line` Activity + `ClueRequest` + clue-level instructions + system prompt |
| `llm_providers.py` | Provider interface; Bedrock Converse (boto3) impl. ElevenLabs has no standalone text API — checked 2026-09-03 |
| `temporal_worker.py` | Worker process (workflow + activity host) |
| `brain_server_sketch.py` | Bridge sketch: ElevenLabs callbacks → Temporal client; `_smoke_test()` at bottom |
| `voice_console.py` | Localhost browser voice-test console: mic WAV → Scribe ASR → workflow → TTS (custom voice); FastAPI, key stays server-side |
| `pirate-agent.py` | Legacy hosted-ElevenLabs-agent version; kept for reference only |
| `test_pirate_workflow.py` | Workflow tests via Temporal time-skipping test env, mocked activities |

## Environment variables

| Variable | Default | Needed for |
| --- | --- | --- |
| `PIRATE_AWS_PROFILE` | *(boto3 default chain — see note)* | Real Bedrock calls (worker + smoke test). On this machine the default profile has no credentials; use `brianz-admin` |
| `PIRATE_LLM_PROVIDER` | `bedrock` | Provider selection (only `bedrock` exists) |
| `PIRATE_BEDROCK_MODEL_ID` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Model override. Must be an inference-profile ID (`us.`-prefixed), not a raw foundation-model ID |
| `PIRATE_BEDROCK_REGION` | `us-west-2` | Region override |
| `PIRATE_VOICE_ID` | `TG2O4Qh067u8gMkJrjhR` (Barnaby custom voice) | Voice-test console TTS voice |
| `PIRATE_TTS_MODEL` | `eleven_flash_v2_5` | Voice-test console TTS model (low latency) |
| `PIRATE_ASR_MODEL` | `scribe_v1` | Voice-test console ASR model |
| `ELEVEN_LABS_API_KEY` | — | ElevenLabs ASR/TTS side (not needed for the Temporal/Bedrock smoke test) |
| `ELEVEN_LABS_AGENT_KEY_ID` | — | Legacy `pirate-agent.py` only |

Unit tests (`pytest`) mock the Activity and need **no AWS credentials**.

## Commands

A `justfile` wraps everything (requires `just`, `brew install just`):

```bash
just deps       # uv sync — install Python deps into .venv from pyproject.toml
just test       # unit tests (no AWS needed)
just smoke      # text-only end-to-end vs real Bedrock (no ElevenLabs)
just dev        # temporal dev server + worker + voice console, one command
just stop       # kill everything `just dev` started
just temporal   # just the dev server      (localhost:7233, UI at :8233)
just worker     # just the worker          (real Bedrock, brianz-admin profile)
just console    # just the voice console   (http://127.0.0.1:8123)
```

Raw equivalents:

```bash
# deps (project venv at .venv, from pyproject.toml + uv.lock)
uv sync

# unit tests (no AWS needed)
.venv/bin/python -m pytest test_pirate_workflow.py

# end-to-end (3 terminals):
temporal server start-dev                              # localhost:7233, UI at :8233
PIRATE_AWS_PROFILE=brianz-admin .venv/bin/python temporal_worker.py
PIRATE_AWS_PROFILE=brianz-admin .venv/bin/python brain_server_sketch.py

# voice turn-testing with real mic + custom-voice TTS (browser):
.venv/bin/python -m uvicorn voice_console:app --host 127.0.0.1 --port 8123
# then open http://127.0.0.1:8123 — needs ELEVEN_LABS_API_KEY in the env.
# Port 8000 is taken on this machine by an unrelated project; use 8123.
```

## Gotchas learned the hard way

- An update can be processed before `run()`'s first line — hence
  `_ensure_password()` is called from every entry point (`run`, `greet`,
  `submit_utterance`). It must assign to `self._password` itself, not just
  return the value — callers besides `run()` discard the return value and
  rely on the side effect.
- Claude on Bedrock rejects `temperature` and `topP` together.
- Signals are not ordered relative to updates; poll the `status` query if
  you need `set_child_name` to land before the next turn.
- Signal name for tests: mock activities must be registered under the
  name `generate_pirate_line` via `activity.defn(name=...)`.
