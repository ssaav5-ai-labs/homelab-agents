---
name: lab-status
description: Read-only health summary of the homelab cluster. Use when asked "how is the lab", for a daily report, or as a first check before investigating anything.
version: 0.1.0
license: MIT
metadata:
  hermes:
    tags: [homelab, kubernetes, sre]
    requires_toolsets: [terminal]
---

# lab-status

Read-only health summary of the homelab k3s cluster. Produces a short report (five lines at most) with the worst thing first.

## Commands, in order

1. `kubectl get nodes -o wide`
2. `kubectl top nodes`
3. `kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded`
4. Pods with restarts in the last 24 hours (only count restarts whose `lastState.terminated.finishedAt` is within the last 24h):
   ```
   kubectl get pods -A -o json | python3 -c "
   import json, sys
   from datetime import datetime, timezone, timedelta
   data = json.load(sys.stdin)
   now = datetime.now(timezone.utc)
   cutoff = now - timedelta(hours=24)
   for item in data['items']:
       for c in item['status'].get('containerStatuses', []):
           last = c.get('lastState', {}).get('terminated', {})
           if last.get('finishedAt'):
               t = datetime.fromisoformat(last['finishedAt'].replace('Z', '+00:00'))
               if t > cutoff:
                   print(f\"{item['metadata']['namespace']}/{item['metadata']['name']} {c['name']} restarts={c.get('restartCount', 0)}\")
   "
   ```
5. `kubectl get applications -n argocd` — sync status and health
6. `kubectl get events -A --field-selector type=Warning --sort-by=.lastTimestamp | tail -20`
7. PVC usage if visible: `kubectl get pvc -A`

## Output format

First line: worst finding ("All good" or the most severe issue). Then up to four bullets with specific observations. End with "nothing else odd" or a short list.

## Limits

- Read-only: never `kubectl delete`, `apply`, `edit`, `patch`, `scale`, `drain`, or `exec`.
- If something needs a change, say what and why, and stop. Give the human the exact command to run.