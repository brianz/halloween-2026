# Haunted Pirates — Captain Barnaby Bones
# `just` recipes for dev, test, and the night-of kiosk.
# Requires `just` (brew install just) and the project venv at .venv.

default: list

# Show available recipes
list:
    @just --list

# ---- dependencies ----------------------------------------------------------

# Install Python deps into the project venv
deps:
    uv pip install --python .venv/bin/python temporalio boto3 pytest pytest-asyncio fastapi "uvicorn[standard]" python-multipart httpx

# ---- tests -----------------------------------------------------------------

# Run unit tests (mocked activities — no AWS needed)
test:
    .venv/bin/python -m pytest test_pirate_workflow.py

# ---- individual services ---------------------------------------------------

# Start the local Temporal dev server (localhost:7233, UI at :8233)
temporal:
    temporal server start-dev

# Start the Temporal worker (real Bedrock calls — uses brianz-admin profile)
worker:
    PIRATE_AWS_PROFILE=brianz-admin .venv/bin/python temporal_worker.py

# Text-only end-to-end smoke test (no ElevenLabs needed, prints 6 lines to stdout)
smoke:
    PIRATE_AWS_PROFILE=brianz-admin .venv/bin/python brain_server_sketch.py

# Browser voice-test console — mic in, custom-voice TTS out.
# Needs ELEVEN_LABS_API_KEY in the environment (direnv handles it).
# Open http://127.0.0.1:8123 (8000 is taken by an unrelated project).
console:
    .venv/bin/python -m uvicorn voice_console:app --host 127.0.0.1 --port 8123

# ---- combos ----------------------------------------------------------------

# Everything for browser voice testing in one command.
# Starts the temporal dev server, waits for it, then worker + console.
# Ctrl-C stops the foreground console; `just stop` kills the rest.
dev:
    @echo "Starting temporal dev server, worker, and voice console…"
    @echo "Open http://127.0.0.1:8123 once all three are up."
    just --justfile '{{ justfile() }}' temporal >/dev/null 2>&1 &
    @sleep 2
    just --justfile '{{ justfile() }}' worker &
    just --justfile '{{ justfile() }}' console

# ---- cleanup ----------------------------------------------------------------

# Kill the background dev processes started by `just dev`
stop:
    @-pkill -f "temporal server start-dev" && echo "temporal stopped" || echo "temporal not running"
    @-pkill -f "temporal_worker.py" && echo "worker stopped" || echo "worker not running"
    @-pkill -f "voice_console:app" && echo "console stopped" || echo "console not running"
