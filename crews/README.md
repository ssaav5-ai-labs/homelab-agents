# sre-crews

Two CrewAI crews behind an MCP server that Hermes calls:

- `investigate_alert` — triager → investigator → scribe, produces a short diagnosis report.
- `weekly_capacity_report` — one analyst, proposes right-sizing.

Both are read-only. See the handbook's `reference-sre-crews.md` for details.

## Layout

- `src/sre_crews/` — the crews (`investigate.py`, `capacity.py`), their tools (`tools.py`), the MCP server (`server.py`), and the gateway LLM config (`llm.py`).
- `tests/` — no model, no network.
- `Dockerfile` — built by CI into `ghcr.io/ssaav5-ai-labs/sre-crews`.

## Run the tests

```bash
uv sync --all-groups
uv run pytest
uv run ruff check
```
