"""
Sketch of the Speech Engine "brain" side. This replaces the hosted
ElevenLabs agent + system prompt entirely — ElevenLabs now does ASR/TTS
only, and every line the pirate speaks comes verbatim from the Temporal
workflow's `submit_utterance` update.

This is deliberately a sketch, not copy-paste-runnable: the exact
on_transcript / session wiring depends on which Speech Engine transport
you use (their Python `engine.serve()` standalone server, or
`engine.create_session()` inside your own FastAPI/Starlette app). Check
https://elevenlabs.io/docs/eleven-api/guides/cookbooks/speech-engine for
the current transport-level API and slot this logic into their
on_transcript callback — the Temporal-facing half below is the part that's
solid.
"""

import asyncio
from temporalio.client import Client

from temporal_workflows import PirateConversation

TASK_QUEUE = "pirate-task-queue"

_temporal_client: Client | None = None


async def get_temporal_client() -> Client:
    global _temporal_client
    if _temporal_client is None:
        _temporal_client = await Client.connect("localhost:7233")
    return _temporal_client


async def on_session_start(session_id: str) -> str:
    """
    Call this once when a new ElevenLabs Speech Engine session opens
    (i.e. a new kid steps up and the push-to-talk kiosk starts a session).
    Starts exactly one workflow per conversation, keyed by session_id.
    """
    client = await get_temporal_client()
    await client.start_workflow(
        PirateConversation.run,
        id=f"pirate-{session_id}",
        task_queue=TASK_QUEUE,
    )
    return "Well, well. Another landlubber washes up on my shore."


async def on_transcript(session_id: str, transcript: str) -> str:
    """
    Call this every time Speech Engine hands you a finished user
    transcript. Returns the exact text to hand to TTS — no LLM call, no
    judgment call, just the workflow's next line.
    """
    client = await get_temporal_client()
    handle = client.get_workflow_handle(f"pirate-{session_id}")
    result = await handle.execute_update(
        PirateConversation.submit_utterance, transcript
    )
    return result["line"]


# --- Minimal manual smoke test (no ElevenLabs involved) --------------------
async def _smoke_test():
    session_id = "test-session-1"
    print(await on_session_start(session_id))
    for i in range(5):
        line = await on_transcript(session_id, f"kid says something turn {i}")
        print(f"turn {i+1}: {line}")


if __name__ == "__main__":
    asyncio.run(_smoke_test())
