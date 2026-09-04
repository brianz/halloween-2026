"""
Unit tests for the PirateConversation workflow's LLM-clue integration,
run against temporalio's in-memory test environment with the
generate_pirate_line Activity replaced by a mock (never a real LLM call).

Covers the two mandated failure paths plus happy paths:
- Activity returns a line containing the password mid-game -> static
  fallback template is used instead, and play continues.
- Activity hangs past its timeout -> fallback used, turn completes in a
  few seconds, and the whole 5-turn game still finishes.
- Normal LLM lines pass through unchanged.
- Reveal turn: password allowed, appears in the line, game ends.
"""

import asyncio
import time

import pytest
from temporalio import activity
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from temporal_workflows import CLUE_TEMPLATES, PASSWORD_POOL, PirateConversation
from pirate_activities import ClueRequest


def _mock(behavior):
    """Wrap a plain async fn as a Temporal activity that replaces
    generate_pirate_line (same registered name so the workflow's call
    routes here instead of to a real LLM)."""

    async def fake(req: ClueRequest) -> str:
        return await behavior(req)

    fake.__name__ = "generate_pirate_line"
    return activity.defn(name="generate_pirate_line")(fake)


async def _run_game(env: WorkflowEnvironment, mock_activity, utterances):
    """Run a full submit_utterance conversation with the given mock
    activity. Returns (per-turn results, worker task)."""
    client: Client = env.client
    handle = await client.start_workflow(
        PirateConversation.run,
        id="test-pirate-conversation",
        task_queue="test-queue",
    )
    async with Worker(
        client,
        task_queue="test-queue",
        workflows=[PirateConversation],
        activities=[mock_activity],
    ):
        results = []
        for utterance in utterances:
            results.append(
                await handle.execute_update(PirateConversation.submit_utterance, utterance)
            )
        return results



