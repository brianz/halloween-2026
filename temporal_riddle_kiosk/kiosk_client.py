"""
The kiosk brain for Captain Barnaby Bones' riddle game, Temporal edition.

Same ElevenLabs hosted-agent architecture as ../pirate_riddle_kiosk.py — the
agent still does all ASR/TTS/voice, the kiosk still owns game logic and the
LLM still only wordsmiths. The difference is WHERE the game logic lives:
instead of a local Python closure matching guesses in-process, each guess is
a Temporal Workflow Update against a RiddleGameWorkflow running on a local
dev server. See README.md in this directory for why, and the tradeoffs.

One run of this script = one kid's conversation = one workflow execution:
  1. Start a RiddleGameWorkflow (it picks the riddle itself, deterministically,
     via workflow.random() — not this script).
  2. Query it once to learn which riddle it picked, to build the agent's
     system-prompt override and ASR keyword list.
  3. Start the ElevenLabs Conversation. Its check_guess client tool sends
     each guess to the workflow as an Update and relays the (synchronous)
     result back to the agent.
  4. On Ctrl-C, signal end_session so the workflow finishes promptly
     instead of idling out its timeout.
  5. The agent itself hangs up when the game ends: the ElevenLabs agent has
     its built-in `end_call` system tool enabled (one-time platform
     config, like the TTS model switch — not set by this script), and
     pirate_riddle_prompt_temporal.txt tells it to call that tool right
     after it speaks the reveal line for "correct" or "out_of_guesses".
     ElevenLabs' orchestrator then closes the websocket itself, which the
     SDK already treats as a normal end_session() (see `_run()`'s
     `ConnectionClosedOK` handling in conversation.py) — so
     wait_for_session_end() returns on its own once the agent is actually
     done talking, no guessing about TTS timing required.
  6. A background watcher (watch_for_workflow_end) is a fallback for paths
     the agent has no reason to hang up for itself — "timed_out" (kid
     walked away, nobody said anything) or "abandoned" (operator's
     Ctrl-C/end_session signal). It ends the ElevenLabs session once the
     workflow ends for any reason, so this process never sits there with
     no game left behind it. An abnormal end (`just kill`, cancel, a real
     failure) hangs up immediately; a clean finish gets a short grace
     period first in case the agent is mid-sentence and hasn't called
     end_call for whatever reason.

Prerequisites (see README.md):
  - `temporal server start-dev` running
  - `python worker.py` running
  - ELEVEN_LABS_API_KEY set

Run:  .venv/bin/python kiosk_client.py [--record]
Stop: Ctrl-C ends the session (next kid = run it again).

Pass --record to write two local WAV files to recordings/ for the session —
the kid's mic input and the Captain's TTS output, named by the workflow id.
Off by default. See RecordingAudioInterface below.
"""

import argparse
import asyncio
import concurrent.futures
import os
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
from models import RIDDLE_POOL, RiddleDef, all_answer_words
from temporalio.client import Client, WorkflowHandle
from workflows import RiddleGameWorkflow

AGENT_ID = os.environ.get("PIRATE_AGENT_ID", "agent_5401m084pnhxf0z8bdyzj8depdes")
API_KEY = os.environ.get("ELEVEN_LABS_API_KEY", "")
if not API_KEY:
    sys.exit("Set ELEVEN_LABS_API_KEY to a key with ElevenAgents read+write.")

TEMPORAL_TARGET = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
TASK_QUEUE = "pirate-riddle-task-queue"

# Overwritten with the live workflow id at the start of every kid's session,
# so `just kill` (see justfile) can force-terminate the current game from a
# second terminal without copy-pasting a uuid out of scrollback.
CURRENT_WORKFLOW_FILE = Path(__file__).with_name("current_workflow.txt")

RECORDINGS_DIR = Path(__file__).with_name("recordings")

# Fallback only: on "correct"/"out_of_guesses" the agent now hangs up itself
# via the end_call tool (see module docstring point 5), so this grace period
# normally never gets reached — watcher.cancel() in run_kid_session's finally
# block fires first. It still matters for "timed_out"/"abandoned", where the
# agent has no reason to call end_call, and as a backstop if it ever forgets
# to. Confirmed against real workflow history: WorkflowExecutionCompleted
# lands in the same instant as the deciding guess's Update, before the agent
# has necessarily said a word about it. Not used for an abnormal end (`just
# kill`, cancel, a real failure) — that's meant to be immediate.
WORKFLOW_END_GRACE_SECONDS = 8.0

