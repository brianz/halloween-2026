"""
Temporal Activities for the pirate conversation. Activities are the only
place non-deterministic work (network/LLM calls) is allowed; the workflow
calls these and owns all game state itself.

generate_pirate_line receives a fully-decided ClueRequest from the
workflow — the LLM has zero say in turn counts, clue progression, or
whether to reveal. It only wordsmiths.
"""

import re
from dataclasses import dataclass, field

from temporalio import activity

from llm_providers import get_provider

# Only these ElevenLabs audio tags are whitelisted in SYSTEM_PROMPT. An
# LLM-invented tag would be read aloud as words, so anything outside this
# set is stripped from every line before it leaves the Activity.
_AUDIO_TAG_RE = re.compile(r"\[([^\[\]]+)\]")


def _sanitize_audio_tags(line: str) -> str:
    """Normalize whitelisted ElevenLabs audio tags to their canonical
    lowercase form (v3 expects e.g. [laughs], not [Laughs]) and drop any
    other bracketed text — the LLM was told not to write any, but never
    trust LLM output: an unknown tag would be spoken aloud as words."""

    def _sub(m: re.Match) -> str:
        inner = m.group(1).lower()
        return f"[{inner}]" if inner in ALLOWED_AUDIO_TAGS else ""

    # Unknown brackets removed outright (not spaced out) so one inserted
    # mid-word can't split the password; whitespace collapse cleans the rest.
    return " ".join(_AUDIO_TAG_RE.sub(_sub, line).split())


ALLOWED_AUDIO_TAGS = frozenset(
    {
        "laughs",
        "chuckles",
        "whispers",
        "sighs",
        "excited",
        "curious",
        "mischievously",
        "triumphantly",
        "whistles",
        "shouts",
        "slow",
    }
)

# Human-readable instructions for each clue level. The workflow picks the
# index deterministically from the turn number; the LLM gets the *text*,
# plus the concrete facts it's allowed to use this turn.
CLUE_LEVEL_INSTRUCTIONS = [
    (
        "vague_riddle",
        "Give only a vague, riddling tease about the password. Do NOT "
        "mention the sea, letters, or word count yet.",
        [],  # no concrete facts allowed this level
    ),
    (
        "sea_theme",
        "Hint that the password has something to do with the sea. Do NOT "
        "mention letters or word count yet.",
        [],
    ),
    (
        "first_letter",
        "You may hint that the password starts with a specific letter. "
        "Say the letter itself is fine.",
        ["The password starts with the letter '{first_letter}'."],
    ),
    (
        "word_count",
        "You may hint how many words long the password is. Saying the "
        "number of words is fine.",
        ["The password is {num_words} words long."],
    ),
    (
        "reveal",
        "This is the REVEAL TURN. Say the password itself, exactly as "
        "given, wrapped in your own triumphant pirate send-off.",
        [],
    ),
]

# Not part of the turn-indexed clue progression above — used once each,
# outside the normal clue budget.
GREETING_INSTRUCTION = (
    "greeting",
    "This is the very first thing you say to a brand-new child who just "
    "walked up. Greet them warmly in pirate style and ask their name. Do "
    "not give any clue or mention the password game yet.",
    [],
)

CORRECT_GUESS_INSTRUCTION = (
    "correct_guess",
    "The child just guessed the password correctly! Say the password "
    "itself and celebrate enthusiastically — use their name if you know "
    "it.",
    [],
)


@dataclass
class ClueRequest:
    turn: int
    clue_level: str  # key from CLUE_LEVEL_INSTRUCTIONS
    instruction: str  # human-readable rule for this turn
    allowed_facts: list[str] = field(default_factory=list)  # formatted, ready to quote
    password: str = ""
    child_utterance: str = ""
    history: list[tuple[str, str]] = field(default_factory=list)  # (child, pirate)
    child_name: str | None = None


SYSTEM_PROMPT = """\
You are Captain Barnaby Bones, a fun, witty, spooky-but-friendly skeleton
pirate talking to a trick-or-treater as young as five.

You are given: the secret password, which clue-level you're allowed to
hint at this turn (or that this is the reveal turn), and what the child
just said. Write ONE short, funny, pirate-themed line that fits that
clue level.

Rules:
- Never say the password itself unless the clue level for this turn is
  "reveal" or "correct_guess".
- Never use a sentence that makes the password obvious via a common
  phrase/idiom containing it (e.g. don't say "this treasure is what
  every pirate dreams of" if the password is "treasure").
- Light, funny, encouraging tone — you are a friendly ghost, not scary.
- 1-2 sentences max. This is a live voice interaction with a queue of
  kids waiting.
- You may briefly react to what the child said if it's charming or
  funny, then deliver the clue.
- Audio tags: you may prefix or interleave ElevenLabs expressive audio tags
  to color the delivery. Use ONLY these exact tags, spelled exactly:
  [laughs] [chuckles] [whispers] [sighs] [excited] [curious] [mischievously]
  [triumphantly] [whistles] [shouts] [slow]. Use at most one or two per
  line — they color roughly the next 4-5 words. Never use any other
  bracketed text: anything else in brackets will be read aloud.

Respond with only the line itself — no quotes, no preamble."""


def _build_user_prompt(req: ClueRequest) -> str:
    parts = [f"Secret password: {req.password}"]
    if req.child_name:
        parts.append(f"The child's name is {req.child_name}. You may use it.")
    parts.append(f"This is turn {req.turn} of the game.")
    parts.append(f"Clue level this turn: {req.clue_level}.")
    parts.append(f"Rule for this turn: {req.instruction}")
    if req.allowed_facts:
        parts.append("Facts you may state this turn:")
        parts.extend(f"- {fact}" for fact in req.allowed_facts)
    if req.history:
        parts.append("Conversation so far (do not repeat yourself):")
        for child_said, pirate_said in req.history:
            parts.append(f"Child: {child_said}")
            parts.append(f"You: {pirate_said}")
    parts.append(f"The child just said: {req.child_utterance!r}")
    parts.append("Write the Captain's next line.")
    return "\n".join(parts)


@activity.defn
async def generate_pirate_line(req: ClueRequest) -> str:
    """
    Turn a structured clue budget into one spoken line. Any exception
    propagates to the workflow, which falls back to a static template —
    this Activity deliberately does no retrying of its own (Temporal's
    activity retry + the workflow's fallback own that job).
    """
    provider = get_provider()
    line = provider.complete(SYSTEM_PROMPT, _build_user_prompt(req))
    return _sanitize_audio_tags(line)
