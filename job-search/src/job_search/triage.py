"""Daily job-triage entry point (CronJob).

Reads unseen job-alert emails from the dedicated mailbox via IMAP
(BODY.PEEK, read-only), filters by allowed From addresses, parses them,
applies deterministic rules, scores with ``fast``, and writes
``digests/YYYY-MM-DD.md`` into the vault.
"""

from __future__ import annotations

import email
import email.policy
import hashlib
import imaplib
import logging
import os
import re
import socket
import ssl
import sys
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from .parse import parse_alert as _parse_alert
from .rules import apply_rules
from .score import score_role as _score_role
from .vault import (
    read_digest,
    read_processed_state,
    read_recent_digests,
    read_roles,
    render_processed_state,
    write_digest_and_state,
)

logger = logging.getLogger("job-search.triage")

ENABLED = os.environ.get("JOB_TRIAGE_ENABLED", "0") in ("1", "true", "yes")

_DEFAULT_ALLOWED_SENDERS = "jobalerts-noreply@linkedin.com"


def _allowed_senders() -> set[str]:
    raw = os.environ.get("TRIAGE_ALLOWED_SENDERS", _DEFAULT_ALLOWED_SENDERS)
    return {a.strip().lower() for a in raw.split(",") if a.strip()}


def _connect_via_proxy(
    proxy_url: str, host: str, port: int, ctx: ssl.SSLContext
) -> ssl.SSLSocket:
    """Open a CONNECT tunnel through an HTTP proxy and wrap it in TLS."""
    pr = urlparse(proxy_url)
    if pr.scheme != "http":
        raise ValueError(f"IMAP_PROXY must be an http:// URL, got {proxy_url!r}")
    sock = socket.create_connection((pr.hostname, pr.port or 3128), timeout=30)
    sock.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("proxy closed during CONNECT")
        buf += chunk
    status = buf.split(b"\r\n", 1)[0].decode(errors="replace")
    if status.split()[1] != "200":
        raise ConnectionError(f"proxy CONNECT refused: {status}")
    return ctx.wrap_socket(sock, server_hostname=host)


class _ProxyIMAP4(imaplib.IMAP4):
    """IMAP4 over a pre-built CONNECT tunnel; ``_create_socket`` returns the TLS socket."""

    def __init__(self, host: str, port: int, tunnel_socket: ssl.SSLSocket, timeout: int = 30):
        self._tunnel_socket = tunnel_socket
        super().__init__(host, port, timeout=timeout)

    def _create_socket(self, timeout) -> ssl.SSLSocket:
        return self._tunnel_socket


def _imap_connect() -> imaplib.IMAP4:
    host = os.environ["IMAP_HOST"]
    user = os.environ["IMAP_USER"]
    password = os.environ["IMAP_APP_PASSWORD"]

    ctx = ssl.create_default_context()
    proxy = os.environ.get("IMAP_PROXY")
    if proxy:
        tunnel = _connect_via_proxy(proxy, host, 993, ctx)
        conn = _ProxyIMAP4(host, 993, tunnel, timeout=30)
    else:
        conn = imaplib.IMAP4_SSL(host, 993, ssl_context=ctx)
    conn.login(user, password)
    return conn


def _fetch_new_alerts(conn: imaplib.IMAP4) -> list[bytes]:
    conn.select("INBOX", readonly=True)
    since = (datetime.now(UTC).date() - timedelta(days=2)).strftime("%d-%b-%Y")
    typ, data = conn.search(None, "SINCE", since)
    if typ != "OK":
        logger.warning("IMAP SEARCH failed: %s", typ)
        return []
    ids = data[0].split()
    if not ids:
        logger.info("no messages since %s", since)
        return []

    logger.info("fetching %d messages since %s with BODY.PEEK", len(ids), since)
    bodies: list[bytes] = []
    for msg_id in ids:
        typ, data = conn.fetch(msg_id, "(BODY.PEEK[])")
        if typ != "OK":
            logger.warning("IMAP FETCH %s failed: %s", msg_id, typ)
            continue
        bodies.append(data[0][1])

    return bodies


def _extract(msg_bytes: bytes) -> tuple[str, str, str, str, bool] | None:
    """Return (from_addr, dedup_key, plain, html, used_fallback) or None if sender not allowed.

    ``dedup_key`` is the sha256 of the Message-ID header, or of ``Date|From|Subject``
    when there is no Message-ID (``used_fallback`` is then True).
    """
    msg = email.message_from_bytes(msg_bytes, policy=email.policy.default)
    from_addr = msg.get("From", "")
    from_addr_low = from_addr.lower()
    allowed = _allowed_senders()

    if not any(addr in from_addr_low for addr in allowed):
        logger.info("ignoring message from %s (not in allowed senders)", from_addr)
        return None

    message_id = (msg.get("Message-ID") or "").strip()
    used_fallback = not message_id
    if message_id:
        dedup_key = hashlib.sha256(message_id.encode()).hexdigest()
    else:
        combined = "|".join([msg.get("Date", ""), from_addr, msg.get("Subject", "")])
        dedup_key = hashlib.sha256(combined.encode()).hexdigest()

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

    return from_addr, dedup_key, plain, html, used_fallback


