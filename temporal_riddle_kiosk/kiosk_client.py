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
  4. On Ctrl-C (or the agent revealing the answer), signal end_session so
     the workflow finishes promptly instead of idling out its timeout.

Prerequisites (see README.md):
  - `temporal server start-dev` running
  - `python worker.py` running
  - ELEVEN_LABS_API_KEY set

Run:  .venv/bin/python kiosk_client.py
Stop: Ctrl-C ends the session (next kid = run it again).
"""

import asyncio
import os
import sys
import threading
import time
import uuid
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

FIRST_MESSAGE = (
    "[chuckles] Well, well... another landlubber washes up on me shore. "
    "I be Captain Barnaby Bones! What be yer name, little matey?"
)


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

    def stop(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)


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


def run_kid_session(
    bridge: TemporalBridge, handle: WorkflowHandle, riddle: RiddleDef
) -> None:
    client = ElevenLabs(api_key=API_KEY)
    conversation = Conversation(
        client,
        AGENT_ID,
        requires_auth=True,
        audio_interface=DefaultAudioInterface(),
        config=build_config(riddle),
        client_tools=make_client_tools(bridge, handle),
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
    bridge = TemporalBridge()
    handle, riddle = start_game(bridge)
    print(f"🗡  This kid's riddle (difficulty {riddle.difficulty}/5): {riddle.riddle}")
    print(f"    Answer (ssh, don't tell): {riddle.answer}")
    print("    Talk to the Captain! Ctrl-C when the kid walks off.\n")
    try:
        run_kid_session(bridge, handle, riddle)
    finally:
        bridge.stop()
