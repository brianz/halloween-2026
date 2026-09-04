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
