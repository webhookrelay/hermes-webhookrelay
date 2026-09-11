"""Webhook Relay ingress adapter for Hermes Agent."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

try:
    from aiohttp import web

    AIOHTTP_AVAILABLE = True
except ImportError:  # pragma: no cover
    web = None  # type: ignore[assignment]
    AIOHTTP_AVAILABLE = False

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import MessageEvent, MessageType, ProcessingOutcome
from gateway.platforms.webhook import WebhookAdapter

from .config import Settings
from .constants import KEY_ENV, PATH_ENV, PLATFORM_NAME, PORT_ENV, SECRET_ENV
from .ledger import RunLedger
from .relay import RelayProcess, unique_buckets
from .routing import event_id, event_type, render_prompt
from .security import SignatureError, verify

logger = logging.getLogger(__name__)


class WebhookRelayAdapter(WebhookAdapter):
    """Waits for the real agent outcome before acknowledging local delivery."""

    interactive_resume = False

    def __init__(self, config: PlatformConfig):
        super().__init__(config)
        try:
            self.platform = Platform(PLATFORM_NAME)
        except ValueError as exc:
            raise RuntimeError(f"Platform {PLATFORM_NAME!r} is not registered") from exc
        self.settings = Settings.from_extra(getattr(config, "extra", None))
        self._host = self.settings.host
        self._port = self.settings.port
        self._path = self.settings.path
        self._routes = {name: route.raw for name, route in self.settings.routes.items()}
        self._max_body_bytes = self.settings.max_body_bytes
        self._ledger: RunLedger | None = None
        self._site_runner: Any = None
        self._relay_processes: list[RelayProcess] = []
        self._slots = asyncio.Semaphore(self.settings.max_concurrent)
        self._waiters: dict[str, asyncio.Future] = {}
        self._event_ids: dict[str, str] = {}

    @property
    def authorization_is_upstream(self) -> bool:
        return all(not route.insecure_no_auth for route in self.settings.routes.values())

    def build_app(self) -> web.Application:
        app = web.Application(client_max_size=self.settings.max_body_bytes)
        app.router.add_get(f"{self.settings.path}/health", self._health)
        app.router.add_post(f"{self.settings.path}/{{route}}", self._delivery)
        app.router.add_post(f"{self.settings.path}/{{route}}/{{tail:.*}}", self._delivery)
        return app

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        del is_reconnect
        self.settings.validate()
        self._ledger = RunLedger(self.settings.state_path)
        self._site_runner = web.AppRunner(self.build_app())
        await self._site_runner.setup()
        try:
            await web.TCPSite(self._site_runner, self.settings.host, self.settings.port).start()
            if self.settings.auto_start_relay:
                for bucket in unique_buckets(self.settings.routes):
                    process = RelayProcess(bucket=bucket, binary=self.settings.relay_binary)
                    await process.start()
                    self._relay_processes.append(process)
        except Exception:
            logger.exception("[webhookrelay] failed to start")
            await self.disconnect()
            return False
        self._mark_connected()
        logger.info(
            "[webhookrelay] listening on http://%s:%d%s for routes %s",
            self.settings.host,
            self.settings.port,
            self.settings.path,
            ", ".join(self.settings.routes),
        )
        return True

    async def disconnect(self) -> None:
        for process in self._relay_processes:
            await process.stop()
        self._relay_processes = []
        if self._site_runner is not None:
            await self._site_runner.cleanup()
            self._site_runner = None
        if self._ledger is not None:
            self._ledger.close()
            self._ledger = None
        self._mark_disconnected()

    async def _health(self, _request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "ok",
                "platform": PLATFORM_NAME,
                "routes": sorted(self.settings.routes),
                "in_flight": len(self._waiters),
            }
        )

    async def _delivery(self, request: web.Request) -> web.Response:
        route_name = request.match_info.get("route", "")
        route = self.settings.routes.get(route_name)
        if route is None:
            return web.json_response({"error": "unknown route"}, status=404)
        if self._slots.locked():
            return web.json_response(
                {"status": "deferred", "reason": "max_concurrent"},
                status=503,
                headers={"Retry-After": str(self.settings.retry_after_seconds)},
            )

        raw = await request.read()
        headers = dict(request.headers.items())
        if not route.insecure_no_auth:
            secret = os.getenv(route.secret_env, "")
            try:
                verify(route.provider, secret, raw, headers)
            except SignatureError as exc:
                logger.warning("[webhookrelay] rejected route=%s: %s", route_name, exc)
                return web.json_response({"error": "signature verification failed"}, status=401)

        try:
            payload: Any = json.loads(raw) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {"raw": raw.decode("utf-8", errors="replace")}
        kind = event_type(payload, route, headers)
        if route.events and kind not in route.events:
            return web.json_response({"status": "ignored", "event": kind})
        identifier = event_id(payload, route, headers, raw)

        assert self._ledger is not None
        admission = self._ledger.admit(
            identifier,
            route=route_name,
            event_type=kind,
            payload=payload,
            stale_after=self.settings.run_timeout_seconds * 1.5,
        )
        if not admission.admitted:
            if admission.reason in {"already_succeeded", "attempts_exhausted"}:
                status = 200 if admission.reason == "already_succeeded" else 422
                return web.json_response(
                    {"status": admission.reason, "event_id": identifier}, status=status
                )
            return web.json_response(
                {"status": "deferred", "reason": admission.reason, "event_id": identifier},
                status=503,
                headers={"Retry-After": str(self.settings.retry_after_seconds)},
            )

        async with self._slots:
            return await self._dispatch(
                route_name, route, kind, identifier, payload, admission.attempts
            )

    async def _dispatch(self, route_name, route, kind, identifier, payload, attempts):
        chat_id = f"webhookrelay:{identifier}:{attempts}"
        event = MessageEvent(
            text=render_prompt(route, payload, kind),
            message_type=MessageType.TEXT,
            source=self.build_source(
                chat_id=chat_id,
                chat_name=f"webhookrelay/{route_name}",
                chat_type="webhook",
                user_id=f"webhookrelay:{route_name}",
                user_name=route_name,
            ),
            raw_message=payload,
            message_id=identifier,
            metadata={
                "webhookrelay_event_id": identifier,
                "webhookrelay_route": route_name,
                "webhookrelay_event_type": kind,
                "webhookrelay_attempt": attempts,
            },
        )
        waiter = asyncio.get_running_loop().create_future()
        self._waiters[chat_id] = waiter
        self._event_ids[chat_id] = identifier
        task = asyncio.create_task(self.handle_message(event))
        task.add_done_callback(lambda completed: self._dispatch_done(chat_id, completed))
        try:
            outcome = await asyncio.wait_for(
                asyncio.shield(waiter), timeout=self.settings.run_timeout_seconds
            )
        except asyncio.TimeoutError:
            # The agent is still running. Retrying now could execute its side
            # effects twice, so acknowledge the delivery and let the eventual
            # completion hook record success/failure for operator follow-up.
            return web.json_response(
                {
                    "status": "accepted",
                    "reason": "agent still running",
                    "event_id": identifier,
                },
                status=202,
            )
        finally:
            self._waiters.pop(chat_id, None)

        success = outcome == ProcessingOutcome.SUCCESS
        if success:
            return web.json_response(
                {"status": "processed", "event_id": identifier, "route": route_name}
            )
        return web.json_response(
            {"status": "failed", "event_id": identifier, "outcome": str(outcome)}, status=500
        )

    def _dispatch_done(self, chat_id: str, task: asyncio.Task) -> None:
        if task.cancelled():
            error: BaseException | None = asyncio.CancelledError()
        else:
            error = task.exception()
        waiter = self._waiters.get(chat_id)
        if error is not None and waiter is not None and not waiter.done():
            logger.error("[webhookrelay] message dispatch failed", exc_info=error)
            event_id = self._event_ids.pop(chat_id, "")
            if event_id and self._ledger is not None:
                self._ledger.finish(event_id, success=False, error=str(error))
            waiter.set_result(ProcessingOutcome.FAILURE)

    async def on_processing_complete(self, event: MessageEvent, outcome: Any) -> None:
        chat_id = getattr(getattr(event, "source", None), "chat_id", "") or ""
        event_id = self._event_ids.pop(chat_id, "")
        if event_id and self._ledger is not None:
            success = outcome == ProcessingOutcome.SUCCESS
            self._ledger.finish(
                event_id, success=success, error="" if success else str(outcome)
            )
        waiter = self._waiters.get(chat_id)
        if waiter is not None and not waiter.done():
            waiter.set_result(outcome)
        try:
            await super().on_processing_complete(event, outcome)
        except Exception:
            logger.debug("[webhookrelay] base completion hook failed", exc_info=True)


def check_requirements() -> bool:
    from importlib.util import find_spec

    return AIOHTTP_AVAILABLE and find_spec("aiohttp") is not None


def validate_config(config: PlatformConfig) -> bool:
    try:
        Settings.from_extra(getattr(config, "extra", None)).validate()
        return True
    except (TypeError, ValueError):
        return False


def is_connected(config: PlatformConfig) -> bool:
    return validate_config(config)


def env_enablement() -> dict | None:
    if not (os.getenv(KEY_ENV) and os.getenv(SECRET_ENV)):
        return None
    seeded: dict[str, Any] = {}
    if os.getenv(PORT_ENV):
        try:
            seeded["port"] = int(os.environ[PORT_ENV])
        except ValueError:
            pass
    if os.getenv(PATH_ENV):
        seeded["path"] = os.environ[PATH_ENV]
    return seeded
