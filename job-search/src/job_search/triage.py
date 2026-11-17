"""Daily job-triage entry point (CronJob).

Reads unseen job-alert emails from the dedicated mailbox via IMAP
(BODY.PEEK, read-only), filters by allowed From addresses, parses them,
applies deterministic rules, scores with ``fast``, and writes
``digests/YYYY-MM-DD.md`` into the vault.
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

_DEFAULT_ALLOWED_SENDERS = "jobalerts-noreply@linkedin.com"


def _allowed_senders() -> set[str]:
    raw = os.environ.get("TRIAGE_ALLOWED_SENDERS", _DEFAULT_ALLOWED_SENDERS)
    return {a.strip().lower() for a in raw.split(",") if a.strip()}


def _imap_connect() -> imaplib.IMAP4_SSL:
    host = os.environ["IMAP_HOST"]
    user = os.environ["IMAP_USER"]
    password = os.environ["IMAP_APP_PASSWORD"]

    ctx = ssl.create_default_context()
    conn = imaplib.IMAP4_SSL(host, 993, ssl_context=ctx)
    conn.login(user, password)
    return conn


def _fetch_new_alerts(conn: imaplib.IMAP4_SSL) -> list[bytes]:
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
    bodies: list[bytes] = []
    for msg_id in ids:
        typ, data = conn.fetch(msg_id, "(BODY.PEEK[])")
        if typ != "OK":
            logger.warning("IMAP FETCH %s failed: %s", msg_id, typ)
            continue
        bodies.append(data[0][1])

    return bodies


def _extract(msg_bytes: bytes) -> tuple[str, str, str] | None:
    """Return (from_addr, text/plain body, text/html body) or None if sender not allowed."""
    msg = email.message_from_bytes(msg_bytes, policy=email.policy.default)
    from_addr = msg.get("From", "")
    from_addr_low = from_addr.lower()
    allowed = _allowed_senders()

    if not any(addr in from_addr_low for addr in allowed):
        logger.info("ignoring message from %s (not in allowed senders)", from_addr)
        return None

    plain = ""
    html = ""
    for part in msg.walk():
        ct = part.get_content_type()
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        decoded = payload.decode("utf-8", errors="replace")
        if ct == "text/plain" and not plain:
            plain = decoded
        elif ct == "text/html" and not html:
            html = decoded

    return from_addr, plain, html


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
    ignored = 0
    for raw in alerts:
        extracted = _extract(raw)
        if extracted is None:
            ignored += 1
            continue
        _from_addr, plain, html = extracted
        if plain:
            records = _parse_alert(plain, "text/plain")
            if not records and html:
                records = _parse_alert(html, "text/html")
        elif html:
            records = _parse_alert(html, "text/html")
        else:
            continue
        all_records.extend(records)

    logger.info("parsed %d records, ignored %d messages", len(all_records), ignored)

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
        f"Alerts: {len(alerts)}, ignored: {ignored}, "
        f"after rules: {len(passed)}, shortlist: {len(shortlist)}",
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