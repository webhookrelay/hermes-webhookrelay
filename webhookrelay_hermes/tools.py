"""Agent-facing tools for inspecting the durable local inbox."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .constants import DEFAULT_STATE_PATH
from .ledger import RunLedger

TOOLSET = "webhookrelay"


def _ledger() -> RunLedger:
    return RunLedger(Path(DEFAULT_STATE_PATH))


def _guard(handler):
    def wrapped(args: dict | None = None, **_: Any) -> str:
        try:
            return handler(args or {})
        except Exception as exc:  # The model needs an actionable message, not a traceback.
            return f"Webhook Relay tool failed: {exc}"

    return wrapped


@_guard
def webhookrelay_queue_status(_args: dict) -> str:
    ledger = _ledger()
    try:
        return json.dumps(ledger.stats())
    finally:
        ledger.close()


@_guard
def webhookrelay_list_failed_events(args: dict) -> str:
    ledger = _ledger()
    try:
        return json.dumps(ledger.failures(int(args.get("limit") or 20)), indent=2)
    finally:
        ledger.close()


@_guard
def webhookrelay_get_event(args: dict) -> str:
    event_id = str(args.get("event_id") or "")
    ledger = _ledger()
    try:
        event = ledger.get(event_id)
    finally:
        ledger.close()
    return json.dumps(event, indent=2) if event else f"Unknown event: {event_id}"


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


SCHEMAS = {
    "webhookrelay_queue_status": _schema(
        "webhookrelay_queue_status",
        "Count local Webhook Relay-triggered Hermes runs by outcome.",
        {},
        [],
    ),
    "webhookrelay_list_failed_events": _schema(
        "webhookrelay_list_failed_events",
        "List recent webhook events whose Hermes runs failed or exhausted retries.",
        {"limit": {"type": "integer", "description": "Maximum rows, default 20."}},
        [],
    ),
    "webhookrelay_get_event": _schema(
        "webhookrelay_get_event",
        "Get one local run record and its original webhook payload.",
        {"event_id": {"type": "string", "description": "Event identifier from the ledger."}},
        ["event_id"],
    ),
}

HANDLERS = {
    "webhookrelay_queue_status": webhookrelay_queue_status,
    "webhookrelay_list_failed_events": webhookrelay_list_failed_events,
    "webhookrelay_get_event": webhookrelay_get_event,
}


def register_tools(ctx: Any) -> None:
    for name, schema in SCHEMAS.items():
        ctx.register_tool(
            name=name,
            toolset=TOOLSET,
            schema=schema,
            handler=HANDLERS[name],
            description=schema["function"]["description"],
            emoji="📨",
        )
