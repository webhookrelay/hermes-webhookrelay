"""Validated adapter settings with deliberately conservative defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .constants import (
    DEFAULT_HOST,
    DEFAULT_MAX_BODY_BYTES,
    DEFAULT_MAX_CONCURRENT,
    DEFAULT_PATH,
    DEFAULT_PORT,
    DEFAULT_RETRY_AFTER_SECONDS,
    DEFAULT_RUN_TIMEOUT_SECONDS,
    DEFAULT_STATE_PATH,
    PATH_ENV,
    PORT_ENV,
)


@dataclass(frozen=True)
class Route:
    name: str
    bucket: str
    prompt: str = ""
    events: tuple[str, ...] = ()
    event_path: str = ""
    id_path: str = ""
    provider: str = "generic"
    secret_env: str = ""
    insecure_no_auth: bool = False
    skills: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def from_dict(cls, name: str, value: dict[str, Any]) -> Route:
        return cls(
            name=name,
            bucket=str(value.get("bucket") or f"hermes-{name}"),
            prompt=str(value.get("prompt") or ""),
            events=tuple(str(x) for x in value.get("events") or ()),
            event_path=str(value.get("event_path") or ""),
            id_path=str(value.get("id_path") or ""),
            provider=str(value.get("provider") or "generic").lower(),
            secret_env=str(value.get("secret_env") or ""),
            insecure_no_auth=bool(value.get("insecure_no_auth", False)),
            skills=tuple(str(x) for x in value.get("skills") or ()),
            raw=dict(value),
        )

    def validate(self) -> None:
        if not self.name or "/" in self.name:
            raise ValueError(f"invalid route name: {self.name!r}")
        if not self.bucket:
            raise ValueError(f"route {self.name!r} needs a bucket")
        if not self.insecure_no_auth and not self.secret_env:
            raise ValueError(
                f"route {self.name!r} must set secret_env or explicitly set "
                "insecure_no_auth: true"
            )
        if self.secret_env and not os.getenv(self.secret_env):
            raise ValueError(
                f"route {self.name!r} needs environment variable {self.secret_env}"
            )


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    path: str
    state_path: Path
    max_body_bytes: int
    max_concurrent: int
    run_timeout_seconds: float
    retry_after_seconds: int
    auto_start_relay: bool
    relay_binary: str
    routes: dict[str, Route]

    @classmethod
    def from_extra(cls, extra: dict[str, Any] | None) -> Settings:
        extra = dict(extra or {})
        routes = {
            str(name): Route.from_dict(str(name), dict(value or {}))
            for name, value in dict(extra.get("routes") or {}).items()
        }
        path = str(extra.get("path") or os.getenv(PATH_ENV) or DEFAULT_PATH)
        if not path.startswith("/"):
            path = "/" + path
        return cls(
            host=str(extra.get("host") or DEFAULT_HOST),
            port=int(extra.get("port") or os.getenv(PORT_ENV) or DEFAULT_PORT),
            path=path.rstrip("/") or DEFAULT_PATH,
            state_path=Path(str(extra.get("state_path") or DEFAULT_STATE_PATH)).expanduser(),
            max_body_bytes=int(extra.get("max_body_bytes") or DEFAULT_MAX_BODY_BYTES),
            max_concurrent=int(extra.get("max_concurrent") or DEFAULT_MAX_CONCURRENT),
            run_timeout_seconds=float(
                extra.get("run_timeout_seconds") or DEFAULT_RUN_TIMEOUT_SECONDS
            ),
            retry_after_seconds=int(
                extra.get("retry_after_seconds") or DEFAULT_RETRY_AFTER_SECONDS
            ),
            auto_start_relay=bool(extra.get("auto_start_relay", True)),
            relay_binary=str(extra.get("relay_binary") or "relay"),
            routes=routes,
        )

    def validate(self) -> None:
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if self.max_concurrent < 1:
            raise ValueError("max_concurrent must be at least 1")
        if self.run_timeout_seconds <= 0:
            raise ValueError("run_timeout_seconds must be positive")
        if not self.routes:
            raise ValueError("at least one route is required")
        buckets: set[str] = set()
        for route in self.routes.values():
            route.validate()
            if route.bucket in buckets:
                raise ValueError(
                    f"bucket {route.bucket!r} is used by more than one route; "
                    "use one bucket per route to avoid fan-out into the wrong agent task"
                )
            buckets.add(route.bucket)
