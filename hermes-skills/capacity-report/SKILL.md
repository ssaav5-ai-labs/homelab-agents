---
name: capacity-report
description: "Weekly right-sizing proposal: compare each workload's requests with 7-day peak usage and list the ten largest gaps. Use when asked for the weekly capacity report."
version: 0.1.0
license: MIT
metadata:
  hermes:
    tags: [homelab, kubernetes, sre, capacity]
    requires_toolsets: [mcp-crews]
---

# capacity-report

Run the weekly capacity report. It is read-only and proposes changes only.

## Run it

Call the `weekly_capacity_report` tool (the crews MCP server). It takes no arguments and runs for one to four minutes, returning a table of the ten largest gaps between each workload's request and its 7-day peak.

## Reply

Post the returned table as it is, then end with:

> Proposals only: open a PR in homelab-gitops to apply.

## Limits

- The report proposes request/limit changes; it never applies them.
- If the tool errors, times out, or returns "busy", say so and suggest running it again later.
