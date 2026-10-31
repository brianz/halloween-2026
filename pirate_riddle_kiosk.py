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

Run:  .venv/bin/python pirate_riddle_kiosk.py [--record]
Stop: the agent hangs up on its own once the game ends (correct guess or
      out_of_guesses) via ElevenLabs' built-in end_call tool, and the script
      exits right after — rerun it for the next kid. Ctrl-C still works as
      a manual override (e.g. a kid who walks away mid-game). If the
      process is wedged and Ctrl-C in its own terminal won't land,
      `just kill-riddle-kiosk` from a second terminal sends it the same
      SIGINT from the process id this script drops in
      current_riddle_kiosk.pid at startup.

Pass --record to write two local WAV files to recordings/ for the session —
the kid's mic input and the Captain's TTS output, named by that session's
id. Off by default. See RecordingAudioInterface below.
"""

import argparse
import os
import random
import re
import sys
import uuid
import wave
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

# Overwritten with this process's pid at startup, so `just kill-riddle-kiosk`
# can force-quit a wedged session from a second terminal (plain SIGINT — the
# same signal Ctrl-C sends) without hunting for the pid by hand.
CURRENT_SESSION_FILE = Path(__file__).with_name("current_riddle_kiosk.pid")

RECORDINGS_DIR = Path(__file__).with_name("recordings")

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

MAX_GUESSES = 3

# One is picked at random per kid (see build_config) so the line doesn't go
# stale over a night of repeat greetings. Each one asks for the child's name
# exactly once, matching the prompt's "ask once, never again" rule.
FIRST_MESSAGES = [
    "[chuckles] Well, well... another landlubber washes up on me shore. "
    "I be Captain Barnaby Bones! What be yer name, little matey?",
    "[laughs] Shiver me timbers, a new face! I be Captain Barnaby Bones, "
    "ghost of the seven seas. Tell me yer name, young buccaneer!",
    "[whistles] Ahoy there! Captain Barnaby Bones at yer service, haunting "
    "this here chest for one more Halloween. Who do I have the pleasure "
    "of spookin' tonight?",
    "[mischievously] Well if it isn't another brave soul... I be Captain "
    "Barnaby Bones, and this be me ship for the evening! What should I "
    "call ye, matey?",
    "[excited] Arrr, a visitor! I be Captain Barnaby Bones, scourge of "
    "the candy seas! What be yer name, friend?",
]


def pick_riddle() -> dict:
    return random.choice(RIDDLE_POOL)


def build_config(riddle: dict) -> ConversationInitiationData:
    prompt = Path(__file__).with_name("pirate_riddle_prompt.txt").read_text()
    all_answer_words = [word for r in RIDDLE_POOL for word in r["answer"].split()]

    return ConversationInitiationData(
        dynamic_variables={"riddle": riddle["riddle"], "answer": riddle["answer"]},
        conversation_config_override={
            "agent": {
                "prompt": {"prompt": prompt},
                "first_message": random.choice(FIRST_MESSAGES),
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
    # Local closure state — the whole-game equivalent of the Temporal
    # workflow's outcome/guesses fields, just living in this process instead
    # of durable workflow history. Once outcome != "playing", any further
    # call is rejected the same way a 4th Update would be: told the game's
    # over rather than silently given another hint.
    state = {"outcome": "playing", "guesses": []}

    def check_guess(parameters: dict) -> str:
        """Deterministic guess check — the agent calls this every turn.
        MUST return a string: the orchestrator's websocket validator
        rejects non-string client tool results with a 1008 policy
        violation, which kills the whole session."""
        guess = parameters.get("guess", "")

        if state["outcome"] != "playing":
            print(f"  [check_guess] {guess!r} -> rejected, already {state['outcome']}")
            return "the game's already over — reveal the answer and move on."

        state["guesses"].append(guess)
        correct = _guess_correct(guess, answer)
        if correct:
            state["outcome"] = "correct"
        elif len(state["guesses"]) >= MAX_GUESSES:
            state["outcome"] = "out_of_guesses"

        print(
            f"  [check_guess] {guess!r} -> {state['outcome']} "
            f"({len(state['guesses'])}/{MAX_GUESSES} guesses used)"
        )

        if state["outcome"] == "correct":
            return f"correct — the answer is {answer}. Reveal it now and celebrate!"
        if state["outcome"] == "out_of_guesses":
            return (
                "out_of_guesses — gently reveal the answer and send them to the chest."
            )
        remaining = MAX_GUESSES - len(state["guesses"])
        noun = "guess" if remaining == 1 else "guesses"
        return f"incorrect — {remaining} {noun} left, give the clue for this turn."

    tools.register("check_guess", check_guess)
    return tools, state


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


# --- Recording mic input + agent output to local WAV files -----------------
#
# DefaultAudioInterface already receives every raw PCM chunk going in each
# direction (16-bit mono, 16kHz — see its INPUT/OUTPUT constants); this just
# tees each chunk to a WAV file before handing it on, so no extra network
# calls or re-encoding. Two mono files rather than one stereo mix, since mic
# and agent audio arrive on independent threads with no shared clock to
# interleave them against — ffmpeg can merge them afterward if a single file
# is wanted.


class RecordingAudioInterface(DefaultAudioInterface):
    SAMPLE_RATE = 16000

    def __init__(self, mic_path: Path, agent_path: Path) -> None:
        super().__init__()
        self._mic_wav = self._open_wav(mic_path)
        self._agent_wav = self._open_wav(agent_path)

    def _open_wav(self, path: Path) -> wave.Wave_write:
        w = wave.open(str(path), "wb")
        w.setnchannels(1)
        w.setsampwidth(2)  # paInt16
        w.setframerate(self.SAMPLE_RATE)
        return w

    def _in_callback(self, in_data, frame_count, time_info, status):
        self._mic_wav.writeframes(in_data)
        self._agent_wav.writeframes(in_data)  # agent output is also fed to _in_callback
        return super()._in_callback(in_data, frame_count, time_info, status)

    def output(self, audio: bytes) -> None:
        self._agent_wav.writeframes(audio)
        super().output(audio)

    def stop(self) -> None:
        super().stop()
        self._mic_wav.close()
        self._agent_wav.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record",
        action="store_true",
        help="Record this session's mic input and agent output to recordings/ (off by default)",
    )
    return parser.parse_args()


def run_kid_session(riddle: dict, record: bool = False) -> None:
    session_id = f"riddle-session-{uuid.uuid4()}"
    print(f"  [session] id {session_id!r}")
    CURRENT_SESSION_FILE.write_text(str(os.getpid()))

    mic_path = agent_path = ""

    if record:
        RECORDINGS_DIR.mkdir(exist_ok=True)
        mic_path = RECORDINGS_DIR / f"{session_id}_mic.wav"
        agent_path = RECORDINGS_DIR / f"{session_id}_agent.wav"
        audio_interface = RecordingAudioInterface(mic_path, agent_path)
    else:
        audio_interface = DefaultAudioInterface()

    tools, state = make_client_tools(riddle["answer"])
    client = ElevenLabs(api_key=API_KEY)
    conversation = Conversation(
        client,
        AGENT_ID,
        requires_auth=True,
        audio_interface=audio_interface,
        config=build_config(riddle),
        client_tools=tools,
        callback_agent_response=lambda resp: print(f"☠ Captain: {resp}"),
        callback_user_transcript=lambda text: print(f"🧒 Kid: {text}"),
    )
    conversation.start_session()
    try:
        conversation.wait_for_session_end()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        conversation.end_session()  # blocks until audio_interface.stop() finishes (closes WAV files if recording)
        if record:
            print(f"  [recording] mic:   {mic_path}")
            print(f"  [recording] agent: {agent_path}")
        print(
            f"  [session] outcome={state['outcome']!r} "
            f"guesses={state['guesses']!r}"
        )


if __name__ == "__main__":
    args = parse_args()
    riddle = pick_riddle()
    print(f"🗡  This kid's riddle: {riddle['riddle']}")
    print(f"    Answer (ssh, don't tell): {riddle['answer']}")
    if args.record:
        print("    Recording this session to recordings/.")
    print("    Talk to the Captain! Ctrl-C when the kid walks off.\n")
    run_kid_session(riddle, record=args.record)
