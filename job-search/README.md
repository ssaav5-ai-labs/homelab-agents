# job-search

Job-search MCP server and drafting crew for Hermes. Part of the [homelab-gitops](https://github.com/ssaav5-ai-labs/homelab-gitops) platform.

## What it does

- **MCP server** (`job_search.server`) — streamable HTTP on `:8000/mcp`, bearer token auth
- **Daily triage** (`job_search.triage`) — CronJob entry point: IMAP → parse → rules → score → digest
- **Drafting crew** — Analyst → Writer → Checker (CrewAI, sequential, no memory)

## Tools

| Tool | Hint | Writes |
|---|---|---|
| `score_role(text_or_url)` | read-only | nothing |
| `todays_matches()` | read-only | nothing |
| `pipeline_summary()` | read-only | nothing |
| `draft_application(role_id_or_text)` | not read-only | `job-search/drafts/` |
| `set_status(role_id, status, note)` | not read-only | `job-search/roles/` |

## Private data rule

Nothing personal enters this repo. Profile, CV, roles and drafts live only in the private `career-vault`. Code is generic; criteria come from the vault at runtime.

## Image

`ghcr.io/ssaav5-ai-labs/job-search` — built by CI on push to `main` touching `job-search/**`.