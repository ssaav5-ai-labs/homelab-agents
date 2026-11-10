# homelab-agents

Agent skills, crews and MCP servers for the homelab. Read by Hermes on k3s through git-sync (every 5 minutes). Nothing here is applied directly to the cluster — the GitOps source of truth is [homelab-gitops](https://github.com/ssaav5-ai-labs/homelab-gitops).

## What's here

- `hermes-skills/` — skills Hermes uses for chat and automation (health checks, alert triage). Reviewed in PRs; a merged skill reaches Hermes within 5 minutes.
- `crews/` — the SRE crews behind an MCP server that Hermes calls (`investigate_alert`, `weekly_capacity_report`). Crews only get read-only tools; see `crews/README.md`.
- `evals/alerts/` — alert payload fixtures for drilling the crews (step 9).

## For AI agents

Read [the handbook](https://github.com/ssaav5-ai-labs/handbook) first. See `AGENTS.md` for rules.