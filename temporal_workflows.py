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
        CORRECT_GUESS_INSTRUCTION,
        GREETING_INSTRUCTION,
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


def _guess_correct(transcript: str, password: str) -> bool:
    """True if the child's utterance contains the password as a run of
    whole words (word-tokenized, not substring) — so a password like "Map"
    doesn't false-positive on "I mapped it out"."""

    def words(s: str) -> list[str]:
        return re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()

    password_words = words(password)
    transcript_words = words(transcript)
    if not password_words:
        return False
    n = len(password_words)
    return any(
        transcript_words[i : i + n] == password_words
        for i in range(len(transcript_words) - n + 1)
    )


_NAME_LEADIN_RE = re.compile(
    r"^(?:my name(?:'s| is)?|i am|i'm|it'?s|this is|call me)\s+", re.IGNORECASE
)
_NAME_STOPWORDS = {"no", "nope", "uh", "um", "dunno", "nothing", "skip", "none", "idk"}


def _extract_name(transcript: str) -> str | None:
    """Best-effort pull of a spoken name out of the reply to 'what's your
    name?'. Deterministic (workflow-safe, pure string ops): strips a common
    lead-in phrase, then takes the first remaining word. Good enough for a
    kiosk game — if the kid didn't give a clean name, we just skip
    personalization rather than guess wrong."""
    cleaned = transcript.strip().strip(".!?").strip()
    cleaned = _NAME_LEADIN_RE.sub("", cleaned, count=1).strip()
    if not cleaned:
        return None
    first_word = cleaned.split()[0].strip(",.!?").lower()
    if not first_word.isalpha() or len(first_word) < 2 or first_word in _NAME_STOPWORDS:
        return None
    return first_word.capitalize()


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
        # Optional personalization; set via signal if captured upstream,
        # or extracted from the child's reply to the greeting's name-ask.
        self._child_name: str | None = None
        # True right after greet() runs, until the child's next utterance
        # has been consumed as a name-capture attempt (not a guess/clue turn).
        self._awaiting_name = False

    def _ensure_password(self) -> str:
        """Pick the password once, lazily, and persist it to self._password
        as a side effect. An update (or now, greet()) can arrive before
        run()'s first line executes, so every entry point calls this; the
        None check keeps workflow.random() called at most once per run, so
        replays re-derive the same choice. Must assign to self._password
        here (not just return it) — callers besides run() discard the
        return value and rely solely on the side effect."""
        if self._password is None:
            self._password = workflow.random().choice(PASSWORD_POOL)
        return self._password

    @workflow.run
    async def run(self) -> str:
        self._ensure_password()
        await workflow.wait_condition(lambda: self._done)
        return self._password

    @workflow.signal
    def set_child_name(self, name: str) -> None:
        self._child_name = name

    def _fallback_line(self, reveal: bool, guessed: bool = False) -> str:
        """Static-template line — the deterministic safety net for every
        LLM failure mode (leak, timeout, exception, empty output)."""
        if reveal and guessed:
            return f"Ye got it, ye clever buccaneer! The password be... {self._password}!"
        if reveal:
            return f"Ye've earned it! The password be... {self._password}!"
        clue_index = min(self._turn - 1, len(CLUE_TEMPLATES) - 1)
        return CLUE_TEMPLATES[clue_index].format(
            first_letter=self._password[0],
            num_words=len(self._password.split()),
        )

    def _fallback_greeting(self) -> str:
        return "Well, well. Another landlubber washes up on my shore. What be yer name, matey?"

    async def _call_activity(
        self,
        level_key: str,
        instruction: str,
        facts: list[str],
        transcript: str,
        *,
        leak_check: bool,
    ) -> str | None:
        """
        Shared Activity-call plumbing: build the ClueRequest, call the LLM
        Activity under the fixed timeout, and (unless this is a turn where
        saying the password is the whole point) leak-check the result.
        Returns None on any failure — timeout, exception, empty output, or
        a leak — so callers fall back to a static line. Never raises.
        """
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
                "generate_pirate_line activity failed on turn %d (%s), using fallback",
                self._turn,
                level_key,
            )
            return None

        line = (line or "").strip()
        if not line:
            return None
        if leak_check and _password_leaked(line, self._password):
            workflow.logger.warning(
                "LLM leaked the password on turn %d, using fallback", self._turn
            )
            return None
        return line

    async def _generated_greeting(self) -> str | None:
        level_key, instruction, facts = GREETING_INSTRUCTION
        return await self._call_activity(level_key, instruction, facts, "", leak_check=True)

    async def _generated_line(self, reveal: bool, guessed: bool, transcript: str) -> str | None:
        """
        Build this turn's deterministic clue budget, hand it to the LLM
        Activity, and return its line — or None if the Activity failed,
        timed out, or leaked the password. Never raises: every failure
        path funnels to the static fallback.
        """
        # The clue budget: keyed by turn number, decided here, not by the LLM.
        if reveal and guessed:
            level_key, instruction, facts = CORRECT_GUESS_INSTRUCTION
        elif reveal:
            level_key, instruction, facts = "reveal", CLUE_LEVEL_INSTRUCTIONS[-1][1], []
        else:
            level_key, instruction, facts = CLUE_LEVEL_INSTRUCTIONS[
                min(self._turn - 1, len(CLUE_LEVEL_INSTRUCTIONS) - 2)
            ]
        return await self._call_activity(
            level_key, instruction, facts, transcript, leak_check=not reveal
        )

    @workflow.update
    async def greet(self) -> dict:
        """
        Called once, right when a new kid's session starts — before any
        submit_utterance call. Generates a dynamic greeting that asks the
        child's name. Not part of the clue-turn budget: the child's reply
        is consumed by submit_utterance's name-capture step, not counted
        as a guess or a clue turn.
        """
        self._ensure_password()
        self._awaiting_name = True
        line = await self._generated_greeting()
        if line is None:
            line = self._fallback_greeting()
        return {"line": line, "turn": 0, "done": False}

    @workflow.update
    async def submit_utterance(self, transcript: str) -> dict:
        """
        Called by the brain server once per user turn. Returns exactly what
        the pirate should say next — the brain server just relays this
        straight to TTS.

        The workflow alone decides what's allowed this turn (clue budget,
        reveal or not, or an early reveal because the child guessed
        correctly). The Activity only turns that structured budget into
        spoken words; its output is leak-checked and discarded in favor of
        a static template if it can't be trusted or was too slow.
        """
        self._ensure_password()

        if self._awaiting_name:
            self._awaiting_name = False
            name = _extract_name(transcript)
            if name:
                self._child_name = name

        self._turn += 1
        guessed = _guess_correct(transcript, self._password)
        reveal = guessed or self._turn >= self._max_turns

        line = await self._generated_line(reveal, guessed, transcript)
        if line is None:
            line = self._fallback_line(reveal, guessed)

        self._history.append((transcript, line))

        if reveal:
            self._done = True
        return {"line": line, "done": self._done, "turn": self._turn, "guessed": guessed}

    @workflow.query
    def status(self) -> dict:
        """Read-only peek at current state, e.g. for a dashboard/debug tool."""
        return {"turn": self._turn, "done": self._done, "child_name": self._child_name}
