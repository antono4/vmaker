"""FastAPI application: JSON API plus the static studio UI."""

from __future__ import annotations

import asyncio
import json
import re
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile as StarletteUploadFile

from . import __version__, config, media, modes, prompt as prompt_lib
from .adapters import GenerationRequest, ProgressReporter, all_backends, get as get_backend
from .adapters.base import BackendError, Canceled
from .store import store

config.ensure_dirs()

STATIC_DIR = Path(__file__).resolve().parent / "static"
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    # Ask in-flight renders to stop and give the worker threads a moment to
    # notice. Without this, a render started seconds earlier keeps running
    # after shutdown, which makes tests and container restarts hang.
    for reporter in list(reporter_for_job.values()):
        reporter.cancel()
    tasks = [task for task in RUNNING.values() if not task.done()]
    if tasks:
        _done, pending = await asyncio.wait(tasks, timeout=10)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


app = FastAPI(
    title="MiniMax H3 Video Maker",
    version=__version__,
    description=(
        "Text, image and reference driven video generation with MiniMax-H3, "
        "including native stereo audio."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/media", StaticFiles(directory=str(config.DATA_DIR)), name="media")

RUNNING: dict[str, asyncio.Task] = {}
reporter_for_job: dict[str, ProgressReporter] = {}


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/healthz")
async def healthz() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "encoder": media.ffmpeg_path() or None,
        "jobs": len(store.list()),
    }


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------
@app.get("/api/backends")
async def api_backends() -> dict:
    return {"default": config.DEFAULT_BACKEND, "backends": [b.info() for b in all_backends()]}


@app.post("/api/backends/api/key")
async def api_set_key(payload: dict) -> dict:
    """Store a MiniMax API key for this process only (never persisted).

    The key is held in memory by the adapter and is deliberately not echoed
    back; the response reports only whether a key is now usable.
    """
    key = str(payload.get("api_key", "")).strip()
    base = str(payload.get("api_base", "")).strip()
    if not key and not base:
        raise HTTPException(status_code=400, detail="Provide an api_key or api_base.")
    if base and not base.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=400,
            detail="api_base must start with http:// or https://",
        )
    backend = get_backend("api")
    backend.set_key(key, base)
    ok, reason = backend.available()
    return {"backend": backend.info(), "available": ok, "reason": reason}


@app.delete("/api/backends/api/key")
async def api_clear_key() -> dict:
    backend = get_backend("api")
    backend.clear_key()
    return {"backend": backend.info(), "available": False}


@app.get("/api/modes")
async def api_modes() -> dict:
    return {
        "modes": [m.to_dict() for m in modes.MODES.values()],
        "shot_sizes": list(modes.SHOT_SIZES),
        "camera_moves": list(modes.SHOT_CAMERA_MOVES),
        "retention_policies": list(prompt_lib.RETENTION_POLICIES),
        "model": {
            "id": config.MODEL_ID,
            "turbo_lora_id": config.TURBO_LORA_ID,
            "fps": media.FPS,
            "audio": "32 kHz stereo",
            "max_duration": 15,
            "min_duration": 4,
        },
    }


