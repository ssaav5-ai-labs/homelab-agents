"""Helpers for tests that read .eml fixtures."""

from pathlib import Path

FIXTURES = Path(__file__).parent


def read_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def extract_text_plain(raw_bytes: bytes) -> str:
    import email
    import email.policy

    msg = email.message_from_bytes(raw_bytes, policy=email.policy.default)
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            payload = part.get_payload(decode=True)
            if payload:
                return payload.decode("utf-8", errors="replace")
    return ""