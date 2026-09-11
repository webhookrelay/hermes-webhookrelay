"""Small stand-ins for the Hermes plugin API used by the unit tests."""

from __future__ import annotations

import asyncio
import json
import sys
import types
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

REGISTERED_PLATFORMS: set[str] = set()


class Platform(Enum):
    WEBHOOK = "webhook"

    @classmethod
    def _missing_(cls, value):
        if value not in REGISTERED_PLATFORMS:
            return None
        member = object.__new__(cls)
        member._name_ = str(value).upper()
        member._value_ = value
        cls._value2member_map_[value] = member
        return member


@dataclass
class PlatformConfig:
    enabled: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


class MessageType(Enum):
    TEXT = "text"


class ProcessingOutcome(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"


@dataclass
class SessionSource:
    platform: Any = None
    chat_id: str = ""
    chat_name: str | None = None
    chat_type: str = "dm"
    user_id: str | None = None
    user_name: str | None = None


@dataclass
class MessageEvent:
    text: str
    message_type: Any = MessageType.TEXT
    source: Any = None
    raw_message: Any = None
    message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BasePlatformAdapter:
    def __init__(self, config: PlatformConfig, platform: Any):
        self.config = config
        self.platform = platform
        self._connected = False
        self._background_tasks: set[asyncio.Task] = set()

    def _mark_connected(self):
        self._connected = True

    def _mark_disconnected(self):
        self._connected = False

    def build_source(self, chat_id: str, **kwargs):
        return SessionSource(platform=self.platform, chat_id=chat_id, **kwargs)

    async def handle_message(self, event: MessageEvent):
        async def run():
            callback = getattr(self, "run_agent", None)
            outcome = ProcessingOutcome.SUCCESS if callback is None else await callback(event)
            await self.on_processing_complete(event, outcome)

        task = asyncio.create_task(run())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def on_processing_complete(self, event, outcome):
        return None


class WebhookAdapter(BasePlatformAdapter):
    def __init__(self, config: PlatformConfig):
        super().__init__(config, Platform.WEBHOOK)
        self._routes = dict(config.extra.get("routes") or {})

    def _render_prompt(self, template, payload, event_type, route_name):
        return template or json.dumps(payload)


def install() -> None:
    gateway = types.ModuleType("gateway")
    gateway.__path__ = []
    config = types.ModuleType("gateway.config")
    config.Platform = Platform
    config.PlatformConfig = PlatformConfig
    platforms = types.ModuleType("gateway.platforms")
    platforms.__path__ = []
    base = types.ModuleType("gateway.platforms.base")
    base.MessageEvent = MessageEvent
    base.MessageType = MessageType
    base.ProcessingOutcome = ProcessingOutcome
    webhook = types.ModuleType("gateway.platforms.webhook")
    webhook.WebhookAdapter = WebhookAdapter
    sys.modules.update(
        {
            "gateway": gateway,
            "gateway.config": config,
            "gateway.platforms": platforms,
            "gateway.platforms.base": base,
            "gateway.platforms.webhook": webhook,
        }
    )
