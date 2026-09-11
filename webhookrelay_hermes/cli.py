"""Operator commands registered under ``hermes webhookrelay``."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from .constants import (
    DEFAULT_PATH,
    DEFAULT_PORT,
    DEFAULT_RUN_TIMEOUT_SECONDS,
    DEFAULT_STATE_PATH,
)
from .ledger import RunLedger


def register_cli(parser: argparse.ArgumentParser) -> None:
    commands = parser.add_subparsers(dest="webhookrelay_action")
    setup = commands.add_parser("setup", help="Create/update a Webhook Relay route")
    setup.add_argument("route")
    setup.add_argument("--bucket", default="")
    setup.add_argument("--port", type=int, default=DEFAULT_PORT)
    setup.add_argument("--path", default=DEFAULT_PATH)
    setup.add_argument("--timeout", type=int, default=DEFAULT_RUN_TIMEOUT_SECONDS)
    setup.add_argument("--relay-binary", default="relay")
    setup.add_argument("--dry-run", action="store_true")
    status = commands.add_parser("status", help="Show local run outcomes")
    status.add_argument("--state-path", default=DEFAULT_STATE_PATH)
    status.add_argument("--limit", type=int, default=10)
    doctor = commands.add_parser("doctor", help="Check CLI credentials and local state")
    doctor.add_argument("--relay-binary", default="relay")
    doctor.add_argument("--state-path", default=DEFAULT_STATE_PATH)
    retry = commands.add_parser("retry", help="Allow a failed event to run again")
    retry.add_argument("event_id")
    retry.add_argument("--state-path", default=DEFAULT_STATE_PATH)


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=30)


def _setup(args: argparse.Namespace) -> int:
    route = args.route.strip()
    if not route or "/" in route:
        print("Route must be one URL-safe path segment")
        return 2
    bucket = args.bucket or f"hermes-{route}"
    path = "/" + args.path.strip("/")
    destination = f"http://127.0.0.1:{args.port}{path}/{route}"
    command = [
        args.relay_binary,
        "forward",
        "--bucket",
        bucket,
        destination,
        "--no-agent",
        "--no-interactive",
    ]
    if args.dry_run:
        print(" ".join(command))
        return 0
    result = _run(command)
    if result.returncode:
        print(result.stderr.strip() or result.stdout.strip())
        return result.returncode
    # `forward` names the output after its destination. Raise its response
    # timeout so the internal delivery can wait for a real agent outcome.
    update = _run(
        [
            args.relay_binary,
            "output",
            "update",
            destination,
            "--bucket",
            bucket,
            "--destination",
            destination,
            "--type",
            "internal",
            "--timeout",
            str(args.timeout + 30),
        ]
    )
    print(result.stdout.strip())
    if update.returncode:
        print("Warning: route exists, but its output timeout could not be updated:")
        print(update.stderr.strip() or update.stdout.strip())
        return update.returncode
    print(
        f"Configured Hermes route {route!r} on bucket {bucket!r} "
        f"(agent timeout {args.timeout}s)."
    )
    return 0


def _status(args: argparse.Namespace) -> int:
    ledger = RunLedger(Path(args.state_path))
    try:
        print(
            json.dumps(
                {"counts": ledger.stats(), "failures": ledger.failures(args.limit)}, indent=2
            )
        )
    finally:
        ledger.close()
    return 0


def _doctor(args: argparse.Namespace) -> int:
    ok = True
    binary = shutil.which(args.relay_binary)
    print(f"[{'ok' if binary else 'fail'}] relay CLI: {binary or 'not found'}")
    ok &= bool(binary)
    credentials = bool(os.getenv("RELAY_KEY") and os.getenv("RELAY_SECRET"))
    if binary and not credentials:
        probe = _run([args.relay_binary, "bucket", "ls"])
        credentials = probe.returncode == 0
    print(f"[{'ok' if credentials else 'fail'}] Webhook Relay credentials")
    ok &= credentials
    try:
        ledger = RunLedger(Path(args.state_path))
        ledger.close()
        print(f"[ok] state database: {Path(args.state_path).expanduser()}")
    except OSError as exc:
        print(f"[fail] state database: {exc}")
        ok = False
    return 0 if ok else 1


def _retry(args: argparse.Namespace) -> int:
    ledger = RunLedger(Path(args.state_path))
    try:
        reset = ledger.reset(args.event_id)
    finally:
        ledger.close()
    if not reset:
        print(f"Unknown event: {args.event_id}")
        return 1
    print(
        "Local attempt counter reset. Replay the original webhook from the Webhook Relay "
        "dashboard or retry its log to deliver it again."
    )
    return 0


def webhookrelay_command(args: argparse.Namespace) -> int:
    action = getattr(args, "webhookrelay_action", None)
    if action == "setup":
        return _setup(args)
    if action == "status":
        return _status(args)
    if action == "doctor":
        return _doctor(args)
    if action == "retry":
        return _retry(args)
    print("Usage: hermes webhookrelay {setup|status|doctor|retry}")
    return 2
