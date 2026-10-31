"""
Shared data shapes and pure logic for the Temporal riddle game.

This file is imported by BOTH the workflow (through the sandbox's
imports_passed_through()) and the kiosk client, so it must stay free of any
I/O or non-deterministic calls — plain dataclasses and pure functions only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_GUESSES = 3

RIDDLE_POOL: list[RiddleDef] = []  # populated below, after RiddleDef exists


@dataclass
class RiddleDef:
    riddle: str
    answer: str
    difficulty: int  # 1 (easiest) .. 5 (hardest)


@dataclass
class GuessResult:
    """Returned synchronously to the kiosk by the submit_guess Update."""

    correct: bool
    guesses_used: int
    guesses_remaining: int
    outcome: str  # "playing" | "correct" | "out_of_guesses"


@dataclass
class GameSummary:
    """The workflow's final return value — visible via `temporal workflow show`."""

    riddle: str
    answer: str
    difficulty: int
    outcome: str  # "correct" | "out_of_guesses" | "abandoned" | "timed_out"
    guesses: list[str] = field(default_factory=list)


# Progressively harder from here down. Difficulty 1 is the one kept from the
# original single-tier pool (a plain, concrete object named outright by its
# clues). Each tier up trades a little more concreteness for pirate lore,
# idiom, and — from tier 2 on — a multi-word answer.
RIDDLE_POOL.extend(
    [
        RiddleDef(
            riddle=(
                "I sit upon a pirate's shoulder and squawk words I don't "
                "understand. My feathers shine as bright as treasure. "
                "What bird am I?"
            ),
            answer="Parrot",
            difficulty=1,
        ),
        RiddleDef(
            riddle=(
                "I'm made of old wood with a big brass lock. Fill me with "
                "gold and jewels and I'll make any pirate smile. What am I?"
            ),
            answer="Treasure Chest",
            difficulty=2,
        ),
        RiddleDef(
            riddle=(
                "I fly high above a ship, stitched from black cloth, with "
                "a skull and crossed bones for my face. Sailors fear me "
                "long before they ever see the ship below. What am I?"
            ),
            answer="Jolly Roger",
            difficulty=3,
        ),
        RiddleDef(
            riddle=(
                "I carry words across the waves, sealed up tight and "
                "corked with care. A sailor tosses me overboard, hoping "
                "someone, someday, finds what's inside. What am I?"
            ),
            answer="Message in a Bottle",
            difficulty=4,
        ),
        RiddleDef(
            riddle=(
                "I'm not a chest you can open, and no key fits my lock. "
                "Old sailors say it's where a ship — and sometimes a "
                "sailor — ends up once it sinks to the bottom of the sea. "
                "What am I?"
            ),
            answer="Davy Jones' Locker",
            difficulty=5,
        ),
    ]
)


def guess_matches(guess: str, answer: str) -> bool:
    """Whole-word match: 'Map' doesn't false-positive on 'I mapped it out'.

    Pure and deterministic — safe to call directly from workflow code,
    no activity needed.
    """

    def words(s: str) -> list[str]:
        return re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()

    a_words = words(answer)
    g_words = words(guess)
    if not a_words:
        return False
    n = len(a_words)
    return any(g_words[i : i + n] == a_words for i in range(len(g_words) - n + 1))


def all_answer_words(pool: list[RiddleDef] = RIDDLE_POOL) -> list[str]:
    """Every riddle's answer words, for ASR keyword boosting without
    tipping off which riddle is live (same trick as pirate_riddle_kiosk.py)."""
    return [word for r in pool for word in r.answer.split()]
