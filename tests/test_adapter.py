import asyncio
import hashlib
import hmac

from aiohttp.test_utils import TestClient, TestServer

from tests.hermes_stub import PlatformConfig, ProcessingOutcome
from webhookrelay_hermes.adapter import WebhookRelayAdapter
from webhookrelay_hermes.ledger import RunLedger


async def _client(adapter):
    return TestClient(TestServer(adapter.build_app()))


async def test_delivery_waits_for_success_and_deduplicates(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_HOOK_SECRET", "secret")
    adapter = WebhookRelayAdapter(
        PlatformConfig(
            extra={
                "state_path": str(tmp_path / "state.db"),
                "routes": {
                    "github": {
                        "provider": "github",
                        "secret_env": "TEST_HOOK_SECRET",
                        "events": ["push"],
                    }
                },
            }
        )
    )
    adapter._ledger = RunLedger(tmp_path / "state.db")
    seen = []

    async def run(event):
        seen.append(event)
        return ProcessingOutcome.SUCCESS

    adapter.run_agent = run
    client = await _client(adapter)
    await client.start_server()
    body = b'{"ref":"main"}'
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": "delivery-1",
    }
    response = await client.post("/webhookrelay/github", data=body, headers=headers)
    assert response.status == 200
    assert (await response.json())["status"] == "processed"
    duplicate = await client.post("/webhookrelay/github", data=body, headers=headers)
    assert duplicate.status == 200
    assert (await duplicate.json())["status"] == "already_succeeded"
    assert len(seen) == 1
    assert "<untrusted_webhook_payload>" in seen[0].text
    await client.close()
    adapter._ledger.close()


async def test_long_run_is_not_retried_while_still_active(tmp_path):
    adapter = WebhookRelayAdapter(
        PlatformConfig(
            extra={
                "state_path": str(tmp_path / "state.db"),
                "run_timeout_seconds": 0.01,
                "routes": {"slow": {"insecure_no_auth": True}},
            }
        )
    )
    adapter._ledger = RunLedger(tmp_path / "state.db")

    async def run(_event):
        await asyncio.sleep(0.03)
        return ProcessingOutcome.SUCCESS

    adapter.run_agent = run
    client = await _client(adapter)
    await client.start_server()
    response = await client.post("/webhookrelay/slow", json={"id": 1})
    assert response.status == 202
    assert adapter._ledger.stats() == {"running": 1}
    await asyncio.sleep(0.04)
    assert adapter._ledger.stats() == {"succeeded": 1}
    await client.close()
    adapter._ledger.close()


async def test_failed_run_returns_retryable_status(tmp_path):
    adapter = WebhookRelayAdapter(
        PlatformConfig(
            extra={
                "state_path": str(tmp_path / "state.db"),
                "routes": {"dev": {"insecure_no_auth": True}},
            }
        )
    )
    adapter._ledger = RunLedger(tmp_path / "state.db")

    async def run(_event):
        return ProcessingOutcome.FAILURE

    adapter.run_agent = run
    client = await _client(adapter)
    await client.start_server()
    response = await client.post("/webhookrelay/dev", json={"id": 1})
    assert response.status == 500
    assert adapter._ledger.stats() == {"failed": 1}
    await client.close()
    adapter._ledger.close()


async def test_bad_signature_is_rejected_before_agent_run(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_HOOK_SECRET", "secret")
    adapter = WebhookRelayAdapter(
        PlatformConfig(
            extra={
                "state_path": str(tmp_path / "state.db"),
                "routes": {"github": {"provider": "github", "secret_env": "TEST_HOOK_SECRET"}},
            }
        )
    )
    adapter._ledger = RunLedger(tmp_path / "state.db")
    client = await _client(adapter)
    await client.start_server()
    response = await client.post(
        "/webhookrelay/github",
        data=b"{}",
        headers={"X-Hub-Signature-256": "sha256=wrong"},
    )
    assert response.status == 401
    assert adapter._ledger.stats() == {}
    await client.close()
    adapter._ledger.close()
