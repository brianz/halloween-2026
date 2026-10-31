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

Pass --record to write one local stereo WAV file to recordings/ for the
session — left channel the kid's mic, right channel the Captain's TTS
output — named by that session's id. Off by default. See
RecordingAudioInterface below.
"""

import argparse
import array
import os
import random
import re
import sys
import threading
import time
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

# "difficulty" is a 1 (easiest) to 10 (hardest) guess at how hard each
# riddle is for a trick-or-treater to solve, used to pick a riddle when the
# kiosk-ui passes --difficulty. One riddle per level by design, so the UI's
# 1-10 dial maps onto an exact riddle rather than a fuzzy nearest-match —
# these ratings are a first guess (see CLAUDE.md), expect them to get
# reshuffled once there's real kid-reaction data from the night.
RIDDLE_POOL = [
    {
        "riddle": (
            "I'm made of old wood with a big lock on my lid. Fill me "
            "with gold and jewels and I'll make any pirate smile. "
            "What am I?"
        ),
        "answer": "Treasure Chest",
        "difficulty": 1,
    },
    {
        "riddle": (
            "I sit upon a pirate's shoulder and squawk words I don't "
            "understand. My feathers shine as bright as treasure. "
            "What bird am I?"
        ),
        "answer": "Parrot",
        "difficulty": 2,
    },
    {
        "riddle": (
            "I'm big and round and made of iron. I go BOOM and send "
            "cannonballs flying across the sea. What am I?"
        ),
        "answer": "Cannon",
        "difficulty": 3,
    },
    {
        "riddle": (
            "I'm covered in dusty lines and a big red X. I show you "
            "where the treasure hides, but I am not the treasure "
            "myself. What am I?"
        ),
        "answer": "Map",
        "difficulty": 4,
    },
    {
        "riddle": (
            "I'm heavy as a cannonball and I sleep at the bottom of the "
            "sea. I keep your ship from sailing away in the night. "
            "What am I?"
        ),
        "answer": "Anchor",
        "difficulty": 5,
    },
    {
        "riddle": (
            "I'm curved like the moon and shiny like silver. Some "
            "pirates wear me instead of a hand. What am I?"
        ),
        "answer": "Hook",
        "difficulty": 6,
    },
    {
        "riddle": (
            "I always point the way home. I have no legs, yet I never "
            "get lost, and sailors trust me more than the stars. "
            "What am I?"
        ),
        "answer": "Compass",
        "difficulty": 7,
    },
    {
        "riddle": (
            "I have no skin, no flesh, no fright — just bones that "
            "rattle in the night. I'm a pirate captain's oldest crew "
            "member. What am I?"
        ),
        "answer": "Skeleton",
        "difficulty": 8,
    },
    {
        "riddle": (
            "I'm a flag that flies high above a pirate ship. I'm black "
            "as night with a skull and crossbones for my face, and I "
            "scare sailors before they even see the ship below me. "
            "What am I?"
        ),
        "answer": "Jolly Roger",
        "difficulty": 9,
    },
    {
        "riddle": (
            "I'm long and thin, and when you peek through one end of "
            "me, far-away ships look close enough to touch. "
            "What am I?"
        ),
        "answer": "Spyglass",
        "difficulty": 10,
    },
]

MAX_GUESSES = 3

# Fallback only: the agent is supposed to hang up itself via end_call right
# after the reveal (see pirate_riddle_prompt.txt), but it doesn't always
# remember to — unlike a wrong guess, there's no later check_guess call to
# nudge it back on track once the game is already over, since the kid has
# no reason to guess again. watch_for_game_end() uses TimingAudioInterface
# to detect when the Captain's queued speech has actually finished playing
# (not a guessed delay — a cutoff would risk dropping the end of a longer
# reveal line) before forcing the session closed. These constants only
# matter for that fallback path:
#   - SPEECH_START_TIMEOUT_SECONDS: how long to wait for the reveal's audio
#     to actually start arriving before giving up on it ever coming — the
#     LLM + TTS take a beat after the tool call returns, so "no audio yet"
#     right after the guess means "hasn't started", not "already done".
#   - QUIET_SETTLE_SECONDS: once speech HAS started, how long the audio
#     queue must then stay empty before we trust he's actually finished —
#     TTS chunks can have brief gaps mid-sentence, not just between turns.
#   - MAX_WAIT_FOR_END_CALL_SECONDS: an absolute ceiling in case something
#     is badly wrong (e.g. audio stuck "playing" forever) — the process
#     should never hang indefinitely regardless.
SPEECH_START_TIMEOUT_SECONDS = 5.0
QUIET_SETTLE_SECONDS = 0.6
MAX_WAIT_FOR_END_CALL_SECONDS = 30.0

# Confirmed live: conversation.end_session() can hang the ENTIRE process,
# Ctrl-C included. Its own code calls audio_interface.stop() — which joins
# DefaultAudioInterface's output thread, which can be stuck inside a
# blocking pyaudio stream.write() — before it sets `_should_stop`, so if
# that join() never returns, the websocket thread never learns to exit
# either, and wait_for_session_end() (and a Ctrl-C handler's own call to
# end_session(), which hits the exact same stuck join()) both hang with
# it. See end_session_or_die().
END_SESSION_TIMEOUT_SECONDS = 5.0

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


def pick_riddle(difficulty: int | None = None) -> dict:
    """With no difficulty, pick uniformly at random (the original
    behavior). With one, pick the riddle tagged with that exact level —
    RIDDLE_POOL has one per 1-10 level by construction."""
    if difficulty is None:
        return random.choice(RIDDLE_POOL)
    for riddle in RIDDLE_POOL:
        if riddle["difficulty"] == difficulty:
            return riddle
    sys.exit(f"No riddle tagged difficulty={difficulty!r} in RIDDLE_POOL.")


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


def watch_for_game_end(
    state: dict,
    conversation: Conversation,
    session_ended: threading.Event,
    audio_interface: "TimingAudioInterface",
) -> None:
    """Fallback for when the agent doesn't call end_call itself after the
    reveal — mirrors temporal_riddle_kiosk's watch_for_workflow_end, just
    polling local `state` instead of a Temporal workflow handle. Runs in
    its own daemon thread so it never blocks process exit on its own.

    Once the outcome is decided, waits for `audio_interface` to report the
    Captain's queued speech has actually finished playing (plus a short
    settle period, since TTS chunks can have brief gaps mid-sentence) —
    not a guessed fixed delay, which would either cut off a longer reveal
    line or leave needless dead air after a short one.

    Two phases, because `still_speaking()` is also False in the few hundred
    ms to a couple seconds between the tool call returning and the first
    reveal audio chunk actually arriving (LLM + TTS latency) — checking it
    immediately would end the call before the reveal even starts, which is
    worse than a late cutoff. So first wait for *new* audio (a chunk after
    the outcome was decided) to show up at all, bounded by
    SPEECH_START_TIMEOUT_SECONDS; only once speech has actually started do
    we treat "queue empty" as "finished" rather than "hasn't begun yet".
    """
    while not session_ended.is_set() and state["outcome"] == "playing":
        time.sleep(0.3)
    if session_ended.is_set():
        return  # ended on its own (end_call, or an operator Ctrl-C) already

    outcome_decided_at = time.monotonic()
    print(f"  [session] outcome={state['outcome']!r} — waiting for the Captain to finish speaking")

    start_deadline = outcome_decided_at + SPEECH_START_TIMEOUT_SECONDS
    while not session_ended.is_set() and time.monotonic() < start_deadline:
        if audio_interface.spoke_since(outcome_decided_at):
            break
        time.sleep(0.2)
    if session_ended.is_set():
        return

    deadline = outcome_decided_at + MAX_WAIT_FOR_END_CALL_SECONDS
    while not session_ended.is_set() and time.monotonic() < deadline:
        if audio_interface.still_speaking():
            time.sleep(0.2)
            continue
        if session_ended.wait(timeout=QUIET_SETTLE_SECONDS):
            return  # ended on its own during the settle window
        if not audio_interface.still_speaking():
            break  # confirmed quiet — safe to end now

    if not session_ended.is_set():
        print("  [session] ending the session now")
        end_session_or_die(conversation)


def end_session_or_die(conversation: Conversation) -> None:
    """conversation.end_session() can block the ENTIRE process, Ctrl-C
    included — confirmed live, not theoretical (see
    END_SESSION_TIMEOUT_SECONDS above). Rather than chase whatever made
    pyaudio's output thread get stuck, give normal cleanup a bounded
    window and hard-exit the whole process if it blows past it. The
    kiosk's real requirement is "always ready for the next kid, rerun the
    script" — not "every session's audio interface tears down cleanly".
    A --record session caught by this loses that session's WAV file
    (RecordingAudioInterface writes it inside the very call being
    abandoned) — an acceptable trade for never hanging.
    """
    done = threading.Event()

    def _do_end() -> None:
        try:
            conversation.end_session()
        finally:
            done.set()

    threading.Thread(target=_do_end, daemon=True).start()
    if not done.wait(timeout=END_SESSION_TIMEOUT_SECONDS):
        print(
            f"  [session] end_session() didn't return within "
            f"{END_SESSION_TIMEOUT_SECONDS:.0f}s — force-exiting",
            flush=True,
        )
        os._exit(1)


# --- Knowing when the Captain has actually finished talking ---------------
#
# DefaultAudioInterface.output() hands us each raw 16-bit PCM chunk right
# before queueing it for playback. A chunk's byte length maps directly to a
# playback duration at a known sample rate, so we can track exactly when
# all currently-queued audio will finish playing — busy_until — without
# guessing. watch_for_game_end() uses this to know it's actually safe to
# hang up, instead of a fixed delay that could cut off a long reveal line
# or leave dead air after a short one.


class TimingAudioInterface(DefaultAudioInterface):
    SAMPLE_RATE = 16000
    SAMPLE_WIDTH = 2  # 16-bit PCM, matches DefaultAudioInterface's formats

    def __init__(self) -> None:
        super().__init__()
        self._timing_lock = threading.Lock()
        self._busy_until = time.monotonic()
        self._last_chunk_at: float | None = None

    def output(self, audio: bytes) -> None:
        duration = len(audio) / (self.SAMPLE_RATE * self.SAMPLE_WIDTH)
        with self._timing_lock:
            now = time.monotonic()
            self._busy_until = max(self._busy_until, now) + duration
            self._last_chunk_at = now
        super().output(audio)

    def still_speaking(self) -> bool:
        with self._timing_lock:
            return time.monotonic() < self._busy_until

    def spoke_since(self, reference: float) -> bool:
        """True once a chunk has arrived at or after `reference` — used to
        tell "hasn't started speaking yet" apart from "already finished",
        both of which otherwise look identical to still_speaking()."""
        with self._timing_lock:
            return self._last_chunk_at is not None and self._last_chunk_at >= reference


# --- Recording mic input + agent output to a single stereo WAV file -------
#
# Mic input arrives continuously on one thread; agent TTS output arrives in
# bursts on another, only while the agent is actually speaking — there's no
# shared clock between them, so naively appending both streams into one file
# as chunks arrive would interleave them in whatever order they happened to
# land, scrambling both. Instead each chunk is timestamped against session
# start and silence-padded into its correct position before being merged, so
# the single output file's left (mic) and right (Captain) channels stay in
# sync with when each side actually spoke.


class RecordingAudioInterface(TimingAudioInterface):
    def __init__(self, output_path: Path) -> None:
        super().__init__()
        self._output_path = output_path
        self._start_time = time.monotonic()
        self._lock = threading.Lock()
        self._mic_chunks: list[tuple[float, bytes]] = []
        self._agent_chunks: list[tuple[float, bytes]] = []

    def _in_callback(self, in_data, frame_count, time_info, status):
        with self._lock:
            self._mic_chunks.append((time.monotonic() - self._start_time, in_data))
        return super()._in_callback(in_data, frame_count, time_info, status)

    def output(self, audio: bytes) -> None:
        with self._lock:
            self._agent_chunks.append((time.monotonic() - self._start_time, audio))
        super().output(audio)  # chains to TimingAudioInterface.output() for busy_until

    def stop(self) -> None:
        super().stop()
        self._write_merged_file()

    def _render_track(self, chunks: list[tuple[float, bytes]]) -> bytes:
        """Lay chunks out at their recorded offset from session start,
        silence-padding any gap — e.g. the agent going quiet while the kid
        talks — instead of just concatenating them back to back."""
        buf = bytearray()
        for offset, data in chunks:
            target_len = int(offset * self.SAMPLE_RATE) * self.SAMPLE_WIDTH
            if target_len > len(buf):
                buf.extend(b"\x00" * (target_len - len(buf)))
            buf.extend(data)
        return bytes(buf)

    def _write_merged_file(self) -> None:
        with self._lock:
            mic_bytes = self._render_track(self._mic_chunks)
            agent_bytes = self._render_track(self._agent_chunks)

        mic_samples = array.array("h", mic_bytes)
        agent_samples = array.array("h", agent_bytes)
        n = max(len(mic_samples), len(agent_samples))
        mic_samples.extend([0] * (n - len(mic_samples)))
        agent_samples.extend([0] * (n - len(agent_samples)))

        stereo = array.array("h", bytes(2 * self.SAMPLE_WIDTH * n))
        stereo[0::2] = mic_samples  # left channel: the kid's mic
        stereo[1::2] = agent_samples  # right channel: the Captain

        with wave.open(str(self._output_path), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(self.SAMPLE_WIDTH)
            w.setframerate(self.SAMPLE_RATE)
            w.writeframes(stereo.tobytes())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record",
        action="store_true",
        help="Record this session to a stereo WAV file in recordings/ (off by default)",
    )
    parser.add_argument(
        "--difficulty",
        type=int,
        choices=range(1, 11),
        default=None,
        metavar="1-10",
        help="Pick the riddle tagged with this difficulty instead of a random one "
        "(driven by kiosk-ui; omit for the original random-pick behavior)",
    )
    return parser.parse_args()


def run_kid_session(riddle: dict, record: bool = False) -> None:
    session_id = f"riddle-session-{uuid.uuid4()}"
    print(f"  [session] id {session_id!r}")
    CURRENT_SESSION_FILE.write_text(str(os.getpid()))

    audio_path = ""

    if record:
        RECORDINGS_DIR.mkdir(exist_ok=True)
        audio_path = RECORDINGS_DIR / f"{session_id}.wav"
        audio_interface = RecordingAudioInterface(audio_path)
    else:
        # Still a TimingAudioInterface, not a plain DefaultAudioInterface —
        # watch_for_game_end needs still_speaking() regardless of --record.
        audio_interface = TimingAudioInterface()

    tools, state = make_client_tools(riddle["answer"])
    session_ended = threading.Event()
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
        callback_end_session=session_ended.set,
    )
    conversation.start_session()
    threading.Thread(
        target=watch_for_game_end,
        args=(state, conversation, session_ended, audio_interface),
        daemon=True,
    ).start()
    try:
        conversation.wait_for_session_end()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        # Only call this if nothing already has — end_call (via the SDK's own
        # ConnectionClosedOK handling) or watch_for_game_end's fallback may
        # have already torn down the audio interface; calling stop() on an
        # already-closed pyaudio stream raises. end_session_or_die() blocks
        # until audio_interface.stop() finishes (writes the WAV file if
        # recording) — or force-exits the process if that hangs, which is
        # exactly what happened on a real test, Ctrl-C included.
        if not session_ended.is_set():
            end_session_or_die(conversation)
        if record:
            print(f"  [recording] {audio_path}")
        print(
            f"  [session] outcome={state['outcome']!r} "
            f"guesses={state['guesses']!r}"
        )


if __name__ == "__main__":
    args = parse_args()
    riddle = pick_riddle(args.difficulty)
    print(f"🗡  This kid's riddle (difficulty {riddle['difficulty']}/10): {riddle['riddle']}")
    print(f"    Answer (ssh, don't tell): {riddle['answer']}")
    if args.record:
        print("    Recording this session to recordings/.")
    print("    Talk to the Captain! Ctrl-C when the kid walks off.\n")
    run_kid_session(riddle, record=args.record)
