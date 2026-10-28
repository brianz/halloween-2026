"""
The kiosk brain for Captain Barnaby Bones' RIDDLE mode, on the ElevenLabs
hosted agent. Same architecture as pirate_kiosk.py, but the child solves a
riddle instead of guessing a bare password.

One run of this script = one kid's conversation:
  1. Pick a random riddle (locally, with plain random — a fresh process
     per kid means fresh state by construction, no session-memory problem).
  2. Start a Conversation with the agent, overriding the system prompt
     with pirate_riddle_prompt.txt (riddle + answer injected as dynamic
     variables) and boosting every riddle's answer words in ASR.
  3. Register a check_guess client tool: the agent calls it every turn,
     this code does the deterministic word-match against the chosen
     riddle's answer, and the agent reveals immediately on a correct
     guess. Game logic is ours; the LLM only wordsmiths.

Dashboard one-time setup (agent "Ghost Pirate Captain", shared with
pirate_kiosk.py):
  - Security tab: enable System prompt + First message + ASR keywords
    overrides.
  - Tools tab: add a CLIENT tool named check_guess with one required
    string parameter "guess".

Run:  .venv/bin/python pirate_riddle_kiosk.py
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

RIDDLE_POOL = [
    {
        "riddle": (
            "I sit upon a pirate's shoulder and squawk words I don't "
            "understand. My feathers shine as bright as treasure. "
            "What bird am I?"
        ),
        "answer": "Parrot",
    },
    {
        "riddle": (
            "I'm heavy as a cannonball and I sleep at the bottom of the "
            "sea. I keep your ship from sailing away in the night. "
            "What am I?"
        ),
        "answer": "Anchor",
    },
    {
        "riddle": (
            "I always point the way home. I have no legs, yet I never "
            "get lost, and sailors trust me more than the stars. "
            "What am I?"
        ),
        "answer": "Compass",
    },
    {
        "riddle": (
            "I'm covered in dusty lines and a big red X. I show you "
            "where the treasure hides, but I am not the treasure "
            "myself. What am I?"
        ),
        "answer": "Map",
    },
    {
        "riddle": (
            "I have no skin, no flesh, no fright — just bones that "
            "rattle in the night. I'm a pirate captain's oldest crew "
            "member. What am I?"
        ),
        "answer": "Skeleton",
    },
]

# The line the agent says before the child's first guess; kept here so the
# dashboard copy doesn't matter — the kiosk is the source of truth.
FIRST_MESSAGE = (
    "[chuckles] Well, well... another landlubber washes up on me shore. "
    "I be Captain Barnaby Bones! What be yer name, little matey?"
)


def pick_riddle() -> dict:
    return random.choice(RIDDLE_POOL)


def build_config(riddle: dict) -> ConversationInitiationData:
    prompt = Path(__file__).with_name("pirate_riddle_prompt.txt").read_text()
    all_answer_words = [
        word for r in RIDDLE_POOL for word in r["answer"].split()
    ]
    return ConversationInitiationData(
        dynamic_variables={"riddle": riddle["riddle"], "answer": riddle["answer"]},
        conversation_config_override={
            "agent": {
                "prompt": {"prompt": prompt},
                "first_message": FIRST_MESSAGE,
            },
            # Boost every riddle's answer words (not just this session's) so
            # a mumbled guess still transcribes reliably without tipping off
            # which riddle is live.
            "asr": {"keywords": all_answer_words},
        },
    )


def make_client_tools(answer: str):
    from elevenlabs.conversational_ai.conversation import ClientTools

    tools = ClientTools()

    def check_guess(parameters: dict) -> str:
        """Deterministic guess check — the agent calls this every turn.
        MUST return a string: the orchestrator's websocket validator
        rejects non-string client tool results with a 1008 policy
        violation, which kills the whole session."""
        guess = parameters.get("guess", "")
        correct = _guess_correct(guess, answer)
        print(f"  [check_guess] {guess!r} -> {'CORRECT' if correct else 'nope'}")
        if correct:
            return f"correct — the answer is {answer}. Reveal it now and celebrate!"
        return "incorrect — keep playing, give the clue for this turn."

    tools.register("check_guess", check_guess)
    return tools


def _guess_correct(guess: str, answer: str) -> bool:
    """Whole-word match (same rule as pirate_kiosk.py): 'Map' doesn't
    false-positive on 'I mapped it out'."""

    def words(s: str) -> list[str]:
        return re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()

    a_words = words(answer)
    g_words = words(guess)
    if not a_words:
        return False
    n = len(a_words)
    return any(g_words[i : i + n] == a_words for i in range(len(g_words) - n + 1))


def run_kid_session(riddle: dict) -> None:
    client = ElevenLabs(api_key=API_KEY)
    conversation = Conversation(
        client,
        AGENT_ID,
        requires_auth=True,
        audio_interface=DefaultAudioInterface(),
        config=build_config(riddle),
        client_tools=make_client_tools(riddle["answer"]),
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
    riddle = pick_riddle()
    print(f"🗡  This kid's riddle: {riddle['riddle']}")
    print(f"    Answer (ssh, don't tell): {riddle['answer']}")
    print("    Talk to the Captain! Ctrl-C when the kid walks off.\n")
    run_kid_session(riddle)
