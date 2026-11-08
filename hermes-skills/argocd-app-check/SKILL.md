---
name: argocd-app-check
description: "Check one Argo CD application in detail: sync status, health, last sync result and conditions, read-only."
version: 1.0.0
license: MIT
metadata:
  hermes:
    tags: [argocd, kubernetes, gitops, homelab]
    requires_toolsets: [terminal]
---

# argocd-app-check

Read-only deep inspection of one named Argo CD application. Use when the user asks for details on a specific app — "check the cert-manager app", "why is myapp degraded?", "what's the last sync result for monitoring?".

For a fleet-wide summary, use lab-status instead.

## Commands

All commands use `<name>` — the exact Argo CD application name as shown in `kubectl get applications -n argocd`.

### 1. Core status (single kubectl call)

```
kubectl get application <name> -n argocd -o json
```

Parse and present these sections from `status`:

#### Sync

- `status.sync.status` — `Synced`, `OutOfSync`, or `Unknown`
- `status.sync.revisions` — the revision(s) the app is synced to
- Source info from `status.sync.comparedTo.source` (or `.sources` for multi-source apps): repo URL, chart, path, target revision

#### Health

- `status.health.status` — `Healthy`, `Degraded`, `Progressing`, `Suspended`, `Missing`, or `Unknown`
- `status.health.message` — optional detail, often present when `Degraded`

#### Last operation

From `status.operationState` (may be absent if the app has never synced):

- `.phase` — `Succeeded`, `Failed`, `Error`, or `Running`
- `.message` — human-readable result (e.g. "successfully synced (all tasks run)")
- `.finishedAt` — when the operation completed
- `.syncResult` — if present, contains per-resource results:
  - `.revision` — the revision just applied
  - `.resources[].kind`, `.name`, `.namespace`, `.status`, `.message`, `.hookType`
  - Count synced vs total; list only resources where status is not `Synced`
- `.operation.sync.revisions` — what revision(s) the operation targeted

#### Conditions

`status.conditions` — array of `{type, message, lastTransitionTime, status}`. Common types: `Error`, `ComparisonError`, `HealthCheckError`. Report every condition — it's the most direct error signal.

#### Resources summary

`status.resources` — array of every managed resource. Summarize:

- Total resource count
- Count by `status` (Synced / OutOfSync) and `health.status` (Healthy / Progressing / Degraded / Missing)
- If any resource is Degraded or OutOfSync, list them with kind/name/namespace

### 2. Recent events for the app (optional, when debugging)

```
kubectl get events -n argocd --field-selector involvedObject.name=<name> --sort-by=.lastTimestamp | tail -20
```

Only run this when sync or health is unexpected and the core status doesn't explain it.

## Output format

Start with the app name and a one-line verdict (e.g. "Healthy and Synced", "Degraded — 2 resources failing"). Then present each section in order, worst-first within each section, omitting sections with nothing to report. End with "Run `kubectl get application <name> -n argocd -o yaml` for the full manifest."

## Limits

- Read-only: never `kubectl delete`, `apply`, `edit`, `patch`, `sync`, `rollback`, or any mutating Argo CD operation.
- If something needs a fix (failed sync, degraded), explain why and propose the change in Git (homelab-gitops), because Argo CD reverts manual changes; only give kubectl commands for read-only checks.
- If the app name isn't found, list existing app names from `kubectl get applications -n argocd --no-headers | cut -d' ' -f1` and ask which one.

