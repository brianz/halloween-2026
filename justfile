# Haunted Pirates — Captain Barnaby Bones
# `just` recipes for the ElevenLabs hosted-agent kiosk.
# Requires `just` (brew install just) and the project venv at .venv.

default: list

# Show available recipes
list:
    @just --list

# ---- dependencies ----------------------------------------------------------

# Sync Python deps from pyproject.toml into the project venv
deps:
    uv sync

# ---- the kiosk -------------------------------------------------------------

# One kid's session: picks a password, talks to the Captain (mic + speakers),
# Ctrl-C when the kid walks off. Run again for the next kid.
kiosk:
    .venv/bin/python pirate_kiosk.py

# One kid's session, riddle mode: picks a riddle instead of a bare password.
# Pass --record to also save mic + agent audio to recordings/ (off by default).
riddle-kiosk *args:
    .venv/bin/python pirate_riddle_kiosk.py {{args}}

# Force-quit a wedged riddle-kiosk session from a second terminal — sends it
# the same SIGINT Ctrl-C would. Normal "kid walked off" case is just Ctrl-C
# in the kiosk's own terminal; this is the break-glass fallback.
kill-riddle-kiosk:
    kill -INT "$(cat current_riddle_kiosk.pid)"

# ---- diagnostics -------------------------------------------------------------

# Record a few seconds from the default mic and report its peak level — no
# ElevenLabs, no Temporal, just PortAudio. Use this to isolate a mic problem
# from the kiosk/ElevenLabs stack. See mic_test.py for what it checks.
mic-test *args:
    .venv/bin/python mic_test.py {{args}}
