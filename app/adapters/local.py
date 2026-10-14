"""Adapter for a self-hosted MiniMax-H3 server.

The official deployment path is SGLang (or vLLM) serving H3-Base behind a small
HTTP API, documented in the model card and reproduced by
``upstream/scripts/reproducible-768p-*.sh``:

    POST {base}/v1/videos                -> {"id": "..."}
    GET  {base}/v1/videos/{id}           -> {"status": "queued|running|completed|failed"}
    GET  {base}/v1/videos/{id}/content   -> mp4 bytes

Ref2VA runs on a second server/port, so this adapter can be pointed at either
endpoint and picks the right one from the task.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from .. import config, media
from .base import (
    BackendError,
    GenerationRequest,
    GenerationResult,
    ProgressFn,
    check_canceled,
)

POLL_INTERVAL = 2.0
STATE_PROGRESS = {
    "queued": 0.10,
    "pending": 0.10,
    "running": 0.45,
    "processing": 0.45,
    "in_progress": 0.45,
    "completed": 1.0,
    "succeeded": 1.0,
}


class LocalBackend:
    name = "local"
    label = "Local H3 server (SGLang / vLLM)"
    description = (
        "Posts to a MiniMax-H3 server you host yourself. Requires a GPU and a "
        "running sglang/vllm deployment; see tools/serve_local.sh."
    )

    def __init__(self) -> None:
        self.base_url = config.LOCAL_BASE_URL.rstrip("/")
        self.base_url_ref = config.LOCAL_BASE_URL_REF.rstrip("/")

    # -- helpers ----------------------------------------------------------
    def endpoint_for(self, task: str) -> str:
        return self.base_url_ref if task == "ref2va" else self.base_url

    def available(self) -> tuple[bool, str]:
        try:
            response = httpx.get(self.base_url + "/v1/videos", timeout=3.0)
        except httpx.HTTPError:
            return False, f"No H3 server reachable at {self.base_url}."
        # 405/404 means something is listening, which is what we can check
        if response.status_code in (200, 400, 404, 405, 422):
            return True, f"H3 server responding at {self.base_url}."
        return False, f"{self.base_url} answered HTTP {response.status_code}."

    def info(self) -> dict:
        ok, reason = self.available()
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "available": ok,
            "reason": reason,
            "endpoints": {"fl2va": self.base_url, "ref2va": self.base_url_ref},
            "requires": ["GPU", "sglang or vllm", "MiniMaxAI/MiniMax-H3 weights"],
        }

    # -- generation -------------------------------------------------------
    def generate(
        self, job_id: str, request: GenerationRequest, progress: ProgressFn
    ) -> GenerationResult:
        base = self.endpoint_for(request.task)
        payload = {
            "task": request.task,
            "prompt": request.prompt,
            "conditions": request.conditions or [],
            "target": request.target(),
            "seed": request.seed,
        }
        if request.negative_prompt:
            payload["negative_prompt"] = request.negative_prompt
        if request.steps:
            payload["num_inference_steps"] = request.steps

        progress(0.05, "submitting to local H3 server")
        try:
            with httpx.Client(timeout=httpx.Timeout(config.READ_TIMEOUT, connect=config.CONNECT_TIMEOUT)) as client:
                response = client.post(base + "/v1/videos", json=payload)
                if response.status_code >= 400:
                    raise BackendError(
                        f"H3 server rejected the request (HTTP {response.status_code}): "
                        f"{response.text[:400]}",
                        hint="Check that the server was started with the matching "
                             "--model-variant and that the weights are loaded.",
                    )
                body = _json(response)
                video_id = body.get("id") or body.get("video_id") or ""
                if not video_id:
                    raise BackendError(f"H3 server did not return a video id: {body}")

                deadline = time.time() + config.READ_TIMEOUT
                state = "queued"
                while True:
                    check_canceled(progress)
                    if time.time() > deadline:
                        raise BackendError(
                            f"Timed out after {config.READ_TIMEOUT:.0f}s waiting for video {video_id}."
                        )
                    time.sleep(POLL_INTERVAL)
                    status_response = client.get(f"{base}/v1/videos/{video_id}")
                    if status_response.status_code >= 400:
                        raise BackendError(
                            f"Status check failed (HTTP {status_response.status_code}): "
                            f"{status_response.text[:300]}"
                        )
                    status_body = _json(status_response)
                    state = str(status_body.get("status", "running")).lower()
                    progress(
                        STATE_PROGRESS.get(state, 0.5),
                        f"H3 server: {state}",
                    )
                    if state in ("completed", "succeeded", "success"):
                        break
                    if state in ("failed", "error", "canceled", "cancelled"):
                        raise BackendError(
                            f"H3 server reported '{state}': "
                            f"{status_body.get('error') or status_body}"
                        )

                progress(0.9, "downloading video")
                content = client.get(f"{base}/v1/videos/{video_id}/content")
                content.raise_for_status()
        except BackendError:
            raise
        except httpx.HTTPError as exc:
            raise BackendError(
                f"Could not talk to the H3 server at {base}: {exc}",
                hint="Start it with tools/serve_local.sh or point "
                     "H3_LOCAL_BASE_URL at an existing deployment.",
            ) from exc

        video_path = config.OUTPUT_DIR / f"{job_id}.mp4"
        video_path.write_bytes(content.content)
        poster = _extract_poster(video_path, job_id)
        return GenerationResult(
            video_path=str(video_path),
            poster_path=str(poster) if poster else "",
            remote_id=video_id,
            meta={"endpoint": base, "server_status": state},
        )


def _json(response: httpx.Response) -> dict:
    try:
        return response.json()
    except Exception:
        raise BackendError(f"Expected JSON, got: {response.text[:300]}") from None


def _extract_poster(video_path: Path, job_id: str) -> Path | None:
    exe = media.ffmpeg_path()
    if exe is None or not video_path.exists():
        return None
    poster = config.OUTPUT_DIR / f"{job_id}.jpg"
    import subprocess

    proc = subprocess.run(
        [exe, "-y", "-hide_banner", "-loglevel", "error", "-i", str(video_path),
         "-vf", "select=eq(n\\,0)", "-frames:v", "1", str(poster)],
        capture_output=True,
    )
    return poster if proc.returncode == 0 and poster.exists() else None
