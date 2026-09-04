"""
LLM providers for turning a structured clue budget into Captain Barnaby
Bones' actual spoken line.

The workflow decides WHAT may be said (turn number, clue level, reveal or
not); a provider here decides the exact WORDS. Providers are only ever
called from Temporal Activities, never from workflow code — workflows
must stay deterministic.

Provider selection: PIRATE_LLM_PROVIDER env var (default "bedrock").

ElevenLabs note: they do NOT have a standalone text-completion API —
their LLM offerings are the hosted Conversational AI platform or
bring-your-own-LLM slots in Speech Engine (checked their docs,
2026-09-03). Since we already moved off their hosted agent, Bedrock is
the only implementation for now; add a class and register it below if
that ever changes.
"""

import os
from abc import ABC, abstractmethod

# Bedrock now requires an inference-profile ID (not the raw foundation-model
# ID) for on-demand Claude invocations; the "us." prefix is the cross-region
# profile form.
DEFAULT_BEDROCK_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
DEFAULT_BEDROCK_REGION = "us-west-2"


class LLMProvider(ABC):
    """Minimal interface: system prompt + user prompt in, one line out."""

    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Return the model's text. Raise on any failure — the Activity
        caller (the workflow) falls back to a static template, so
        providers don't need to retry or self-rescue."""


class BedrockConverseProvider(LLMProvider):
    def __init__(
        self,
        model_id: str = DEFAULT_BEDROCK_MODEL_ID,
        region: str | None = None,
        profile: str | None = None,
    ) -> None:
        import boto3

        self._model_id = model_id
        session_kwargs = {}
        if profile:
            session_kwargs["profile_name"] = profile
        # Explicit region wins, else fall back to AWS_REGION/boto3 default.
        session = boto3.Session(region_name=region, **session_kwargs)
        self._client = session.client("bedrock-runtime")

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        response = self._client.converse(
            modelId=self._model_id,
            system=[{"text": system_prompt}],
            messages=[
                {"role": "user", "content": [{"text": user_prompt}]},
            ],
            inferenceConfig={"maxTokens": 150, "temperature": 1.0},
        )
        return response["output"]["message"]["content"][0]["text"]


def get_provider() -> LLMProvider:
    name = os.environ.get("PIRATE_LLM_PROVIDER", "bedrock").lower()
    model_id = os.environ.get("PIRATE_BEDROCK_MODEL_ID", DEFAULT_BEDROCK_MODEL_ID)
    region = os.environ.get("PIRATE_BEDROCK_REGION", DEFAULT_BEDROCK_REGION)
    profile = os.environ.get("PIRATE_AWS_PROFILE") or None
    if name == "bedrock":
        return BedrockConverseProvider(model_id=model_id, region=region, profile=profile)
    raise ValueError(
        f"Unknown PIRATE_LLM_PROVIDER {name!r}. Available: bedrock. "
        "(ElevenLabs has no standalone text-completion API — see module docstring.)"
    )