def run() -> None:
    if not ENABLED:
        logger.info("job triage disabled (JOB_TRIAGE_ENABLED!=1)")
        return

    started = time.monotonic()
    logger.info("triage started")
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    processed_state = read_processed_state()

    existing_digest = read_digest(today)

    try:
        conn = _imap_connect()
    except Exception as exc:
        logger.error("IMAP connect failed: %s", exc)
        lines = [f"# Triage {today}", "", f"IMAP connect failed: {exc}"]
        state_text = render_processed_state(processed_state, today)
        write_digest_and_state(today, "\n".join(lines), state_text)
        return
    logger.info("IMAP login ok")

    try:
        alerts = _fetch_new_alerts(conn)
        conn.logout()
    except Exception as exc:
        logger.error("IMAP fetch failed: %s", exc)
        conn.logout()
        lines = [f"# Triage {today}", "", f"IMAP fetch failed: {exc}"]
        state_text = render_processed_state(processed_state, today)
        write_digest_and_state(today, "\n".join(lines), state_text)
        return
    logger.info("alerts fetched=%d", len(alerts))

    all_records = []
    ignored = 0
    already_processed = 0
    for raw in alerts:
        extracted = _extract(raw)
        if extracted is None:
            ignored += 1
            continue
        _from_addr, dedup_key, plain, html, used_fallback = extracted
        if dedup_key in processed_state:
            already_processed += 1
            logger.info("email already processed: %s", dedup_key)
            continue
        processed_state[dedup_key] = today
        if plain:
            records = _parse_alert(plain, "text/plain")
            if not records and html:
                records = _parse_alert(html, "text/html")
        elif html:
            records = _parse_alert(html, "text/html")
        else:
            continue
        all_records.extend(records)

    logger.info(
        "parsed %d records, ignored %d messages, already processed=%d",
        len(all_records), ignored, already_processed,
    )

    recent_digests = read_recent_digests(14)
    recent_source_ids: set[str] = set()
    for content in recent_digests.values():
        for m in re.finditer(r"- Source: linkedin \((\d+)\)", content):
            recent_source_ids.add(m.group(1))
    for role in read_roles():
        if role.get("source_id"):
            recent_source_ids.add(role["source_id"])

    if recent_source_ids:
        filtered = []
        digest_skipped = 0
        for rec in all_records:
            if rec.source_id in recent_source_ids:
                digest_skipped += 1
                continue
            filtered.append(rec)
        logger.info("digest dedupe skipped=%d", digest_skipped)
        all_records = filtered

    passed, skipped = apply_rules(all_records)
    logger.info("kept=%d", len(passed))

    scored = []
    for role in passed:
        try:
            result = _score_role(role.description or f"{role.title} at {role.company}")
            scored.append((role, result))
        except Exception as exc:
            logger.error("score failed: %s", exc)

    sorted_scored = sorted(scored, key=lambda x: x[1].get("score", 0), reverse=True)
    cap = int(os.environ.get("DAILY_CAP", "5"))
    threshold = int(os.environ.get("SHORTLIST_THRESHOLD", "70"))
    shortlist = [(r, s) for r, s in sorted_scored if s.get("score", 0) >= threshold][:cap]
    logger.info("shortlisted=%d", len(shortlist))

    if existing_digest and shortlist:
        new_lines = []
        for role, result in shortlist:
            new_lines.append(f"### {role.title} at {role.company}")
            new_lines.append(f"- Score: {result.get('score', '?')}/100")
            new_lines.append(f"- Why: {result.get('why', '')}")
            new_lines.append(f"- Gaps: {result.get('gaps', '')}")
            new_lines.append(f"- URL: {role.url}")
            new_lines.append(f"- Source: {role.source} ({role.source_id})")
            new_lines.append("")
        digest_content = existing_digest.rstrip() + "\n\n" + "\n".join(new_lines)
    else:
        lines = [
            f"# Daily digest {today}",
            "",
            f"Alerts: {len(alerts)}, ignored: {ignored}, already processed: {already_processed}, "
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

        digest_content = "\n".join(lines)

    state_text = render_processed_state(processed_state, today)
    commit_sha = write_digest_and_state(today, digest_content, state_text)
    logger.info("digest path=%s", f"job-search/digests/{today}.md")
    logger.info("commit sha=%s", commit_sha)
    logger.info("done in %.1fs", time.monotonic() - started)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        run()
    except Exception as exc:
        logger.error("triage failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()