@app.post("/api/prompt/preview")
async def api_prompt_preview(payload: dict) -> dict:
    mode_key = str(payload.get("mode", "t2v"))
    try:
        mode = modes.get_mode(mode_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    spec = prompt_lib.PromptSpec.from_dict({**payload, "mode": mode_key})
    problems = prompt_lib.validate_references(mode, spec.references)
    composed = prompt_lib.compose(spec)
    return {
        "mode": mode_key,
        "task": mode.task,
        "prompt": composed,
        "characters": len(composed),
        "sections": [s for s in composed.split("\n") if s.endswith(":")] or [],
        "problems": problems,
        "conditions": prompt_lib.build_conditions(mode, spec.references),
    }


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
@app.post("/api/generate")
async def api_generate(request: Request) -> dict:
    content_type = request.headers.get("content-type", "")
    uploads: list[tuple[int, UploadFile]] = []
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        payload = json.loads(form.get("payload") or "{}")
        for key in form.keys():
            if not key.startswith("file_"):
                continue
            try:
                index = int(key.split("_", 1)[1])
            except ValueError:
                continue
            value = form.get(key)
            if isinstance(value, StarletteUploadFile) and value.filename:
                uploads.append((index, value))
    else:
        payload = await request.json()

    mode_key = str(payload.get("mode", "t2v"))
    try:
        mode = modes.get_mode(mode_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    backend_name = str(payload.get("backend") or config.DEFAULT_BACKEND)
    try:
        backend = get_backend(backend_name)
    except BackendError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    spec = prompt_lib.PromptSpec.from_dict({**payload, "mode": mode_key})

    for index, upload in uploads:
        if index < 0 or index >= len(spec.references):
            continue
        item = await _persist_upload(upload)
        spec.references[index].uri = item["url"]
        spec.references[index].filename = item["name"]

    problems = prompt_lib.validate_references(mode, spec.references)
    if problems:
        raise HTTPException(status_code=400, detail=" ".join(problems))

    duration = _clamp(_to_float(payload.get("duration"), mode.default_duration),
                      mode.min_duration, mode.max_duration)
    aspect = str(payload.get("aspect_ratio") or mode.default_aspect)
    if aspect not in mode.aspect_ratios:
        aspect = mode.default_aspect
    resolution = str(payload.get("resolution", "768p")).lower()
    if resolution not in ("768p", "2k"):
        resolution = "768p"
    short_edge = 1440 if resolution == "2k" else 768

    composed = prompt_lib.compose(spec)
    if not composed.strip():
        raise HTTPException(
            status_code=400,
            detail="The composed prompt is empty. Fill in at least a subject or one shot.",
        )

    job = store.create(
        mode=mode_key,
        backend=backend_name,
        task=mode.task,
        prompt=composed,
        raw_prompt=str(payload.get("raw_prompt", "")),
        negative_prompt=spec.negative,
        duration=duration,
        aspect_ratio=aspect,
        short_edge=short_edge,
        seed=int(_to_float(payload.get("seed"), 0)),
        resolution=resolution,
        steps=int(_to_float(payload.get("steps"), 0)),
        conditions=prompt_lib.build_conditions(mode, spec.references),
        meta={
            "backend_variant": mode.backend_variant,
            "references": [r.__dict__ for r in spec.references],
            "shots": [s.__dict__ for s in spec.shots],
        },
    )

    generation_request = GenerationRequest(
        mode=mode_key,
        task=mode.task,
        prompt=composed,
        raw_prompt=job.raw_prompt,
        negative_prompt=spec.negative,
        duration=duration,
        aspect_ratio=aspect,
        short_edge=short_edge,
        seed=job.seed,
        resolution=resolution,
        conditions=job.conditions,
        references=[r.__dict__ for r in spec.references],
        language=spec.language,
        shots=[s.__dict__ for s in spec.shots],
    )

    RUNNING[job.id] = asyncio.create_task(
        _run_job(job.id, backend_name, generation_request)
    )
    return {"job": store.get(job.id).to_dict()}


@app.get("/api/jobs")
async def api_jobs() -> dict:
    return {"jobs": [j.to_dict() for j in store.list()]}


@app.get("/api/jobs/{job_id}")
async def api_job(job_id: str) -> dict:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"job": job.to_dict()}


@app.delete("/api/jobs/{job_id}")
async def api_job_delete(job_id: str) -> dict:
    # Signal the backend first: a render already inside a worker thread only
    # stops when it next checks the flag, and the task cancel below cannot
    # interrupt that thread.
    reporter = reporter_for_job.get(job_id)
    if reporter is not None:
        reporter.cancel()
    task = RUNNING.pop(job_id, None)
    if task and not task.done():
        task.cancel()
    if not store.delete(job_id):
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"deleted": job_id}


