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

- If the tool returns a table, post it as it is, then end with:

  > Proposals only: open a PR in homelab-gitops to apply.

- If the tool returns `capacity report unavailable: <reason>`, say exactly that and stop. Do **not** invent workloads, nodes, or numbers.

## Limits

- The report proposes request/limit changes; it never applies them.
- The table is the tool's computed output; never fill in a missing table from memory.
- If the tool errors, times out, or returns "busy", say so and suggest running it again later.
