"""Gateway LLM configuration for the job-search crew.

Two models, both reached through the in-cluster LiteLLM gateway by alias
(ADR-0008). Jobs uses ``jobs-fast`` and ``jobs-reason`` (with OpenRouter
``data_collection: deny``) instead of the shared aliases.
"""

from __future__ import annotations

import os

from crewai import LLM

GATEWAY_HEADERS = {
    "x-litellm-enable-message-redaction": "true",
}


def make_llm(alias: str) -> LLM:
    base = os.environ["LAB_GATEWAY_URL"].rstrip("/")
    return LLM(
        model=f"openai/{alias}",
        base_url=f"{base}/v1",
        api_key=os.environ["JOBS_GATEWAY_KEY"],
        temperature=0.2,
        timeout=60,
        extra_headers=GATEWAY_HEADERS,
    )