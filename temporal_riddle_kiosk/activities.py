"""
The one piece of real I/O in this exercise. Everything else in the game
(matching a guess, counting attempts, deciding the outcome) is pure and
deterministic and lives directly in the workflow — it doesn't need an
activity. Writing a line to disk does, because it's I/O that can fail
independently of the game logic, and Temporal will retry it for us.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from temporalio import activity

LOG_PATH = Path(__file__).with_name("guess_log.jsonl")


@activity.defn
def record_guess(answer: str, guess: str, correct: bool, difficulty: int) -> None:
    line = {
        "at": datetime.now(UTC).isoformat(),
        "answer": answer,
        "difficulty": difficulty,
        "guess": guess,
        "correct": correct,
    }
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(line) + "\n")
