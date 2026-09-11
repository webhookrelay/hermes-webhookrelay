import argparse
import subprocess

from webhookrelay_hermes import cli


def test_setup_works_with_relay_versions_before_no_interactive(monkeypatch):
    commands = []

    def fake_run(command):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="configured", stderr="")

    monkeypatch.setattr(cli, "_run", fake_run)
    args = argparse.Namespace(
        route="triage",
        bucket="hermes-triage",
        port=3580,
        path="/webhookrelay",
        timeout=30,
        relay_binary="relay",
        dry_run=False,
    )

    assert cli._setup(args) == 0
    assert "--no-agent" in commands[0]
    assert "--no-interactive" not in commands[0]


def test_setup_verifies_timeout_after_cli_response_decode_error(monkeypatch):
    calls = 0

    def fake_run(command):
        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(command, 0, stdout="configured", stderr="")
        if calls == 2:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="decode failed")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="http://127.0.0.1:3580/webhookrelay/triage\t1m\n",
            stderr="",
        )

    monkeypatch.setattr(cli, "_run", fake_run)
    args = argparse.Namespace(
        route="triage",
        bucket="hermes-triage",
        port=3580,
        path="/webhookrelay",
        timeout=30,
        relay_binary="relay",
        dry_run=False,
    )

    assert cli._setup(args) == 0


def test_duration_seconds_parses_go_duration_output():
    assert cli._duration_seconds("40s") == 40
    assert cli._duration_seconds("1m30s") == 90
    assert cli._duration_seconds("not-a-duration") is None