@pytest.mark.asyncio
async def test_happy_path_uses_llm_lines_and_never_leaks():
    """Normal Activity output passes through; across all 4 clue turns the
    password (case-insensitive) never appears in any line."""

    async def mock(req: ClueRequest) -> str:
        if req.clue_level == "reveal":
            return f"YE'VE WON! The password be {req.password}! Claim yer candy!"
        return f"[Chuckles] A fine guess, but me lips be sealed. ({req.clue_level} turn {req.turn})"

    utterances = [
        "hello captain",
        "is it gold?",
        "does it start with K?",
        "give me a hint",
        "okay I give up",
    ]
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        results = await _run_game(env, _mock(mock), utterances)
        password = None
        # Get the password from the reveal turn's own line (mock echoes it).
        assert results[-1]["done"] is True
        # On clue turns, the LLM line must be passed through verbatim...
        for i, r in enumerate(results[:-1]):
            assert "clue_level" in r["line"] or "me lips be sealed" in r["line"]
            assert r["turn"] == i + 1
            assert r["done"] is False
        # ...and no clue-turn line contains any password from the pool
        # (covers whichever one the deterministic picker chose).
        for r in results[:-1]:
            for pw in PASSWORD_POOL:
                assert pw.lower() not in r["line"].lower()
        # Reveal turn must contain the password.
        assert any(pw.lower() in results[-1]["line"].lower() for pw in PASSWORD_POOL)
    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_password_leak_in_activity_output_falls_back_to_template():
    """Activity returns a line containing the password mid-game -> the
    workflow must discard it and speak the static template instead."""

    async def mock(req: ClueRequest) -> str:
        if req.clue_level == "reveal":
            return f"The password be {req.password}!"
        # Naughty: blurts the password on a clue turn.
        return f"Arr, I'll just tell ye — it be {req.password}, matey!"

    env = await WorkflowEnvironment.start_time_skipping()
    try:
        results = await _run_game(
            env,
            _mock(mock),
            ["hi", "what is it", "tell me", "please?", "fine, reveal it"],
        )
        for i, r in enumerate(results[:-1]):
            # Fallback template used, not the leaked LLM line.
            assert "I'll just tell ye" not in r["line"]
            expected = CLUE_TEMPLATES[i].format(
                first_letter="X", num_words=0
            )  # can't know password; compare structurally below instead
        # Structural check: each clue turn's line equals one of the
        # formatted CLUE_TEMPLATES (with the real password's facts).
        # We recover the password via the reveal-turn LLM line.
        reveal_line = results[-1]["line"]
        password = next(
            pw for pw in PASSWORD_POOL if pw.lower() in reveal_line.lower()
        )
        for i, r in enumerate(results[:-1]):
            expected = CLUE_TEMPLATES[i].format(
                first_letter=password[0], num_words=len(password.split())
            )
            assert r["line"] == expected, f"turn {i+1} should use fallback template"
        # And crucially: no clue-turn line contains the password.
        for r in results[:-1]:
            assert password.lower() not in r["line"].lower()
    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_activity_timeout_falls_back_and_completes_quickly():
    """Activity sleeps past its 4s schedule_to_close timeout -> fallback
    template used, and each turn still completes within a few seconds
    (time-skipping env makes the timeout fire immediately on replay, but
    we still assert wall-clock bounds to prove nothing hangs)."""

    async def mock(req: ClueRequest) -> str:
        await asyncio.sleep(60)  # far past the 4s activity timeout
        return "never returned"

    env = await WorkflowEnvironment.start_time_skipping()
    try:
        utterances = ["hi", "what is it", "tell me", "please?", "reveal"]
        client: Client = env.client
        handle = await client.start_workflow(
            PirateConversation.run,
            id="test-pirate-timeout",
            task_queue="test-queue",
        )
        async with Worker(
            client,
            task_queue="test-queue",
            workflows=[PirateConversation],
            activities=[_mock(mock)],
        ):
            started = time.monotonic()
            results = []
            for utterance in utterances:
                results.append(
                    await handle.execute_update(
                        PirateConversation.submit_utterance, utterance
                    )
                )
            elapsed = time.monotonic() - started
        # All 5 turns completed.
        assert len(results) == 5
        assert results[-1]["done"] is True
        # Every clue turn used a fallback template (not "never returned").
        for r in results[:-1]:
            assert r["line"] != "never returned"
            assert "me lips be sealed" not in r["line"]
        # Nothing hung: the whole game is done in seconds, not minutes.
        assert elapsed < 30, f"game took {elapsed:.1f}s — timeout fallback too slow"
        # Reveal fallback line spoken too (activity never returned there either).
        assert "The password be" in results[-1]["line"]
    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_activity_exception_falls_back():
    """Provider raises -> static template, game continues."""

    async def mock(req: ClueRequest) -> str:
        raise RuntimeError("bedrock exploded")

    env = await WorkflowEnvironment.start_time_skipping()
    try:
        results = await _run_game(env, _mock(mock), ["hi", "what", "hint", "more", "reveal"])
        assert len(results) == 5
        assert results[-1]["done"] is True
        for r in results[:-1]:
            # Must be one of the formatted static templates.
            assert "riddle" in results[0]["line"] or True  # structural below
        reveal_line = results[-1]["line"]
        password = next(
            pw for pw in PASSWORD_POOL if pw.lower() in reveal_line.lower()
        )
        for i, r in enumerate(results[:-1]):
            expected = CLUE_TEMPLATES[i].format(
                first_letter=password[0], num_words=len(password.split())
            )
            assert r["line"] == expected
    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_history_and_child_name_reach_the_activity():
    """The Activity sees full prior history and the child's name when set."""

    seen_requests: list[ClueRequest] = []

    async def mock(req: ClueRequest) -> str:
        seen_requests.append(req)
        return f"[Chuckles] Turn {req.turn} of speaking, {req.child_name}."

    env = await WorkflowEnvironment.start_time_skipping()
    try:
        client: Client = env.client
        handle = await client.start_workflow(
            PirateConversation.run,
            id="test-pirate-history",
            task_queue="test-queue",
        )
        async with Worker(
            client,
            task_queue="test-queue",
            workflows=[PirateConversation],
            activities=[_mock(mock)],
        ):
            await handle.signal(PirateConversation.set_child_name, "Maya")
            # Signal delivery isn't ordered relative to updates — poll until
            # the workflow state shows it, so the first update reliably
            # carries the name.
            for _ in range(50):
                if (await handle.query(PirateConversation.status))["child_name"] == "Maya":
                    break
                await asyncio.sleep(0.05)
            r1 = await handle.execute_update(PirateConversation.submit_utterance, "ahoy")
            r2 = await handle.execute_update(
                PirateConversation.submit_utterance, "is it a parrot?"
            )
        # Both requests carried the name.
        assert all(req.child_name == "Maya" for req in seen_requests)
        # Second request saw the first turn's exchange in its history.
        assert seen_requests[1].history == [("ahoy", r1["line"])]
        # And the LLM line (which included the name) passed through.
        assert "Maya" in r2["line"]
    finally:
        await env.shutdown()


def test_password_leak_detection_variants():
    """Direct unit tests of the leak checker: substring, reversed,
    spelled-out, per-word spelling, and honest lines that pass."""
    from temporal_workflows import _password_leaked

    pw = "Kraken's Kiss"
    assert _password_leaked("it be the Kraken's Kiss, matey", pw)
    assert _password_leaked("ssik s'nekark reversed am I", pw)
    assert _password_leaked("K r a k e n 's Kiss ye seek", pw)
    assert _password_leaked("think K r a k e n and ye be close", pw)
    # Same word order with different casing/spacing still leaks.
    assert _password_leaked("the   kraken's   kiss awaits", pw)
    # Honest clue lines must NOT be flagged.
    assert not _password_leaked("it starts with the letter K", pw)
    assert not _password_leaked("it's two words long", pw)
    assert not _password_leaked("think salty sea thoughts", pw)
