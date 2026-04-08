"""
env.py — OpenEnv client wrapper for sql-debug-env.

Provides SqlDebugEnv and SqlDebugAction that the inference script imports.
Supports two connection modes:
  1. from_docker_image(image_name) — spin up Docker container, connect to it
  2. from_url(base_url)           — connect to an already-running server (HF Space)

Both modes expose the same async API:
  await env.reset()          → ResetResult
  await env.step(action)     → StepResult
  await env.close()          → None
  await env.state()          → StateResponse
"""

import asyncio
import subprocess
import time
from typing import Any, Dict, Optional

import httpx
from pydantic import BaseModel

from models import ResetResult, SqlAction, SqlObservation, StateResponse, StepResult

# Re-export for convenience so inference.py can do:
#   from env import SqlDebugEnv, SqlDebugAction
SqlDebugAction = SqlAction


class SqlDebugEnv:
    """Async client for the sql-debug-env FastAPI server."""

    def __init__(self, base_url: str, session_id: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.session_id: Optional[str] = session_id
        self._client: Optional[httpx.AsyncClient] = None
        self._container_proc: Optional[subprocess.Popen] = None

    # ── Factory methods ──────────────────────────────────────────────────────

    @classmethod
    async def from_url(cls, base_url: str) -> "SqlDebugEnv":
        """Connect to a running server at base_url."""
        env = cls(base_url)
        env._client = httpx.AsyncClient(base_url=base_url, timeout=60.0)
        return env

    @classmethod
    async def from_docker_image(cls, image_name: str, port: int = 7860) -> "SqlDebugEnv":
        """
        Spin up a Docker container from image_name and connect to it.
        The container must expose port 7860.
        """
        import random as _random
        host_port = port + _random.randint(0, 999)

        proc = subprocess.Popen(
            ["docker", "run", "--rm", "-p", f"{host_port}:7860", image_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        base_url = f"http://localhost:{host_port}"
        env = cls(base_url)
        env._container_proc = proc
        env._client = httpx.AsyncClient(base_url=base_url, timeout=60.0)

        # Wait for server to become ready (up to 30 s)
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                r = await env._client.get("/health")
                if r.status_code == 200:
                    break
            except Exception:
                pass
            await asyncio.sleep(1.0)
        else:
            proc.terminate()
            raise RuntimeError(
                f"Server at {base_url} did not become ready within 30 seconds."
            )

        return env

    # ── Core API ─────────────────────────────────────────────────────────────

    async def reset(
        self,
        task_name: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> ResetResult:
        """Reset the environment and return the initial observation."""
        body: Dict[str, Any] = {}
        if task_name:
            body["task_name"] = task_name
        if seed is not None:
            body["seed"] = seed

        resp = await self._client.post("/reset", json=body)
        resp.raise_for_status()
        data = resp.json()
        result = ResetResult(**data)
        self.session_id = data.get("info", {}).get("session_id")
        return result

    async def step(self, action: SqlDebugAction) -> StepResult:
        """Submit an action and advance the episode."""
        body: Dict[str, Any] = {"content": action.content}
        if self.session_id:
            body["session_id"] = self.session_id

        resp = await self._client.post("/step", json=body)
        resp.raise_for_status()
        return StepResult(**resp.json())

    async def state(self) -> StateResponse:
        """Return current environment state."""
        params = {}
        if self.session_id:
            params["session_id"] = self.session_id
        resp = await self._client.get("/state", params=params)
        resp.raise_for_status()
        return StateResponse(**resp.json())

    async def close(self) -> None:
        """Clean up HTTP client and container if running."""
        if self._client:
            await self._client.aclose()
            self._client = None
        if self._container_proc:
            self._container_proc.terminate()
            try:
                self._container_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._container_proc.kill()
            self._container_proc = None
