import base64
import hashlib
import hmac

import pytest

from webhookrelay_hermes.security import SignatureError, verify

BODY = b'{"id":"evt_1"}'
SECRET = "top-secret"


def test_github_hmac():
    signature = "sha256=" + hmac.new(SECRET.encode(), BODY, hashlib.sha256).hexdigest()
    verify("github", SECRET, BODY, {"X-Hub-Signature-256": signature})
    with pytest.raises(SignatureError):
        verify("github", SECRET, BODY + b"x", {"X-Hub-Signature-256": signature})


def test_shopify_hmac():
    signature = base64.b64encode(
        hmac.new(SECRET.encode(), BODY, hashlib.sha256).digest()
    ).decode()
    verify("shopify", SECRET, BODY, {"X-Shopify-Hmac-Sha256": signature})


def test_gitlab_token():
    verify("gitlab", SECRET, BODY, {"X-Gitlab-Token": SECRET})
    with pytest.raises(SignatureError):
        verify("gitlab", SECRET, BODY, {"X-Gitlab-Token": "wrong"})


def test_slack_signature_and_replay_window():
    timestamp = "1000"
    base = b"v0:" + timestamp.encode() + b":" + BODY
    signature = "v0=" + hmac.new(SECRET.encode(), base, hashlib.sha256).hexdigest()
    headers = {"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": signature}
    verify("slack", SECRET, BODY, headers, now=1100)
    with pytest.raises(SignatureError, match="stale"):
        verify("slack", SECRET, BODY, headers, now=1400)


def test_stripe_accepts_any_matching_v1_signature():
    timestamp = 1000
    signature = hmac.new(
        SECRET.encode(), f"{timestamp}.".encode() + BODY, hashlib.sha256
    ).hexdigest()
    verify(
        "stripe",
        SECRET,
        BODY,
        {"Stripe-Signature": f"t={timestamp},v1=bad,v1={signature}"},
        now=1100,
    )


def test_unknown_provider_fails_closed():
    with pytest.raises(SignatureError, match="unsupported"):
        verify("made-up", SECRET, BODY, {})
