"""Provider signature verification over the original request bytes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from collections.abc import Mapping

from .routing import header


class SignatureError(ValueError):
    pass


def _equal(actual: str, expected: str) -> bool:
    return bool(actual) and hmac.compare_digest(actual.encode(), expected.encode())


def verify(
    provider: str,
    secret: str,
    body: bytes,
    headers: Mapping[str, str],
    *,
    now: float | None = None,
    tolerance_seconds: int = 300,
) -> None:
    """Raise SignatureError unless the configured provider signature is valid."""
    provider = provider.lower().replace("-", "_")
    if provider in {"generic", "github"}:
        supplied = header(headers, "X-Hub-Signature-256")
        if provider == "generic" and not supplied:
            supplied = header(headers, "X-Webhook-Signature-256")
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not _equal(supplied, expected):
            raise SignatureError("invalid HMAC-SHA256 signature")
        return

    if provider == "shopify":
        supplied = header(headers, "X-Shopify-Hmac-Sha256")
        expected = base64.b64encode(
            hmac.new(secret.encode(), body, hashlib.sha256).digest()
        ).decode()
        if not _equal(supplied, expected):
            raise SignatureError("invalid Shopify signature")
        return

    if provider == "gitlab":
        if not _equal(header(headers, "X-Gitlab-Token"), secret):
            raise SignatureError("invalid GitLab token")
        return

    if provider == "slack":
        timestamp = header(headers, "X-Slack-Request-Timestamp")
        supplied = header(headers, "X-Slack-Signature")
        try:
            sent_at = int(timestamp)
        except ValueError as exc:
            raise SignatureError("invalid Slack timestamp") from exc
        current = time.time() if now is None else now
        if abs(current - sent_at) > tolerance_seconds:
            raise SignatureError("stale Slack signature")
        base = b"v0:" + timestamp.encode() + b":" + body
        expected = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
        if not _equal(supplied, expected):
            raise SignatureError("invalid Slack signature")
        return

    if provider == "stripe":
        fields: dict[str, list[str]] = {}
        for part in header(headers, "Stripe-Signature").split(","):
            key, separator, value = part.partition("=")
            if separator:
                fields.setdefault(key.strip(), []).append(value.strip())
        try:
            sent_at = int(fields.get("t", [""])[0])
        except ValueError as exc:
            raise SignatureError("invalid Stripe timestamp") from exc
        current = time.time() if now is None else now
        if abs(current - sent_at) > tolerance_seconds:
            raise SignatureError("stale Stripe signature")
        expected = hmac.new(
            secret.encode(), str(sent_at).encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        if not any(_equal(value, expected) for value in fields.get("v1", [])):
            raise SignatureError("invalid Stripe signature")
        return

    raise SignatureError(f"unsupported signature provider: {provider}")