FIRST_MESSAGE = (
    "[chuckles] Well, well... another landlubber washes up on me shore. "
    "I be Captain Barnaby Bones! What be yer name, little matey?"
)


# --- Recording mic input + agent output to local WAV files -----------------
#
# DefaultAudioInterface already receives every raw PCM chunk going in each
# direction (16-bit mono, 16kHz — see its INPUT/OUTPUT constants); this just
# tees each chunk to a WAV file before handing it on, so no extra network
# calls or re-encoding. Two mono files rather than one stereo mix, since mic
# and agent audio arrive on independent threads with no shared clock to
# interleave them against — ffmpeg can merge them afterward if a single file
# is wanted (see README.md).


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
        return super()._in_callback(in_data, frame_count, time_info, status)

    def output(self, audio: bytes) -> None:
        self._agent_wav.writeframes(audio)
        super().output(audio)

    def stop(self) -> None:
        super().stop()
        self._mic_wav.close()
        self._agent_wav.close()


# --- Bridging sync ElevenLabs callbacks to the async Temporal client -------
#
# Conversation (from the elevenlabs SDK) runs its own event loop internally
# and calls client tools synchronously from its own thread (see the "don't
# wrap its lifecycle in asyncio.run" gotcha in the top-level CLAUDE.md). The
# Temporal client is asyncio-native. So this script runs ONE dedicated
# background event loop for all Temporal calls, and bridges into it with
# asyncio.run_coroutine_threadsafe() wherever a sync callback needs an
# answer from the workflow.


