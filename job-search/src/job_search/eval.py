"""Eval entry point: ``python -m job_search.eval``

Reads ``vault/job-search/evals/rated.md``, scores every role with
``score_role_with_raw``, and prints a comparison table (role number, user score,
AI score, difference) plus the top-three overlap.

With ``--explain``, prints per-role criterion values, points, any deal-breaker
cap applied, and the final score — no ad text, no why text, no CV, no key.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

from .score import _DB_KEYS, ScoreError, _parse_dealbreaker, score_role_with_raw

logger = logging.getLogger("job-search")


def _extract_roles(path: Path) -> list[tuple[str, int, str, str, str]]:
    text = path.read_text(errors="replace")

    pivot = text.find("\n## ")
    if pivot == -1:
        if text.strip().startswith("## "):
            pivot = 0
        else:
            raise ValueError(f"no '## ' heading found in {path}")
    text = text[pivot:].strip()

    blocks = text.split("\n## ")
    roles: list[tuple[str, int, str, str, str]] = []
    for block in blocks:
        lines = block.split("\n")
        header = lines[0].removeprefix("## ").strip()
        num = header.split(".")[0].strip()
        title = re.sub(r"^\d+\.\s*", "", header).strip()
        user_score = 0
        link = ""
        ad_lines: list[str] = []
        body_started = False
        for line in lines[1:]:
            if line.startswith("- **My score:"):
                m = re.search(r"\d+", line)
                if m:
                    user_score = int(m.group())
                continue
            if line.startswith("- **Why:") or line.startswith("- **Link:"):
                if line.startswith("- **Link:"):
                    m = re.search(r"https?://\S+", line)
                    link = m.group(0) if m else ""
                continue
            if line == "---":
                break
            if line.strip() and not line.startswith("- "):
                body_started = True
            if body_started:
                ad_lines.append(line)
        ad_text = "\n".join(ad_lines).strip()
        roles.append((num, user_score, ad_text, link, title))
    return roles


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score evals against the gateway.")
    parser.add_argument(
        "--vault-path",
        default=None,
        help="Path to the career-vault repo root (uses VAULT_READ_ROOT if unset).",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Print per-criterion values, points, deal-breaker caps, and final score.",
    )
    parser.add_argument(
        "rated",
        nargs="?",
        default="job-search/evals/rated.md",
        help="Path to rated.md relative to the vault root.",
    )
    args = parser.parse_args(argv)

    import os

    vault_root = (
        args.vault_path or os.environ.get("VAULT_READ_ROOT") or "/workspace/career-vault"
    )
    rated_path = Path(vault_root) / args.rated

    if not rated_path.exists():
        alt = Path("/tmp/agent/career-vault") / args.rated
        if alt.exists():
            rated_path = alt

    roles = _extract_roles(rated_path)

    scores: list[tuple[str, int, object]] = []
    for num, user, ad, _link, title in roles:
        sys.stdout.write(f"{num}.")
        sys.stdout.flush()
        raw_reply = ""
        try:
            if not ad.strip():
                raise ScoreError("empty ad text (ad_len=0)")
            result, raw_reply = score_role_with_raw(ad, title=title)
            ai = int(result["score"])
        except ScoreError as exc:
            logger.error("role %s: %s", num, exc)
            sys.stdout.write(" ERR")
            sys.stdout.flush()
            ai = exc
        except Exception as exc:
            logger.error("role %s: unexpected %s", num, exc)
            sys.stdout.write(" ERR")
            sys.stdout.flush()
            ai = exc
        scores.append((num, user, ai))
        if args.explain:
            _print_explain(num, result if isinstance(ai, int) else None, len(ad), title)
    print()

    print(f"{'#':<4} {'You':>5} {'AI':>5} {'Δ':>5}")
    print("-" * 24)
    for num, user, ai_ in scores:
        if isinstance(ai_, int):
            diff = ai_ - user
            print(f"{num:<4} {user:>5} {ai_:>5} {diff:+>5}")
        else:
            print(f"{num:<4} {user:>5}   ERR")
    print("-" * 24)

    numeric = [(n, u, a) for n, u, a in scores if isinstance(a, int)]
    if not numeric:
        print("No successful scores — nothing to compare.")
        return 2

    user_top3 = {n for n, _u, _a in sorted(numeric, key=lambda x: -x[1])[:3]}
    ai_top3 = {n for n, _u, _a in sorted(numeric, key=lambda x: -x[2])[:3]}
    overlap = user_top3 & ai_top3
    print(f"Your top 3: {sorted(user_top3)}")
    print(f"AI  top 3:  {sorted(ai_top3)}")
    print(f"Overlap:    {sorted(overlap)} ({len(overlap)}/3)")
    return 0


_CRITERION_LABELS = {
    "scope_platform_sre": "platform_sre",
    "people_leadership": "people",
    "strategy_ownership": "strategy",
    "remote": "remote",
    "ai_ml_scope": "ai_ml",
    "salary_vs_floor": "salary",
}


def _print_explain(num: str, result: dict | None, ad_len: int, title: str) -> None:
    """Emit per-criterion diagnostics on stderr."""
    if result is None:
        print(f"  [{num}] ad={ad_len} ERR", file=sys.stderr)
        return
    score = result.get("score", 0)
    criteria = result.get("criteria", {})
    dealbreakers = result.get("dealbreakers", {})

    lines: list[str] = [f"  [{num}] ad={ad_len} score={score}"]
    for key, label in _CRITERION_LABELS.items():
        entry = criteria.get(key, {})
        value = entry.get("value", "unknown") if isinstance(entry, dict) else "unknown"
        lines.append(f"    {label}: {value}")
    db_active = []
    for db_key in _DB_KEYS:
        raw = dealbreakers.get(db_key, "no")
        triggered, quote = _parse_dealbreaker(raw)
        if triggered:
            db_active.append(f"{db_key}={quote[:60]}")
    if db_active:
        lines.append(f"    cap=40 trigger={'; '.join(db_active)}")
    print("\n".join(lines), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())