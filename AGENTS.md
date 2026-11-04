# Instructions for AI agents

This repo holds agent skills, crews and MCP servers for the homelab. Hermes reads skills from here; nothing here is applied directly to the cluster.

## Read first
- The handbook: https://github.com/ssaav5-ai-labs/handbook
- The playbook protocol: `playbooks/RUNNING.md` in the handbook.
- Decisions: `docs/decisions/` in the handbook; open questions: `docs/open-questions/`.

## Rules
- Never commit secrets, tokens, real public IPs or hostnames. Use placeholders.
- Never push to `main`; open a PR.
- **Skills must be read-only by default.** A skill may tell an agent to propose a change, never to make one.
- If reality differs from the playbook, fix the run, then propose a playbook edit in the same PR.
- Scratch work goes in /tmp/agent/, never directly in /tmp.