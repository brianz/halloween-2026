# Haunted Pirates — Captain Barnaby Bones

A Halloween kiosk game. Kids walk up and talk to **Captain Barnaby
Bones**, a friendly skeleton pirate. He greets them, asks their name, and
plays a password guessing game — one progressively-easier clue per turn,
up to 4 clues. If the kid guesses the password at any point, he reveals
it immediately and celebrates; otherwise he reveals it after the 4th
clue. The kid brings the password to a nearby treasure chest to claim
candy.

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
- The child's utterance is checked every turn for a correct guess
  (whole-word match against the password); the game reveals immediately
  when that happens instead of forcing the remaining clue turns.
- Conversation history and an optional kid's name live in workflow state
  and are passed to each LLM call for continuity and personalization. The
  name comes from the child's reply to the opening greeting's name-ask
  (`greet()`), best-effort extracted — no name if they don't give a clean
  one.

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

Simulates a full conversation through the real stack (Temporal + Bedrock)
and prints the greeting plus each pirate line. Example output:

```
[Cheerfully] Ahoy there, me young buccaneer! Welcome to me spooky ship — what be yer name, friend?
Ahoy there, Billy! [Chuckles] What I be thinkin' of makes a pirate's heart go thump-thump — can ye guess?
turn 2: Arrr, Billy, here be a hint: ye'd find it deep in the briny sea …
turn 3: The word starts with the letter 'T', matey!
turn 4: One more nudge... it be just one word long!
turn 5: Arrr, Billy, ye've got it — the answer be Treasure! Ye be a true pirate now!
```

Every clue turn should be freshly worded (LLM), escalate in specificity,
use the captured name where it fits, and never contain the password
before the reveal turn. If the child's simulated utterance ever contains
the real password, the game ends immediately with a `correct_guess`
celebration instead of running the remaining turns — the smoke test's
generic filler utterances won't trigger this, but see
`test_correct_guess_ends_game_early` in the test suite for a scripted
example. If Bedrock is slow or down you'll see the static templates
instead — the game still completes.

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
