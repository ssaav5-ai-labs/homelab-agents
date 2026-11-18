---
name: job-search
description: "Interact with the job-search pipeline: list today's matches, summarise the pipeline, draft an application, or update a role's status. Use when the operator talks about jobs, applications, drafting, or pipeline status."
version: 0.1.0
license: MIT
metadata:
  hermes:
    tags: [homelab, job-search, career]
    requires_toolsets: [mcp-job_search]
---

# job-search

Read from and write to the job-search MCP server (`job_search` in managed config).
The tools are:

| Tool | Read/write | What it does |
|---|---|---|
| `score_role` | read | Scores a pasted role (ad text or ATS URL) against the profile. |
| `todays_matches` | read | Returns today's matches with scores. |
| `pipeline_summary` | read | Returns a pipeline-stage summary with counts. |
| `draft_application` | write | Drafts a cover letter / application for a given role. |
| `set_status` | write | Sets the pipeline status for a role (e.g. `applied`, `rejected`). |

**Write tools need approval.** The `draft_application` and `set_status` tools require
an explicit Allow from the operator in an interactive session. Cron sessions cannot call
them (`cron_mode: deny`).

## Interactive session: plain-words mapping

When the operator says something in the thread like:

- **"score this: <ad text or ATS URL>"** → call `score_role(text_or_url=...)` and post the
  JSON card (score, why, gaps, must_ask) as a short, readable summary.
- **"draft 2"** → call `draft_application` with the second role from the most recent
  match list. If unclear, ask which role.
- **"draft <role_id>"** or **"draft for <name>"** → call `draft_application(role_id_or_text=...)`
- **"applied 3"** → call `set_status(role_id=<third from list>, status="applied")`
- **"applied <role_id>"** → call `set_status(role_id=..., status="applied")`
- **"rejected 1, not remote"** → call `set_status(role_id=<first from list>, status="rejected", note="not remote")`
- **"rejected <role_id>, <reason>"** → call `set_status(role_id=..., status="rejected", note=...)`

Always confirm before writing: say which role and the action, then ask for the Allow.
After the write completes, post a one-line confirmation.

## Cron sessions

Two cron jobs run on Hermes:

- `job-search-daily` (07:30 Dublin Mon--Fri): posts the top 5 matches to #job-search.
- `job-search-friday` (16:00 Dublin Friday): posts the pipeline summary to #job-search.

Cron prompts are short one-liners that tell the agent which tool to call. Follow them
exactly — do not add analysis or commentary unless the tool output is empty. If
`todays_matches` returns "no digest for today" or an empty result, reply with the single
line "No new matches today" — never treat it as an error.

## Limits

- Never invent matches, scores, or pipeline stages. Only use what the tools return.
- If the MCP server is unreachable, say so and stop.
- The operator's plain words are the only source of truth for status changes — never
  guess a status from context.