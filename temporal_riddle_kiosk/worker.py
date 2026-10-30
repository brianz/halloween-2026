"""
Worker process: polls the task queue, runs RiddleGameWorkflow + record_guess.

Run against a local dev server:
    temporal server start-dev
    .venv/bin/python worker.py
"""

import asyncio
import concurrent.futures

from activities import record_guess
from temporalio.client import Client
from temporalio.worker import Worker
from workflows import RiddleGameWorkflow

TASK_QUEUE = "pirate-riddle-task-queue"


async def main() -> None:
    client = await Client.connect("localhost:7233")
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as activity_executor:
        worker = Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=[RiddleGameWorkflow],
            activities=[record_guess],
            activity_executor=activity_executor,
        )
        print(f"Worker polling task queue {TASK_QUEUE!r}. Ctrl-C to stop.")
        await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
