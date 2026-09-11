"""Supervise the Webhook Relay CLI processes used for private delivery."""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class RelayMissing(RuntimeError):
    pass


@dataclass
class RelayProcess:
    bucket: str
    binary: str = "relay"
    max_retries: int = 20
    process: asyncio.subprocess.Process | None = None
    _stderr_task: asyncio.Task | None = None

    async def start(self) -> None:
        if not shutil.which(self.binary):
            raise RelayMissing(
                f"{self.binary!r} was not found; install it from "
                "https://webhookrelay.com/docs/installation/cli"
            )
        if self.process and self.process.returncode is None:
            return
        self.process = await asyncio.create_subprocess_exec(
            self.binary,
            "forward",
            "--bucket",
            self.bucket,
            "--no-interactive",
            "--max-retries",
            str(self.max_retries),
            "--retry-wait-min",
            "2s",
            "--retry-wait-max",
            "2m",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._stderr_task = asyncio.create_task(self._log_output())
        await asyncio.sleep(0)
        if self.process.returncode is not None:
            raise RuntimeError(f"relay process for bucket {self.bucket!r} exited immediately")

    async def _log_output(self) -> None:
        if not self.process:
            return
        streams = [self.process.stdout, self.process.stderr]

        async def drain(stream: asyncio.StreamReader | None) -> None:
            if stream is None:
                return
            while line := await stream.readline():
                logger.info(
                    "[webhookrelay:%s] %s", self.bucket, line.decode(errors="replace").rstrip()
                )

        await asyncio.gather(*(drain(stream) for stream in streams))

    async def stop(self) -> None:
        process = self.process
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        if self._stderr_task:
            await asyncio.gather(self._stderr_task, return_exceptions=True)
        self.process = None
        self._stderr_task = None


def unique_buckets(routes: dict) -> list[str]:
    return list(dict.fromkeys(route.bucket for route in routes.values()))