@app.post("/api/jobs/{job_id}/regenerate-2k")
async def api_regenerate_2k(job_id: str) -> dict:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    backend = get_backend("api")
    ok, reason = backend.available()
    if not ok:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{reason} H3-Regenerate-2K is a hosted service and is not part "
                "of the open-source release."
            ),
        )

    if not job.video_path or not Path(job.video_path).exists():
        raise HTTPException(status_code=400, detail="This job has no base video yet.")

    def _progress(value: float, stage: str) -> None:
        store.update(job_id, progress=min(0.95, value), stage=stage)

    try:
        result = await asyncio.to_thread(
            backend.regenerate_2k, job_id, job.prompt, Path(job.video_path), _progress
        )
    except BackendError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    video_url = f"/media/outputs/{Path(result.video_path).name}"
    store.update(
        job_id,
        status="completed",
        progress=1.0,
        stage="2K ready",
        video_url=video_url,
        video_path=result.video_path,
        meta={**job.meta, "upscaled_2k": True, "video_url_remote": result.video_url},
    )
    return {"job": store.get(job_id).to_dict()}


@app.post("/api/prompt/expand")
async def api_prompt_expand(payload: dict) -> dict:
    """Optional H3-Context-IR expansion through the MiniMax Open Platform."""
    text = str(payload.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="Nothing to expand.")
    backend = get_backend("api")
    ok, reason = backend.available()
    if not ok:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{reason} H3-Context-IR is a hosted service, so it needs an API "
                "key. Without it, use the composer fields instead."
            ),
        )
    try:
        expanded = await asyncio.to_thread(
            backend.expand_prompt,
            text,
            _to_float(payload.get("duration"), 8.0),
            str(payload.get("aspect_ratio", "16:9")),
        )
    except BackendError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"prompt": expanded, "characters": len(expanded)}


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
async def _run_job(job_id: str, backend_name: str, request: GenerationRequest) -> None:
    backend = get_backend(backend_name)

    def progress(value: float, stage: str) -> None:
        store.update(job_id, progress=round(min(max(value, 0.0), 1.0), 3), stage=stage)

    reporter = ProgressReporter(progress)
    reporter_for_job[job_id] = reporter

    store.update(job_id, status="running", stage="starting", progress=0.02)
    try:
        result = await asyncio.to_thread(backend.generate, job_id, request, reporter)
    except Canceled:
        store.update(job_id, status="canceled", stage="canceled", error="Canceled.")
        return
    except asyncio.CancelledError:
        reporter.cancel()
        store.update(job_id, status="canceled", stage="canceled", error="Canceled.")
        raise
    except BackendError as exc:
        store.update(
            job_id,
            status="failed",
            stage="failed",
            error=str(exc),
            meta={"hint": exc.hint},
        )
        return
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI on purpose
        store.update(
            job_id,
            status="failed",
            stage="failed",
            error=f"{type(exc).__name__}: {exc}",
            meta={"traceback": traceback.format_exc()[-2000:]},
        )
        return
    finally:
        RUNNING.pop(job_id, None)
        reporter_for_job.pop(job_id, None)

    video_url = f"/media/outputs/{Path(result.video_path).name}" if result.video_path else ""
    audio_url = f"/media/outputs/{Path(result.audio_path).name}" if result.audio_path else ""
    poster_url = f"/media/outputs/{Path(result.poster_path).name}" if result.poster_path else ""
    store.update(
        job_id,
        status="completed",
        stage="completed",
        progress=1.0,
        video_path=result.video_path,
        audio_path=result.audio_path,
        poster_path=result.poster_path,
        video_url=video_url,
        audio_url=audio_url,
        poster_url=poster_url,
        remote_id=result.remote_id,
        meta={**store.get(job_id).meta, **result.meta},
    )


async def _persist_upload(upload: StarletteUploadFile) -> dict:
    raw = await upload.read()
    if not raw:
        raise HTTPException(status_code=400, detail=f"{upload.filename} is empty.")
    if len(raw) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"{upload.filename} exceeds {config.MAX_UPLOAD_MB} MB.",
        )
    safe = SAFE_NAME.sub("_", Path(upload.filename).name)
    stamp = int(time.time() * 1000)
    target = config.UPLOAD_DIR / f"{stamp}_{safe}"
    target.write_bytes(raw)
    return {"name": upload.filename, "url": f"/media/uploads/{target.name}"}


def _to_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@app.exception_handler(BackendError)
async def backend_error_handler(_request: Request, exc: BackendError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc), "hint": exc.hint})


def run() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=config.HOST,
        port=config.PORT,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    run()
