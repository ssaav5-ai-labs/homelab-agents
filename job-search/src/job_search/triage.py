"""Daily job-triage entry point (CronJob).

Reads unseen job-alert emails from the dedicated mailbox via IMAP
(BODY.PEEK, read-only), parses them, applies deterministic rules,
scores with ``fast``, and writes ``digests/YYYY-MM-DD.md`` into the vault.
"""

from __future__ import annotations

import email
import email.policy
import imaplib
import logging
import os
import ssl
import sys
from datetime import UTC, datetime

from .parse import parse_alert as _parse_alert
from .rules import apply_rules
from .score import score_role as _score_role
from .vault import write_digest

logger = logging.getLogger("job-search.triage")

ENABLED = os.environ.get("JOB_TRIAGE_ENABLED", "0") in ("1", "true", "yes")


def _imap_connect() -> imaplib.IMAP4_SSL:
    host = os.environ["IMAP_HOST"]
    user = os.environ["IMAP_USER"]
    password = os.environ["IMAP_APP_PASSWORD"]

    ctx = ssl.create_default_context()
    conn = imaplib.IMAP4_SSL(host, 993, ssl_context=ctx)
    conn.login(user, password)
    return conn


def _fetch_new_alerts(conn: imaplib.IMAP4_SSL) -> list[str]:
    conn.select("INBOX", readonly=True)
    typ, data = conn.search(None, "UNSEEN")
    if typ != "OK":
        logger.warning("IMAP SEARCH failed: %s", typ)
        return []
    ids = data[0].split()
    if not ids:
        logger.info("no unseen messages")
        return []

    logger.info("fetching %d unseen messages with BODY.PEEK", len(ids))
    bodies: list[str] = []
    for msg_id in ids:
        typ, data = conn.fetch(msg_id, "(BODY.PEEK[])")
        if typ != "OK":
            logger.warning("IMAP FETCH %s failed: %s", msg_id, typ)
            continue
        bodies.append(data[0][1].decode("utf-8", errors="replace"))

    return bodies


def _extract_text(msg_bytes: str) -> str:
    msg = email.message_from_string(msg_bytes, policy=email.policy.default)
    parts: list[str] = []
    for part in msg.walk():
        content_type = part.get_content_type()
        if content_type in ("text/plain", "text/html"):
            payload = part.get_payload(decode=True)
            if payload:
                parts.append(payload.decode("utf-8", errors="replace"))
    return "\n".join(parts)


def run() -> None:
    if not ENABLED:
        logger.info("job triage disabled (JOB_TRIAGE_ENABLED!=1)")
        return

    logger.info("triage started")
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    try:
        conn = _imap_connect()
    except Exception as exc:
        logger.error("IMAP connect failed: %s", exc)
        lines = [f"# Triage {today}", "", f"IMAP connect failed: {exc}"]
        write_digest(today, "\n".join(lines))
        return

    try:
        alerts = _fetch_new_alerts(conn)
        conn.logout()
    except Exception as exc:
        logger.error("IMAP fetch failed: %s", exc)
        conn.logout()
        lines = [f"# Triage {today}", "", f"IMAP fetch failed: {exc}"]
        write_digest(today, "\n".join(lines))
        return

    all_records = []
    for raw in alerts:
        text = _extract_text(raw)
        records = _parse_alert(text)
        all_records.extend(records)

    passed, skipped = apply_rules(all_records)

    scored = []
    for role in passed:
        try:
            result = _score_role(role.description or f"{role.title} at {role.company}")
            scored.append((role, result))
        except Exception as exc:
            logger.error("score failed for %s: %s", role.title, exc)

    sorted_scored = sorted(scored, key=lambda x: x[1].get("score", 0), reverse=True)
    cap = int(os.environ.get("DAILY_CAP", "5"))
    threshold = int(os.environ.get("SHORTLIST_THRESHOLD", "70"))
    shortlist = [(r, s) for r, s in sorted_scored if s.get("score", 0) >= threshold][:cap]

    lines = [
        f"# Daily digest {today}",
        "",
        f"Alerts: {len(alerts)}, after rules: {len(passed)}, shortlist: {len(shortlist)}",
        f"Threshold: {threshold}, cap: {cap}",
        "",
    ]

    if skipped:
        lines.append("## Skipped by rules")
        for s in skipped[:20]:
            lines.append(f"- {s}")
        lines.append("")

    if shortlist:
        lines.append("## Shortlist")
        for role, result in shortlist:
            lines.append(f"### {role.title} at {role.company}")
            lines.append(f"- Score: {result.get('score', '?')}/100")
            lines.append(f"- Why: {result.get('why', '')}")
            lines.append(f"- Gaps: {result.get('gaps', '')}")
            lines.append(f"- URL: {role.url}")
            lines.append(f"- Source: {role.source} ({role.source_id})")
            lines.append("")
    else:
        lines.append("No roles above threshold.")

    write_digest(today, "\n".join(lines))
    logger.info(
        "triage done: %d alerts, %d passed, %d shortlisted",
        len(alerts), len(passed), len(shortlist),
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        run()
    except Exception as exc:
        logger.error("triage failed: %s", exc)
        sys.exit(1)