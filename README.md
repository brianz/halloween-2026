# Haunted Pirates — Captain Barnaby Bones

A Halloween kiosk game. Kids walk up and talk to **Captain Barnaby
Bones**, a friendly skeleton pirate. He plays a password guessing game
with them — one clue per turn for up to 5 turns — then reveals a secret
password. The kid brings the password to a nearby treasure chest to
claim candy.

Why it's built this way: an earlier version used a hosted LLM voice
agent and kept losing track of state mid-conversation. Now **ElevenLabs
does audio only (ASR + TTS via their Speech Engine)**, and a **Temporal
workflow owns every piece of game state** — which password, which turn,
whether we're done — so it's deterministic, crash-resumable, and
debuggable in a live UI. The LLM is only ever a *wordsmith*: the workflow
hands it a structured "clue budget" ("you may hint at the first letter",
"reveal now") and it turns that into one funny pirate line.

## How it works

```
kid speaks ──▶ ElevenLabs ASR ──▶ brain server ──▶ Temporal update
                                                     (submit_utterance)
                                                          │
              workflow decides clue budget (deterministic)
                                                          │
                                              Activity: LLM call
                                            (Bedrock, 4s timeout)
                                                          │
                    leak-check the output ◀───────────────┘
                    (password substring / reversed / spelled-out?)
                          │                          │
                       clean: speak it          leak/timeout/error:
                                                 static template instead
                                                          │
kid hears ◀── ElevenLabs TTS ◀── brain server ◀───────────┘
```

**Guarantees:**

- The password is chosen once per conversation with `workflow.random()`
  — replay-safe, so a crashed worker picks the *same* password on resume.
- The LLM can only say what the clue budget allows. Its output is checked
  (case-insensitive substring, reversed, spelled-out letter-by-letter)
  before anyone hears it; any leak, timeout, or error falls back to a
  canned template. The kiosk never hangs or goes silent.
- Conversation history and an optional kid's name live in workflow state
  and are passed to each LLM call for continuity and personalization.

## Running locally

### 1. Dependencies

Requires Python 3.12+ (venv is at `.venv`) and `uv`:

```bash
uv pip install --python .venv/bin/python temporalio boto3 pytest pytest-asyncio
```

Temporal itself (install once): `brew install temporal`
(or see https://temporal.io/setup/install-temporal-cli)

### 2. Temporal server (terminal 1)

```bash
temporal server start-dev
```

Gives you `localhost:7233` (API) and a live workflow UI at
http://localhost:8233 — great for watching clue progression in real time.

### 3. Worker (terminal 2)

```bash
PIRATE_AWS_PROFILE=brianz-admin .venv/bin/python temporal_worker.py
```

The worker hosts both the workflow and the LLM Activity.

### 4. Smoke test (terminal 3) — no ElevenLabs needed

```bash
PIRATE_AWS_PROFILE=brianz-admin .venv/bin/python brain_server_sketch.py
```

Simulates a full 5-turn conversation through the real stack (Temporal +
Bedrock) and prints each pirate line. Example output:

```
Well, well. Another landlubber washes up on my shore.
turn 1: [Chuckles] Ah, ye be startin' fresh, eh? …
turn 2: [Enthusiastically] Arrr, good guessin'! Here be yer sea clue …
turn 3: [Chuckles] Here's yer hint, matey—the answer starts with the letter 'S' …
turn 4: [Enthusiastically] …the answer be THREE words long, savvy?
turn 5: [Enthusiastically] Blimey, ye've done it! The password be Skull and Bones!
```

Every turn should be freshly worded (LLM), escalate in specificity, and
never contain the password before turn 5. If Bedrock is slow or down
you'll see the static templates instead — the game still completes.

### 5. Unit tests — no AWS credentials needed

```bash
.venv/bin/python -m pytest test_pirate_workflow.py
```

The Activity is mocked, so tests cover the safety logic offline:
password-leak fallback, timeout fallback (with wall-clock bounds),
exception fallback, happy-path passthrough, history/name propagation,
and the leak checker's detection variants.

### Wiring up the real kiosk

`brain_server_sketch.py` shows the two callbacks to slot into ElevenLabs
Speech Engine's `on_transcript` hook (see their Speech Engine cookbook
for the transport-specific wiring): start one workflow per session
(`on_session_start`), then one `submit_utterance` update per finished
transcript and TTS the returned `line` verbatim.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `PIRATE_AWS_PROFILE` | boto3 default chain | AWS **profile name** for Bedrock. **Required on machines where the default profile has no credentials** (e.g. this one — use `brianz-admin`). Alternative: export `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_SESSION_TOKEN` or any boto3-supported credential source |
| `PIRATE_LLM_PROVIDER` | `bedrock` | LLM provider (`bedrock` is currently the only implementation) |
| `PIRATE_BEDROCK_MODEL_ID` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Bedrock model. Must be an inference-profile ID (`us.`-prefixed) — raw foundation-model IDs don't support on-demand invocation anymore |
| `PIRATE_BEDROCK_REGION` | `us-west-2` | Bedrock region |
| `ELEVEN_LABS_API_KEY` | — | ElevenLabs ASR/TTS (only for the live kiosk, not the smoke test) |

The AWS account needs Claude model access enabled in Bedrock
(us-west-2 has `us.anthropic.claude-haiku-4-5-20251001-v1:0` enabled).
No LLM-related env vars are needed for `pytest`.

## Project layout

| File | Role |
| --- | --- |
| `temporal_workflows.py` | The `PirateConversation` workflow — state, clue budgets, leak check, static fallbacks |
| `pirate_activities.py` | The `generate_pirate_line` Activity, `ClueRequest`, clue-level instructions, and the Captain's persona prompt |
| `llm_providers.py` | LLM provider interface + Bedrock Converse implementation |
| `temporal_worker.py` | Worker process hosting the workflow + activity |
| `brain_server_sketch.py` | ElevenLabs ↔ Temporal bridge sketch, plus the manual smoke test |
| `test_pirate_workflow.py` | Workflow tests (Temporal time-skipping test environment, mocked Activity) |
| `pirate-agent.py` | Legacy hosted-ElevenLabs-agent version, kept for reference |

Password pool and clue templates live at the top of
`temporal_workflows.py`; tune the Captain's personality in
`pirate_activities.py` (`SYSTEM_PROMPT` and `CLUE_LEVEL_INSTRUCTIONS`).
