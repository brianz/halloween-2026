"""
The kiosk brain for Captain Barnaby Bones, on the ElevenLabs hosted agent.

One run of this script = one kid's conversation:
  1. Pick a random password (locally, with plain random — a fresh process
     per kid means fresh state by construction, no session-memory problem).
  2. Start a Conversation with the agent, overriding the system prompt
     with pirate_prompt.txt (password + clue rules injected as a dynamic
     variable) and boosting the password words in ASR.
  3. Register a check_guess client tool: the agent calls it every turn,
     this code does the deterministic word-match, and the agent reveals
     immediately on a correct guess. Game logic is ours; the LLM only
     wordsmiths.

Dashboard one-time setup (agent "Ghost Pirate Captain"):
  - Security tab: enable System prompt + First message + ASR keywords
    overrides.
  - Tools tab: add a CLIENT tool named check_guess with one required
    string parameter "guess".

Run:  .venv/bin/python pirate_kiosk.py
Stop: Ctrl-C ends the session (next kid = run it again).
"""

import os
import random
import re
import sys
from pathlib import Path

from elevenlabs.client import ElevenLabs
from elevenlabs.conversational_ai.conversation import (
    Conversation,
    ConversationInitiationData,
)
from elevenlabs.conversational_ai.default_audio_interface import DefaultAudioInterface

# The Ghost Pirate Captain agent. (Don't put this in ELEVEN_LABS_AGENT_KEY_ID —
# that direnv var actually holds an API *key* id, not an agent id; it 404s.)
AGENT_ID = os.environ.get("PIRATE_AGENT_ID", "agent_5401m084pnhxf0z8bdyzj8depdes")

API_KEY = os.environ.get("ELEVEN_LABS_API_KEY", "")
if not API_KEY:
    sys.exit("Set ELEVEN_LABS_API_KEY to a key with ElevenAgents read+write.")

PASSWORD_POOL = [
    "Treasure",
    "Parrot",
    "Ship",
    "Gold",
    "Anchor",
    "Map",
    "Compass",
    "Island",
    "Hook",
    "Cannon",
]

# The line the agent says before the child's first guess; kept here so the
# dashboard copy doesn't matter — the kiosk is the source of truth.
FIRST_MESSAGE = (
    "[chuckles] Well, well... another landlubber washes up on me shore. "
    "I be Captain Barnaby Bones! What be yer name, little matey?"
)


def pick_password() -> str:
    return random.choice(PASSWORD_POOL)


def build_config(password: str) -> ConversationInitiationData:
    prompt = Path(__file__).with_name("pirate_prompt.txt").read_text()
    return ConversationInitiationData(
        dynamic_variables={"password": password},
        conversation_config_override={
            "agent": {
                "prompt": {"prompt": prompt},
                "first_message": FIRST_MESSAGE,
            },
            # Boost the password words so a mumbled "anchor" still
            # transcribes reliably. Needs the ASR keywords override enabled.
            "asr": {"keywords": PASSWORD_POOL},
        },
    )


def make_client_tools(password: str):
    from elevenlabs.conversational_ai.conversation import ClientTools

    tools = ClientTools()

    def check_guess(parameters: dict) -> str:
        """Deterministic guess check — the agent calls this every turn.
        MUST return a string: the orchestrator's websocket validator
        rejects non-string client tool results with a 1008 policy
        violation, which kills the whole session."""
        guess = parameters.get("guess", "")
        correct = _guess_correct(guess, password)
        print(f"  [check_guess] {guess!r} -> {'CORRECT' if correct else 'nope'}")
        if correct:
            return f"correct — the password is {password}. Reveal it now and celebrate!"
        return "incorrect — keep playing, give the clue for this turn."

    tools.register("check_guess", check_guess)
    return tools


def _guess_correct(guess: str, password: str) -> bool:
    """Whole-word match (same rule the Temporal workflow used): 'Map'
    doesn't false-positive on 'I mapped it out'."""

    def words(s: str) -> list[str]:
        return re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()

    pw_words = words(password)
    g_words = words(guess)
    if not pw_words:
        return False
    n = len(pw_words)
    return any(g_words[i : i + n] == pw_words for i in range(len(g_words) - n + 1))


def run_kid_session(password: str) -> None:
    client = ElevenLabs(api_key=API_KEY)
    conversation = Conversation(
        client,
        AGENT_ID,
        requires_auth=True,
        audio_interface=DefaultAudioInterface(),
        config=build_config(password),
        client_tools=make_client_tools(password),
        callback_agent_response=lambda resp: print(f"☠ Captain: {resp}"),
        callback_user_transcript=lambda text: print(f"🧒 Kid: {text}"),
    )
    conversation.start_session()
    try:
        conversation.wait_for_session_end()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        conversation.end_session()


if __name__ == "__main__":
    password = pick_password()
    print(f"🗡  This kid's password: {password}  (ssh, don't tell)")
    print("    Talk to the Captain! Ctrl-C when the kid walks off.\n")
    run_kid_session(password)