class TemporalBridge:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def run(self, coro, timeout: float = 10.0):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def run_background(self, coro) -> concurrent.futures.Future:
        """Schedule a coroutine without waiting for it. The returned future
        can be cancelled from any thread (see watch_for_workflow_end)."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def stop(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)


async def watch_for_workflow_end(
    handle: WorkflowHandle, conversation: Conversation
) -> None:
    """Ends the ElevenLabs session once the workflow is done, so this
    process exits on its own instead of sitting there waiting for a Ctrl-C
    the operator has no more reason to give.

    This is a fallback, not the primary mechanism: on a correct guess or
    out_of_guesses, the agent now hangs up itself via its end_call tool
    right after speaking the reveal (see module docstring point 5), which
    closes the websocket and makes wait_for_session_end() return on its
    own — at which point run_kid_session's finally block cancels this
    watcher before the sleep below ever matters. This coroutine mainly
    exists for "timed_out" (kid walked away) and "abandoned" (operator's
    Ctrl-C), where the agent has no reason to call end_call, and as a
    backstop if it ever forgets to.

    `just kill` (or anything else that ends the workflow abnormally —
    terminate, cancel, a genuine failure) hangs up right away. A clean
    finish resolves handle.result() normally with no exception — those get
    a grace period first (WORKFLOW_END_GRACE_SECONDS) in case the agent is
    still mid-sentence, since the workflow completes the instant the
    deciding guess lands, not after the agent has said anything about it.
    """
    try:
        await handle.result()
    except Exception as e:
        print(
            f"  [temporal] workflow ended abnormally ({e!r}) — ending ElevenLabs session"
        )
    else:
        print(
            f"  [temporal] workflow finished — ending ElevenLabs session in "
            f"{WORKFLOW_END_GRACE_SECONDS:.0f}s"
        )
        await asyncio.sleep(WORKFLOW_END_GRACE_SECONDS)
    try:
        conversation.end_session()
    except Exception:
        pass


def start_game(bridge: TemporalBridge) -> tuple[WorkflowHandle, RiddleDef]:
    client = bridge.run(Client.connect(TEMPORAL_TARGET))
    workflow_id = f"riddle-game-{uuid.uuid4()}"
    handle = bridge.run(
        client.start_workflow(
            RiddleGameWorkflow.run,
            RIDDLE_POOL,
            id=workflow_id,
            task_queue=TASK_QUEUE,
        )
    )
    print(f"  [temporal] started workflow {workflow_id!r}")
    CURRENT_WORKFLOW_FILE.write_text(workflow_id)

    # The riddle is picked inside the workflow's first task, not by this
    # script — poll briefly until it's visible via query.
    riddle = None
    for _ in range(50):
        riddle = bridge.run(handle.query(RiddleGameWorkflow.get_riddle))
        if riddle is not None:
            break
        time.sleep(0.1)
    if riddle is None:
        sys.exit("Workflow never picked a riddle — is the worker running?")
    return handle, riddle


def build_config(riddle: RiddleDef) -> ConversationInitiationData:
    prompt = Path(__file__).with_name("pirate_riddle_prompt_temporal.txt").read_text()
    return ConversationInitiationData(
        dynamic_variables={"riddle": riddle.riddle, "answer": riddle.answer},
        conversation_config_override={
            "agent": {
                "prompt": {"prompt": prompt},
                "first_message": FIRST_MESSAGE,
            },
            "asr": {"keywords": all_answer_words()},
        },
    )


def make_client_tools(bridge: TemporalBridge, handle: WorkflowHandle):
    from elevenlabs.conversational_ai.conversation import ClientTools

    tools = ClientTools()

    def check_guess(parameters: dict) -> str:
        """Called by the agent every turn. MUST return a string — the
        orchestrator's websocket validator rejects non-string client tool
        results with a 1008 policy violation, which kills the session."""
        guess = parameters.get("guess", "")
        try:
            result = bridge.run(
                handle.execute_update(RiddleGameWorkflow.submit_guess, guess)
            )
        except Exception as e:
            # The validator rejects guesses once the game is already over
            # (correct / out_of_guesses) — treat any rejection as "nothing
            # more to do here" rather than crashing the session.
            print(f"  [check_guess] update rejected: {e}")
            return "the game's already over — reveal the answer and move on."

        print(
            f"  [check_guess] {guess!r} -> {result.outcome} "
            f"({result.guesses_used}/5 guesses used)"
        )

        if result.outcome == "correct":
            return "correct — reveal the answer now and celebrate!"
        if result.outcome == "out_of_guesses":
            return (
                "out_of_guesses — gently reveal the answer and send them to the chest."
            )
        return f"incorrect — {result.guesses_remaining} guesses left, give the clue for this turn."

    tools.register("check_guess", check_guess)
    return tools


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record",
        action="store_true",
        help="Record this session's mic input and agent output to recordings/ (off by default)",
    )
    return parser.parse_args()


def run_kid_session(
    bridge: TemporalBridge,
    handle: WorkflowHandle,
    riddle: RiddleDef,
    record: bool = False,
) -> None:

    mic_path = ""
    agent_path = ""

    if record:
        RECORDINGS_DIR.mkdir(exist_ok=True)
        mic_path = RECORDINGS_DIR / f"{handle.id}_mic.wav"
        agent_path = RECORDINGS_DIR / f"{handle.id}_agent.wav"
        audio_interface = RecordingAudioInterface(mic_path, agent_path)
    else:
        audio_interface = DefaultAudioInterface()

    eleven_labs_client = ElevenLabs(api_key=API_KEY)
    conversation = Conversation(
        eleven_labs_client,
        AGENT_ID,
        requires_auth=True,
        audio_interface=audio_interface,
        config=build_config(riddle),
        client_tools=make_client_tools(bridge, handle),
        callback_agent_response=lambda resp: print(f"☠ Captain: {resp}"),
        callback_user_transcript=lambda text: print(f"🧒 Kid: {text}"),
    )
    conversation.start_session()
    watcher = bridge.run_background(watch_for_workflow_end(handle, conversation))
    try:
        conversation.wait_for_session_end()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        watcher.cancel()  # workflow is still ours to finish normally from here on
        conversation.end_session()  # blocks until audio_interface.stop() finishes (closes WAV files if recording)
        if record:
            print(f"  [recording] mic:   {mic_path}")
            print(f"  [recording] agent: {agent_path}")
        try:
            bridge.run(handle.signal(RiddleGameWorkflow.end_session))
        except Exception:
            pass  # workflow may have already finished on its own

        try:
            summary = bridge.run(handle.result())
            print(
                f"  [temporal] workflow finished: outcome={summary.outcome!r} "
                f"guesses={summary.guesses}"
            )
        except Exception as e:
            print(f"  [temporal] couldn't fetch final result: {e}")


if __name__ == "__main__":
    args = parse_args()
    bridge = TemporalBridge()
    handle, riddle = start_game(bridge)
    print(f"🗡  This kid's riddle (difficulty {riddle.difficulty}/5): {riddle.riddle}")
    print(f"    Answer (ssh, don't tell): {riddle.answer}")
    if args.record:
        print("    Recording this session to recordings/.")
    print("    Talk to the Captain! Ctrl-C when the kid walks off.\n")
    try:
        run_kid_session(bridge, handle, riddle, record=args.record)
    finally:
        bridge.stop()
