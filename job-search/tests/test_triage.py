"""Test triage sender filtering, text extraction, and IMAP proxy connect."""

import os
import socket
import ssl
import subprocess
import sys
from pathlib import Path

import pytest

from job_search.triage import _allowed_senders, _connect_via_proxy, _extract, _ProxyIMAP4
from tests.fixtures import read_fixture


def test_allowed_senders_default():
    senders = _allowed_senders()
    assert "jobalerts-noreply@linkedin.com" in senders


def test_allowed_senders_from_env(monkeypatch):
    monkeypatch.setenv("TRIAGE_ALLOWED_SENDERS",
                       "jobalerts-noreply@linkedin.com, jobs-noreply@linkedin.com")
    senders = _allowed_senders()
    assert "jobalerts-noreply@linkedin.com" in senders
    assert "jobs-noreply@linkedin.com" in senders


def test_extract_allows_linkedin_sender():
    raw = read_fixture("is-hiring.eml")
    from_addr, dedup_key, plain, html, used_fallback, rejected = _extract(raw)
    assert "linkedin.com" in from_addr.lower()
    assert "Platform Reliability Engineer" in plain
    assert len(dedup_key) == 64
    assert used_fallback
    assert not rejected


def test_extract_rejects_unknown_sender():
    raw = read_fixture("spam.eml")
    from_addr, dedup_key, plain, html, used_fallback, rejected = _extract(raw)
    assert rejected
    assert plain == ""
    assert html == ""
    assert len(dedup_key) == 64


def test_extract_returns_plain_and_html():
    raw = read_fixture("is-hiring.eml")
    _from_addr, dedup_key, plain, html, used_fallback, rejected = _extract(raw)
    assert len(plain) > 0
    assert "AcmeCloud" in plain
    assert len(dedup_key) == 64
    assert not rejected


def test_triage_disabled_by_default():
    from job_search import triage
    assert not triage.ENABLED


def test_module_entry_point_runs_main():
    src = Path(__file__).resolve().parent.parent / "src"
    env = dict(os.environ)
    env["JOB_TRIAGE_ENABLED"] = "0"
    env["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    env["PYTHONPATH"] = str(src) + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.run(
        [sys.executable, "-m", "job_search.triage"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(src),
        timeout=120,
    )

    output = proc.stdout + proc.stderr
    assert proc.returncode == 0
    assert "job triage disabled" in output


def test_extract_dedup_key_stable_for_same_message_id():
    raw = read_fixture("is-hiring.eml")
    r1 = _extract(raw)
    r2 = _extract(raw)
    assert r1[1] == r2[1]
    assert len(r1[1]) == 64


def test_extract_fallback_key_when_no_message_id():
    raw = read_fixture("spam.eml")
    from_addr, dedup_key, plain, html, used_fallback, rejected = _extract(raw)
    assert rejected
    assert len(dedup_key) == 64
    assert plain == ""


def test_extract_fallback_key_used():
    import hashlib

    no_message_id = (
        b"From: LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>\r\n"
        b"Date: Mon, 01 Jan 2024 10:00:00 +0000\r\n"
        b"Subject: Test Alert\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"Some body text\r\n"
    )
    result = _extract(no_message_id)
    from_addr, dedup_key, plain, html, used_fallback, rejected = result
    assert "linkedin" in from_addr.lower()
    assert not rejected
    assert used_fallback
    assert len(dedup_key) == 64
    expected = hashlib.sha256(
        b"Mon, 01 Jan 2024 10:00:00 +0000|"
        b"LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>|Test Alert"
    ).hexdigest()
    assert dedup_key == expected


def test_rejected_sender_still_returns_dedup_key():
    non_linkedin = (
        b"From: Bad Sender <spammer@example.com>\r\n"
        b"Date: Mon, 01 Jan 2024 10:00:00 +0000\r\n"
        b"Subject: Buy stuff\r\n"
        b"Message-ID: <abc123@example.com>\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"Spam body\r\n"
    )
    from_addr, dedup_key, plain, html, used_fallback, rejected = _extract(non_linkedin)
    assert rejected
    assert "spammer@example.com" in from_addr.lower()
    assert len(dedup_key) == 64
    assert plain == ""
    assert html == ""
    assert not used_fallback


class _FakeProxySocket:
    def __init__(self, response):
        self.sent = b""
        self._response = response

    def sendall(self, data):
        self.sent += data

    def recv(self, _n):
        return self._response


def test_connect_via_proxy_sends_connect_line(monkeypatch):
    fake = _FakeProxySocket(b"HTTP/1.1 200 Connection established\r\n\r\n")
    monkeypatch.setattr(socket, "create_connection", lambda addr, timeout=None: fake)
    ctx = ssl.create_default_context()
    monkeypatch.setattr(ctx, "wrap_socket", lambda sock, server_hostname: (sock, server_hostname))

    result = _connect_via_proxy("http://proxy.example.com:3128", "imap.gmail.com", 993, ctx)

    assert result == (fake, "imap.gmail.com")
    assert fake.sent == b"CONNECT imap.gmail.com:993 HTTP/1.1\r\nHost: imap.gmail.com:993\r\n\r\n"


def test_connect_via_proxy_rejects_non_200(monkeypatch):
    fake = _FakeProxySocket(b"HTTP/1.1 403 Forbidden\r\n\r\n")
    monkeypatch.setattr(socket, "create_connection", lambda addr, timeout=None: fake)
    ctx = ssl.create_default_context()

    with pytest.raises(ConnectionError, match="403"):
        _connect_via_proxy("http://proxy.example.com:3128", "imap.gmail.com", 993, ctx)


def test_proxy_imap_reads_greeting_through_tunnel():
    class FakeTunnel:
        def __init__(self):
            self.sent = b""
            self._tag = b""
            self._stage = 0

        def sendall(self, data):
            self.sent += data
            self._tag = data.split(b" ")[0]

        def makefile(self, _mode):
            return self

        def readline(self, _n):
            if self._stage == 0:
                self._stage = 1
                return b"* OK IMAP4rev1 Service Ready\r\n"
            if self._stage == 1:
                self._stage = 2
                return b"* CAPABILITY IMAP4rev1\r\n"
            if self._stage == 2:
                self._stage = 3
                return self._tag + b" OK CAPABILITY completed\r\n"
            return b""

    tunnel = FakeTunnel()
    conn = _ProxyIMAP4("imap.gmail.com", 993, tunnel)

    assert conn.sock is tunnel
    assert conn.welcome == b"* OK IMAP4rev1 Service Ready"