"""Gateway LLM configuration for the job-search crew.

Two model aliases (ADR-0008): ``jobs-fast`` and ``jobs-reason``, with
OpenRouter ``data_collection: deny`` and message redaction.  The scoring
path uses a tuned variant that requests JSON output, disables reasoning,
and allows more tokens.
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