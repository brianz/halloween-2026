# Haunted Pirates — Captain Barnaby Bones

A Halloween kiosk game. Kids walk up and talk to **Captain Barnaby
Bones**, a friendly skeleton pirate (a custom ElevenLabs voice). He greets
them, asks their name, and plays a password guessing game — a
progressively-easier clue each turn. If the kid guesses the password at
any point, he reveals it immediately and celebrates; otherwise he reveals
it after the last clue. The kid brings the password to a nearby treasure
chest to claim candy.

## How it works

The whole thing runs on the **ElevenLabs hosted Conversational AI agent**
(realtime streaming ASR + TTS, interruption handling, the custom Captain
voice, `eleven_v3_conversational` TTS with audio tags like `[laughs]`,
Claude Haiku as the LLM) — but **the kiosk script owns the game logic**:

- `pirate_kiosk.py` picks a random password locally, then starts one
  conversation per kid: **one process = one kid = fresh state by
  construction**. No session-memory problems, nothing to clean up between
  kids — run the script again.
- The full system prompt lives in `pirate_prompt.txt` (in this repo, not
  buried in the ElevenLabs dashboard) and is injected per session via the
  **system-prompt override**. The password itself goes in as a **dynamic
  variable**; turn counting uses the platform's built-in
  `system__agent_turns` counter, so the LLM never has to keep count.
- The agent calls the **`check_guess` client tool** every turn; the
  deterministic whole-word password match runs locally in the kiosk
  script. A correct guess short-circuits straight to the reveal — the LLM
  can't mess up that decision because it doesn't make it.
- The **ASR keywords override** passes the password pool each session, so
  a mumbled "anchor" still transcribes reliably.

```
       ┌────────────── ElevenLabs cloud ──────────────┐
       │  realtime ASR ─▶ Claude Haiku ─▶ v3 TTS      │
       │      (custom Captain voice, audio tags)      │
       └──────┬───────────────────────────▲───────────┘
              │ transcripts              │ spoken lines
       ┌──────▼───────────────────────────┴───────────┐
       │ pirate_kiosk.py (laptop)                     │
       │  • picks password (random.choice)            │
       │  • injects prompt + password per session     │
       │  • check_guess client tool (local, exact)    │
       │  • mic + speakers                            │
       └──────────────────────────────────────────────┘
```

## Running it on Halloween

You'll run this from your laptop with a mic and speakers (or headphones
to avoid the mic picking up the Captain's own voice).

### One-time setup (already done — skip this unless re-provisioning)

1. An ElevenLabs API key with **ElevenAgents: Read + Write** permission
   (created in the ElevenLabs dashboard → API keys). No other endpoint
   permissions are needed.
2. The "Ghost Pirate Captain" agent exists in your ElevenLabs workspace
   (id in `ELEVEN_LABS_AGENT_KEY_ID`) with the custom voice
   (`TG2O4Qh067u8gMkJrjhR`) and `eleven_v3_conversational` TTS model.
3. Agent security overrides (system prompt, first message, ASR keywords)
   and the `check_guess` client tool are configured — this was done via
   the API; see CLAUDE.md "One-time agent setup" for the exact calls.

### Every time (deps + env)

```bash
brew install just portaudio   # once, if not already installed
uv sync                       # installs elevenlabs[pyaudio] into .venv
```

Environment (e.g. via direnv in `.envrc`):

```bash
export ELEVEN_LABS_API_KEY=...        # key with ElevenAgents read+write
export ELEVEN_LABS_AGENT_KEY_ID=agent_5401m084pnhxf0z8bdyzj8depdes
```

### Per kid

```bash
just kiosk          # or: .venv/bin/python pirate_kiosk.py
```

- The script picks a secret password and prints it to your terminal
  (`🗡 This kid's password: Gold (ssh, don't tell)`) — glance at it so you
  can help a stuck kid, but keep it away from small eyes.
- The Captain greets the kid through your speakers and listens on your
  mic. Talk normally; he handles interruptions.
- The terminal shows the live transcript (`☠ Captain:` / `🧒 Kid:` lines)
  and every `check_guess` call.
- When the kid walks off: **Ctrl-C**. Run `just kiosk` again for the next
  kid — new password, fresh conversation, nothing to reset.

**Troubleshooting on the night:**

- No mic/speaker audio → check macOS Sound settings; the script uses the
  system default devices. Grant mic permission to your terminal app if
  prompted.
- `ImportError: pyaudio` → `brew install portaudio && uv sync`.
- 401/403 from ElevenLabs → the API key lost ElevenAgents Read+Write, or
  `ELEVEN_LABS_API_KEY` isn't exported in this shell.
- The internet is a hard dependency on the night (the agent runs in
  ElevenLabs' cloud). If wifi dies, the game is down — have a bowl of
  candy as the manual fallback.

## Tuning the game

- **Persona, clue ladder, reveal rules, audio tags** → `pirate_prompt.txt`
  (the single source of truth for agent behavior; takes effect on the
  next `just kiosk` run — no dashboard edits needed).
- **Password pool** → `PASSWORD_POOL` at the top of `pirate_kiosk.py`.
  Keep it in sync with nothing else — the ASR keywords are derived from
  it automatically.
- **Opening line** → `FIRST_MESSAGE` in `pirate_kiosk.py`.

## Project layout

| File | Role |
| --- | --- |
| `pirate_kiosk.py` | One kid's session: pick password, start the Conversation with overrides + ASR keywords, register `check_guess`, print the transcript |
| `pirate_prompt.txt` | The full system prompt: persona, clue ladder, reveal rules, audio-tag whitelist |
| `CLAUDE.md` | Architecture notes and gotchas (for AI assistants working on this repo) |

## History

Earlier iterations are gone but worth a line: a hosted-agent version
abandoned because the no-code console made the agent "simplistic" (the
SDK fixes that — which is what we use now); then a Temporal-workflow
version with local batch ASR → Bedrock → batch TTS, retired because each
turn cost seconds of serial round-trips. The current design keeps the
hosted agent's voice and latency but owns the game logic in the kiosk
script.
