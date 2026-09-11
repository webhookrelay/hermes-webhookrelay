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
