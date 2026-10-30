"""
One kid's riddle game, as a Temporal workflow.

Each guess is a Workflow Update: a small, separately-recorded, synchronously-
answered step in the workflow's durable history. The 5-guess cap is enforced
by an Update validator (reject the 6th guess outright) instead of relying on
the LLM's own turn-counting. The riddle is chosen once, inside the workflow,
with workflow.random() — deterministic across replay, unlike random.choice()
in a plain script.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from activities import record_guess
    from models import MAX_GUESSES, GameSummary, GuessResult, RiddleDef, guess_matches

IDLE_TIMEOUT = timedelta(minutes=10)


@workflow.defn
class RiddleGameWorkflow:
    def __init__(self) -> None:
        self._riddle: RiddleDef | None = None
        self._guesses: list[str] = []
        self._outcome = "playing"
        self._ended_early = False

    @workflow.query
    def get_riddle(self) -> RiddleDef | None:
        """None until the first workflow task has run and picked one —
        the kiosk polls this briefly right after starting the workflow."""
        return self._riddle

    @workflow.query
    def get_state(self) -> dict:
        return {
            "outcome": self._outcome,
            "guesses_used": len(self._guesses),
            "guesses_remaining": max(0, MAX_GUESSES - len(self._guesses)),
        }

    @workflow.update
    async def submit_guess(self, guess: str) -> GuessResult:
        assert self._riddle is not None
        self._guesses.append(guess)
        correct = guess_matches(guess, self._riddle.answer)
        if correct:
            self._outcome = "correct"
        elif len(self._guesses) >= MAX_GUESSES:
            self._outcome = "out_of_guesses"

        # The only non-deterministic step: durably logging the attempt.
        await workflow.execute_activity(
            record_guess,
            args=[self._riddle.answer, guess, correct, self._riddle.difficulty],
            start_to_close_timeout=timedelta(seconds=10),
        )

        return GuessResult(
            correct=correct,
            guesses_used=len(self._guesses),
            guesses_remaining=max(0, MAX_GUESSES - len(self._guesses)),
            outcome=self._outcome,
        )

    @submit_guess.validator
    def validate_submit_guess(self, guess: str) -> None:
        if self._riddle is None:
            raise ValueError("no riddle chosen yet")
        if self._outcome != "playing":
            raise ValueError(f"game is already over: {self._outcome}")
        if not guess or not guess.strip():
            raise ValueError("guess cannot be empty")

    @workflow.signal
    async def end_session(self) -> None:
        """The kiosk calls this from its Ctrl-C handler so an abandoned
        game ends cleanly instead of idling out the full timeout."""
        self._ended_early = True

    @workflow.run
    async def run(self, pool: list[RiddleDef]) -> GameSummary:
        self._riddle = workflow.random().choice(pool)

        try:
            await workflow.wait_condition(
                lambda: self._outcome != "playing" or self._ended_early,
                timeout=IDLE_TIMEOUT,
            )
        except TimeoutError:
            self._outcome = "timed_out"

        if self._ended_early and self._outcome == "playing":
            self._outcome = "abandoned"

        # Let a guess that's mid-flight (its activity still running) finish
        # before the workflow completes out from under it.
        await workflow.wait_condition(workflow.all_handlers_finished)

        return GameSummary(
            riddle=self._riddle.riddle,
            answer=self._riddle.answer,
            difficulty=self._riddle.difficulty,
            outcome=self._outcome,
            guesses=self._guesses,
        )
