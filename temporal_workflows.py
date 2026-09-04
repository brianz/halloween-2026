"""
One PirateConversation workflow execution = one kid's conversation with the
Captain. Workflow ID should be the ElevenLabs conversation/session ID, so
there's exactly one workflow per session and it's trivially resumable.

Determinism notes (this is the actual point of using Temporal here):
- Password is chosen with workflow.random(), NOT the stdlib `random` module.
  workflow.random() is seeded deterministically per workflow run and is
  replay-safe — if the worker crashes and replays history, it picks the
  SAME password again instead of a new random one. Plain `random.choice()`
  in workflow code would violate determinism and Temporal's sandbox will
  flag it.
- All state (password, turn, done) lives on `self` inside the workflow
  instance, persisted by Temporal automatically. No external dict/Redis
  needed for this part.
"""

import re
from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from pirate_activities import (
        CLUE_LEVEL_INSTRUCTIONS,
        ClueRequest,
        generate_pirate_line,
    )

PASSWORD_POOL = [
    "Treasure",
    "Parrot",
    "Ship",
    "Gold",
    "Anchor",
    "Map",
    "Compass",
    "Island",
    "Hook",
    "Cannon",
]

# Index 0 = first clue (vaguest), later entries = more obvious.
CLUE_TEMPLATES = [
    "Me treasure's password be hidden in a riddle only a true pirate can crack.",
    "It's got somethin' to do with the sea, matey. Think salty thoughts.",
    "I'll give ye a hint — it starts with the letter '{first_letter}'.",
    "Alright, alright, one more nudge... it's {num_words} words long.",
    "Ye persistent barnacle. Fine — I'll just tell ye.",
]


def _password_leaked(line: str, password: str) -> bool:
    """
    Safety net: True if the generated line gives away the password.
    Kids (and LLMs) try the obvious tricks — plain substring is the main
    one, but also the password read backwards, or spelled out letter by
    letter ("K r a k e n", "K-r-a-k-e-n", "K. r. a..."). The spelled-out
    check requires at least one non-letter between letters, so a word
    merely appearing normally in a sentence can't false-positive — and
    a false positive here only costs us the LLM line, never the game.
    """
    lowered = " ".join(line.lower().split())  # collapse whitespace runs
    pw = password.lower()
    if pw in lowered or pw[::-1] in lowered:
        return True
    targets = [pw] + pw.split()  # whole password, or any single word of it
    for target in targets:
        letters = [c for c in target.lower() if c.isalpha()]
        # Check the full spelling and any prefix of >= 4 letters — a line
        # that spells out "K r a k e n" leaks "Kraken's" just as surely as
        # the full word. Normal prose never has letters separated by
        # non-letters, so these can't false-positive on honest clues.
        for length in range(len(letters), 3, -1):
            pattern = r"[^a-z]+".join(re.escape(c) for c in letters[:length])
            if re.search(pattern, lowered):
                return True
    return False


@workflow.defn
class PirateConversation:
    def __init__(self) -> None:
        self._password: str | None = None
        self._turn = 0
        self._max_turns = 5
        self._done = False
        # Full conversation history, kept in workflow state so the LLM
        # Activity can see what's already been said (no self-repetition,
        # callbacks to earlier turns). This is state, not control flow —
        # the workflow still decides everything deterministically.
        self._history: list[tuple[str, str]] = []
        # Optional personalization; set via signal if captured upstream.
        self._child_name: str | None = None

    def _ensure_password(self) -> str:
        """Pick the password once, lazily. An update can arrive before
        run()'s first line executes, so both paths call this; the None
        check keeps workflow.random() called at most once per run, so
        replays re-derive the same choice."""
        if self._password is None:
            return workflow.random().choice(PASSWORD_POOL)
        return self._password

    @workflow.run
    async def run(self) -> str:
        self._password = self._ensure_password()
        await workflow.wait_condition(lambda: self._done)
        return self._password

    @workflow.signal
    def set_child_name(self, name: str) -> None:
        self._child_name = name

    def _fallback_line(self, reveal: bool) -> str:
        """Static-template line — the deterministic safety net for every
        LLM failure mode (leak, timeout, exception, empty output)."""
        if reveal:
            return f"Ye've earned it! The password be... {self._password}!"
        clue_index = min(self._turn - 1, len(CLUE_TEMPLATES) - 1)
        return CLUE_TEMPLATES[clue_index].format(
            first_letter=self._password[0],
            num_words=len(self._password.split()),
        )

    async def _generated_line(self, reveal: bool, transcript: str) -> str | None:
        """
        Build this turn's deterministic clue budget, hand it to the LLM
        Activity, and return its line — or None if the Activity failed,
        timed out, or leaked the password. Never raises: every failure
        path funnels to the static fallback.
        """
        # The clue budget: keyed by turn number, decided here, not by the LLM.
        if reveal:
            level_key, instruction, facts = "reveal", CLUE_LEVEL_INSTRUCTIONS[-1][1], []
        else:
            level_key, instruction, facts = CLUE_LEVEL_INSTRUCTIONS[
                min(self._turn - 1, len(CLUE_LEVEL_INSTRUCTIONS) - 2)
            ]
        fact_strings = [
            f.format(
                first_letter=self._password[0],
                num_words=len(self._password.split()),
            )
            for f in facts
        ]

        try:
            line = await workflow.start_activity(
                generate_pirate_line,
                ClueRequest(
                    turn=self._turn,
                    clue_level=level_key,
                    instruction=instruction,
                    allowed_facts=fact_strings,
                    password=self._password,
                    child_utterance=transcript,
                    history=list(self._history),  # copy for this turn's call
                    child_name=self._child_name,
                ),
                schedule_to_close_timeout=timedelta(seconds=4),
            )
        except Exception:  # timeout, provider error, anything — fall back
            workflow.logger.warning(
                "generate_pirate_line activity failed on turn %d, using fallback",
                self._turn,
            )
            return None

        line = (line or "").strip()
        if not line:
            return None
        if not reveal and _password_leaked(line, self._password):
            workflow.logger.warning(
                "LLM leaked the password on turn %d, using fallback", self._turn
            )
            return None
        return line

    @workflow.update
    async def submit_utterance(self, transcript: str) -> dict:
        """
        Called by the brain server once per user turn. Returns exactly what
        the pirate should say next — the brain server just relays this
        straight to TTS.

        The workflow alone decides what's allowed this turn (clue budget,
        reveal or not). The Activity only turns that structured budget
        into spoken words; its output is leak-checked and discarded in
        favor of a static template if it can't be trusted or was too slow.
        """
        self._ensure_password()
        self._turn += 1
        reveal = self._turn >= self._max_turns

        line = await self._generated_line(reveal, transcript)
        if line is None:
            line = self._fallback_line(reveal)

        self._history.append((transcript, line))

        if reveal:
            self._done = True
        return {"line": line, "done": self._done, "turn": self._turn}

    @workflow.query
    def status(self) -> dict:
        """Read-only peek at current state, e.g. for a dashboard/debug tool."""
        return {"turn": self._turn, "done": self._done, "child_name": self._child_name}
