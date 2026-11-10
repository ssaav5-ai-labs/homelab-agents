"""Gateway LLM configuration for the crews.

Two models, both reached through the in-cluster LiteLLM gateway by alias
(ADR-0008). The ``openai/`` prefix plus a ``base_url`` makes CrewAI use its
native OpenAI client against the gateway and send the alias as the model name.
"""

from __future__ import annotations

import os

from crewai import LLM


def make_llm(alias: str) -> LLM:
    base = os.environ["LAB_GATEWAY_URL"].rstrip("/")
    return LLM(
        model=f"openai/{alias}",
        base_url=f"{base}/v1",
        api_key=os.environ["CREWS_GATEWAY_KEY"],
        temperature=0.2,
        timeout=60,
    )
