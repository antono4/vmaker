"""Adapter for the MiniMax Open Platform API.

Endpoints, taken from the official scripts shipped with the model
(``upstream/scripts/full-2k-*.sh``):

    POST {base}/v2/h3_context_ir              -> {"task_id": "..."}   (prompt expansion)
    POST {base}/v2/video_generation           -> {"task_id": "..."}
    POST {base}/v2/video_regeneration         -> {"task_id": "..."}   (768p -> 2K)
    GET  {base}/v2/query/video_generation/{id} -> {"task": {"status": ..., "content": {...}}}

``base`` is ``https://api.minimax.io`` (global) or ``https://api.minimaxi.com``
(CN). Requests are authenticated with ``Authorization: Bearer <token>``.

Local files cannot be uploaded through this API, so reference inputs are only
forwarded when they already have a public URL.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path

import httpx

from .. import config, media
from .base import BackendError, GenerationRequest, GenerationResult, ProgressFn

POLL_INTERVAL = 5.0
DONE_STATES = ("success", "succeeded", "completed", "successed")
FAILED_STATES = ("fail", "failed", "error", "canceled", "cancelled")


class MiniMaxAPIBackend:
    name = "api"
    label = "MiniMax Open Platform API"
    description = (
        "Calls the hosted MiniMax-H3 API. No GPU needed, but it needs an API "
        "key and the reference inputs must be publicly reachable URLs."
    )

    def __init__(self) -> None:
        self.base_url = config.MINIMAX_API_BASE.rstrip("/")
        # A key typed into the UI lives only here, in memory. It is never
        # written to disk or returned by the API; a restart falls back to
        # MINIMAX_API_KEY from the environment.
        self._runtime_key = ""

    @property
    def api_key(self) -> str:
        return self._runtime_key or config.MINIMAX_API_KEY

    @property
    def key_source(self) -> str:
        if self._runtime_key:
            return "session"
        if config.MINIMAX_API_KEY:
            return "environment"
        return ""

    def set_key(self, key: str, base: str = "") -> None:
        self._runtime_key = (key or "").strip()
        if base.strip():
            self.base_url = base.strip().rstrip("/")

    def clear_key(self) -> None:
        self._runtime_key = ""

    def available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "No API key. Paste one below, or set MINIMAX_API_KEY."
        return True, f"Key from {self.key_source}, endpoint {self.base_url}."

    def info(self) -> dict:
        ok, reason = self.available()
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "available": ok,
            "reason": reason,
            "key_source": self.key_source,
            "accepts_key": True,
            "endpoints": {
                "video_generation": f"{self.base_url}/v2/video_generation",
                "video_regeneration": f"{self.base_url}/v2/video_regeneration",
                "h3_context_ir": f"{self.base_url}/v2/h3_context_ir",
                "query": f"{self.base_url}/v2/query/video_generation/{{task_id}}",
            },
            "requires": ["MINIMAX_API_KEY", "public URLs for reference inputs"],
        }

    # -- internals --------------------------------------------------------
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _content_items(self, request: GenerationRequest) -> list[dict]:
        items: list[dict] = [{"type": "text", "text": request.prompt}]
        for ref in request.references:
            uri = (ref.get("uri") or "").strip()
            if not uri.startswith(("http://", "https://")):
                continue
            kind = ref.get("kind")
            if kind == "image":
                items.append({"type": "image_url", "image_url": {"url": uri},
                              "role": "reference"})
            elif kind == "video":
                items.append({"type": "video_url", "video_url": {"url": uri},
                              "role": "reference"})
            elif kind == "audio":
                items.append({"type": "audio_url", "audio_url": {"url": uri},
                              "role": "reference"})
        return items

    def _poll(self, client: httpx.Client, task_id: str, progress: ProgressFn) -> dict:
        deadline = time.time() + config.READ_TIMEOUT
        while True:
            if time.time() > deadline:
                raise BackendError(
                    f"Timed out after {config.READ_TIMEOUT:.0f}s waiting for task {task_id}."
                )
            time.sleep(POLL_INTERVAL)
            response = client.get(
                f"{self.base_url}/v2/query/video_generation/{task_id}",
                headers=self._headers(),
            )
            if response.status_code >= 400:
                raise BackendError(
                    f"Query failed (HTTP {response.status_code}): {response.text[:300]}"
                )
            body = response.json()
            task = body.get("task") or {}
            status = str(task.get("status", "")).lower()
            progress(_progress_for(status), f"MiniMax API: {status or 'unknown'}")
            if status in DONE_STATES:
                return task
            if status in FAILED_STATES:
                raise BackendError(
                    f"MiniMax API task {task_id} ended as '{status}': "
                    f"{task.get('message') or task}"
                )

    def _submit(self, client: httpx.Client, path: str, payload: dict) -> str:
        response = client.post(
            f"{self.base_url}{path}", headers=self._headers(), json=payload
        )
        if response.status_code >= 400:
            raise BackendError(
                f"MiniMax API rejected the request (HTTP {response.status_code}): "
                f"{response.text[:400]}",
                hint="Check MINIMAX_API_KEY, the selected region, and that the "
                     "account has MiniMax-H3 access.",
            )
        body = response.json()
        task_id = body.get("task_id") or (body.get("task") or {}).get("id") or body.get("id")
        if not task_id:
            raise BackendError(f"MiniMax API did not return a task id: {body}")
        return str(task_id)

    # -- generation -------------------------------------------------------
    def generate(
        self, job_id: str, request: GenerationRequest, progress: ProgressFn
    ) -> GenerationResult:
        ok, reason = self.available()
        if not ok:
            raise BackendError(reason, hint="Set MINIMAX_API_KEY and restart the app.")

        payload: dict = {
            "model": config.VIDEO_MODEL,
            "content": self._content_items(request),
            "resolution": request.resolution.upper() if request.resolution == "2k" else "768P",
            "duration": int(request.duration),
            "ratio": request.aspect_ratio,
        }
        if request.seed:
            payload["seed"] = request.seed

        try:
            with httpx.Client(
                timeout=httpx.Timeout(config.READ_TIMEOUT, connect=config.CONNECT_TIMEOUT)
            ) as client:
                progress(0.05, "submitting to MiniMax API")
                task_id = self._submit(client, "/v2/video_generation", payload)

                if request.resolution == "2k":
                    progress(0.5, "requesting 2K regeneration")
                    task = self._poll(client, task_id, progress)
                    url = ((task.get("content") or {}).get("url")
                           or (task.get("content") or {}).get("video_url") or "")
                    if not url:
                        raise BackendError(
                            f"MiniMax API returned no video URL: {task}"
                        )
                    progress(0.9, "downloading 2K video")
                    content = client.get(url)
                    content.raise_for_status()
                    video_path = config.OUTPUT_DIR / f"{job_id}.mp4"
                    video_path.write_bytes(content.content)
                    return GenerationResult(
                        video_path=str(video_path),
                        remote_id=task_id,
                        video_url=url,
                        meta={"endpoint": self.base_url, "resolution": "2K"},
                    )

                task = self._poll(client, task_id, progress)
                content = task.get("content") or {}
                base_url = content.get("url") or content.get("video_url") or ""
                if not base_url:
                    raise BackendError(f"MiniMax API returned no video URL: {task}")

                progress(0.75, "downloading 768p video")
                base_bytes = client.get(base_url).content
                base_path = config.OUTPUT_DIR / f"{job_id}.base.mp4"
                base_path.write_bytes(base_bytes)

                progress(0.9, "downloading video")
                final = client.get(base_url)
                final.raise_for_status()
                video_path = config.OUTPUT_DIR / f"{job_id}.mp4"
                video_path.write_bytes(final.content)

                meta = {"endpoint": self.base_url, "resolution": "768P"}
                result = GenerationResult(
                    video_path=str(video_path),
                    remote_id=task_id,
                    video_url=base_url,
                    meta=meta,
                )
                return result
        except BackendError:
            raise
        except httpx.HTTPError as exc:
            raise BackendError(
                f"Could not reach the MiniMax API at {self.base_url}: {exc}",
                hint="Check network access and MINIMAX_API_BASE.",
            ) from exc

    # -- optional prompt expansion ---------------------------------------
    def expand_prompt(self, text: str, duration: float, ratio: str) -> str:
        ok, reason = self.available()
        if not ok:
            raise BackendError(reason)
        payload = {
            "model": config.VIDEO_MODEL,
            "content": [{"type": "text", "text": text}],
            "duration": int(duration),
            "ratio": ratio,
        }
        with httpx.Client(timeout=httpx.Timeout(config.READ_TIMEOUT)) as client:
            task_id = self._submit(client, "/v2/h3_context_ir", payload)
            task = self._poll(client, task_id, lambda *_a: None)
        prompt = (task.get("content") or {}).get("prompt") or ""
        if not prompt:
            raise BackendError(f"H3-Context-IR returned no prompt: {task}")
        return prompt

    def regenerate_2k(self, job_id: str, prompt: str, base_video: Path,
                      progress: ProgressFn) -> GenerationResult:
        ok, reason = self.available()
        if not ok:
            raise BackendError(reason)
        if not base_video.exists():
            raise BackendError(f"Base video {base_video} not found.")
        data_url = "data:video/mp4;base64," + base64.b64encode(
            base_video.read_bytes()
        ).decode()
        payload = {
            "model": config.VIDEO_MODEL,
            "content": [
                {"type": "text", "text": prompt},
                {"type": "video_url", "video_url": {"url": data_url}, "role": "base_video"},
            ],
            "resolution": "2K",
        }
        with httpx.Client(
            timeout=httpx.Timeout(config.READ_TIMEOUT, connect=config.CONNECT_TIMEOUT)
        ) as client:
            progress(0.05, "submitting 2K regeneration")
            task_id = self._submit(client, "/v2/video_regeneration", payload)
            task = self._poll(client, task_id, progress)
            url = (task.get("content") or {}).get("url") or ""
            if not url:
                raise BackendError(f"Regeneration returned no URL: {task}")
            progress(0.9, "downloading 2K video")
            content = client.get(url)
            content.raise_for_status()
        video_path = config.OUTPUT_DIR / f"{job_id}_2k.mp4"
        video_path.write_bytes(content.content)
        return GenerationResult(
            video_path=str(video_path), remote_id=task_id, video_url=url,
            meta={"resolution": "2K"},
        )


def _progress_for(status: str) -> float:
    if status in DONE_STATES:
        return 1.0
    if status in ("queue", "queued", "pending"):
        return 0.15
    if status in ("running", "processing", "in_progress"):
        return 0.55
    return 0.35
