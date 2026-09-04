"""
Run this once, keep it alive for the night alongside your brain server.

For a Halloween prop, run Temporal itself locally rather than depending on
Temporal Cloud + home internet for something this latency- and reliability-
sensitive:

    temporal server start-dev

(installs via `brew install temporal` or see temporal.io/setup/install-temporal-cli)
That gives you localhost:7233 plus a web UI at localhost:8233 for watching
workflow state live during testing — handy for debugging clue progression.
"""

import asyncio
from temporalio.client import Client
from temporalio.worker import Worker

from pirate_activities import generate_pirate_line
from temporal_workflows import PirateConversation

TASK_QUEUE = "pirate-task-queue"


async def main():
    client = await Client.connect("localhost:7233")
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[PirateConversation],
        # The LLM wording call — every other piece of game state stays
        # deterministic workflow logic. The workflow leak-checks and
        # falls back to static templates if this is slow or untrustworthy.
        activities=[generate_pirate_line],
    )
    print(f"Worker running, task queue: {TASK_QUEUE}")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
