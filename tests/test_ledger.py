from webhookrelay_hermes.ledger import RunLedger


def test_success_is_deduplicated(tmp_path):
    ledger = RunLedger(tmp_path / "state.db")
    first = ledger.admit(
        "evt", route="r", event_type="push", payload={"x": 1}, stale_after=10, now=100
    )
    assert first.admitted
    ledger.finish("evt", success=True)
    duplicate = ledger.admit(
        "evt", route="r", event_type="push", payload={"x": 1}, stale_after=10, now=200
    )
    assert not duplicate.admitted
    assert duplicate.reason == "already_succeeded"
    ledger.close()


def test_failure_and_stale_run_can_retry(tmp_path):
    ledger = RunLedger(tmp_path / "state.db")
    ledger.admit("failed", route="r", event_type="x", payload={}, stale_after=10, now=100)
    ledger.finish("failed", success=False, error="boom")
    retry = ledger.admit(
        "failed", route="r", event_type="x", payload={}, stale_after=10, now=101
    )
    assert retry.admitted and retry.attempts == 2
    ledger.admit("stale", route="r", event_type="x", payload={}, stale_after=10, now=100)
    assert not ledger.admit(
        "stale", route="r", event_type="x", payload={}, stale_after=10, now=105
    ).admitted
    assert ledger.admit(
        "stale", route="r", event_type="x", payload={}, stale_after=10, now=111
    ).admitted
    ledger.close()


def test_stats_failures_and_reset(tmp_path):
    ledger = RunLedger(tmp_path / "state.db")
    ledger.admit("evt", route="r", event_type="x", payload={"id": 1}, stale_after=1)
    ledger.finish("evt", success=False, error="nope")
    assert ledger.stats() == {"failed": 1}
    assert ledger.failures()[0]["event_id"] == "evt"
    assert ledger.get("evt")["payload"] == {"id": 1}
    assert ledger.reset("evt")
    ledger.close()
