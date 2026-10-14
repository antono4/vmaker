"""Offline demo backend.

Renders a real, playable mp4 with synchronized stereo audio directly on the
CPU, with no GPU, no weights and no credentials. Its only purpose is to let you
exercise the whole pipeline -- submit, progress, poll, mux audio, poster,
gallery, download -- and to give you a reference file to compare against when
the real H3 server is up.

The output is clearly watermarked so it can never be mistaken for model output.
"""

from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np

from .. import config, media
from .base import (
    BackendError,
    Canceled,
    GenerationRequest,
    GenerationResult,
    ProgressFn,
    check_canceled,
)

PALETTES = (
    ((10, 14, 32), (72, 46, 168), (232, 138, 92)),
    ((6, 24, 28), (24, 122, 132), (240, 214, 128)),
    ((28, 10, 24), (150, 40, 110), (250, 170, 150)),
    ((8, 20, 12), (46, 128, 72), (200, 232, 150)),
    ((22, 16, 8), (168, 112, 40), (250, 220, 170)),
    ((12, 12, 20), (86, 96, 200), (180, 220, 255)),
)

RESOLUTIONS = {"768p": (1280, 720), "2k": (2560, 1440)}


class DemoBackend:
    name = "demo"
    label = "Offline demo renderer (no GPU)"
    description = (
        "Renders a watermarked placeholder clip on the CPU. Use it to verify "
        "the studio end to end before pointing it at a real H3 server."
    )

    def available(self) -> tuple[bool, str]:
        if not media.has_encoder():
            return False, "No ffmpeg binary found (install ffmpeg or imageio-ffmpeg)."
        return True, "CPU renderer ready."

    def info(self) -> dict:
        ok, reason = self.available()
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "available": ok,
            "reason": reason,
            "requires": ["nothing"],
        }

    def generate(
        self, job_id: str, request: GenerationRequest, progress: ProgressFn
    ) -> GenerationResult:
        ok, reason = self.available()
        if not ok:
            raise BackendError(reason)

        width, height = RESOLUTIONS.get(request.resolution, RESOLUTIONS["768p"])
        aspect = _aspect_scale(request.aspect_ratio)
        if aspect:
            # Keep the *short* edge at the target size, the way H3-Base does
            # (the model card calls this "short_edge"). A 9:16 request is
            # therefore 432x768, not 720x1280.
            short = request.short_edge or 768
            if aspect >= 1:
                width, height = int(round(short * aspect)), short
            else:
                width, height = short, int(round(short / aspect))

        # libx264 needs even dimensions
        width -= width % 2
        height -= height % 2

        fps = media.FPS
        total_frames = max(int(request.duration * fps), 1)
        progress(0.05, "preparing demo render")

        seed = request.seed or abs(hash(request.prompt)) % (2**31)
        rng = np.random.default_rng(seed)
        palette = PALETTES[seed % len(PALETTES)]
        # float32 keeps the per-frame math about twice as fast as float64,
        # and the demo only ever quantises to 8-bit anyway.
        base_color = np.array(palette[0], dtype=np.float32)
        blob_colors = [np.array(c, dtype=np.float32) for c in palette[1:]]

        # smooth blob trajectories
        blobs = []
        for i in range(5):
            blobs.append({
                "color": blob_colors[i % len(blob_colors)],
                "x0": rng.uniform(0.1, 0.9),
                "y0": rng.uniform(0.15, 0.85),
                "radius": rng.uniform(0.18, 0.42),
                "phase": rng.uniform(0, math.tau),
                "speed": rng.uniform(0.25, 0.7) * (1 if rng.random() > 0.5 else -1),
                "drift": rng.uniform(0.05, 0.16),
            })

        # slow push-in, matching the "camera" language of the prompt spec
        shot_count = max(len(request.shots), 1)

        poster_dir = config.OUTPUT_DIR
        video_path = poster_dir / f"{job_id}.mp4"
        poster_path = poster_dir / f"{job_id}.jpg"

        # The blobs, vignette and light sweep are all smooth, so the field is
        # built on a coarse grid and scaled up. Only the grain and the tint
        # touch every pixel, which keeps the per-frame cost down.
        field_w = min(width, 320)
        field_h = max(int(round(field_w * height / width)), 2)

        gy, gx = np.mgrid[0:field_h, 0:field_w]
        # coarse coordinates in full-resolution pixel units, so the push-in
        # zoom stays centred the same way it would at full resolution
        grid_x = (gx.astype(np.float32) + 0.5) * (width / field_w)
        grid_y = (gy.astype(np.float32) + 0.5) * (height / field_h)

        glow = np.array([255, 250, 235], dtype=np.float32)
        grain = np.random.default_rng(seed + 1)
        grain_shape = (height, width, 3)
        frames: list[np.ndarray] = []
        started = time.time()

        def upsample(field: np.ndarray) -> np.ndarray:
            tiled = np.repeat(np.repeat(field, math.ceil(height / field_h), axis=0),
                              math.ceil(width / field_w), axis=1)
            return tiled[:height, :width]

        for index in range(total_frames):
            check_canceled(progress)
            t = index / total_frames
            zoom = 1.0 + 0.12 * t  # gentle push in
            cx = (grid_x - width * 0.5) / zoom + width * 0.5
            cy = (grid_y - height * 0.5) / zoom + height * 0.5
            nx = cx / width
            ny = cy / height

            small = base_color[None, None, :] * (0.6 + 0.4 * (1.0 - ny))[..., None]

            for blob in blobs:
                angle = blob["phase"] + math.tau * blob["speed"] * t
                bx = blob["x0"] + blob["drift"] * math.cos(angle)
                by = blob["y0"] + blob["drift"] * math.sin(angle * 1.3)
                dist = np.sqrt((nx - bx) ** 2 + ((ny - by) * 1.4) ** 2)
                falloff = np.clip(1.0 - dist / blob["radius"], 0.0, 1.0)
                small += blob["color"] * (falloff ** 2.2)[..., None] * 0.85

            # a light sweep across the frame
            sweep = np.clip(1.0 - np.abs(nx - (t * 1.4 - 0.2)) * 5.0, 0.0, 1.0)
            small += glow * (sweep ** 3)[..., None] * 0.35

            vignette = 1.0 - 0.85 * (((nx - 0.5) ** 2 + (ny - 0.5) ** 2) * 1.8)
            small *= vignette[..., None]

            frame = upsample(small)
            # Every sixth frame gets an overlay that covers the whole
            # canvas, so the grain under it would never be visible.
            if index % 6 != 0:
                frame += grain.normal(0, 3.2, grain_shape).astype(np.float32)
            frame = np.clip(frame, 0, 255).astype(np.uint8)

            if index % 6 == 0:
                frame = _draw_overlay(
                    frame, request, index, total_frames, shot_count, t
                )
            frames.append(frame)

            if index % max(total_frames // 20, 1) == 0:
                progress(0.1 + 0.75 * (index / total_frames), "rendering frames")

        progress(0.88, "encoding video")
        audio = media.audio_from_prompt(request.prompt, request.duration, seed)
        media.write_video(frames, video_path, fps=fps, audio=audio)

        try:
            from PIL import Image

            Image.fromarray(frames[len(frames) // 3]).save(poster_path, quality=88)
        except Exception:
            poster_path = None  # type: ignore[assignment]

        progress(1.0, "demo render complete")
        return GenerationResult(
            video_path=str(video_path),
            poster_path=str(poster_path) if poster_path else "",
            meta={
                "backend": "demo",
                "render_seconds": round(time.time() - started, 2),
                "frames": total_frames,
                "resolution": f"{width}x{height}",
                "watermarked": True,
            },
        )


def _aspect_scale(ratio: str) -> float | None:
    if not ratio or ratio == "auto":
        return 16 / 9
    try:
        left, right = ratio.split(":")
        return float(left) / float(right)
    except Exception:
        return 16 / 9


def _draw_overlay(frame, request, index, total_frames, shot_count, t):
    from PIL import Image, ImageDraw

    image = Image.fromarray(frame)
    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size

    # translucent bars top and bottom
    draw.rectangle([0, 0, width, 74], fill=(0, 0, 0, 110))
    draw.rectangle([0, height - 58, width, height], fill=(0, 0, 0, 110))

    title = _ellipsize(request.prompt.strip().split("\n")[0], 92)
    draw.text((24, 18), title or "(no prompt)", fill=(255, 255, 255, 235))
    subtitle = (
        f"{request.mode.upper()}  |  {request.task}  |  "
        f"{request.duration:g}s  |  {request.aspect_ratio}  |  seed {request.seed}"
    )
    draw.text((24, 44), subtitle, fill=(210, 220, 235, 220))

    shot_index = min(int(t * shot_count) + 1, shot_count)
    draw.text((24, height - 44),
              f"SHOT {shot_index}/{shot_count}   {_timecode(index)}   "
              f"frame {index + 1}/{total_frames}",
              fill=(235, 240, 250, 220))
    draw.text((width - 300, height - 44), "DEMO RENDER - NOT MODEL OUTPUT",
              fill=(255, 190, 120, 235))

    bar_width = int((index / max(total_frames - 1, 1)) * (width - 48))
    draw.rectangle([24, height - 12, 24 + bar_width, height - 7], fill=(255, 190, 120, 220))
    draw.rectangle([24, height - 12, width - 24, height - 7], outline=(255, 255, 255, 70))

    return np.asarray(image).copy()


def _timecode(index: int) -> str:
    seconds = index / media.FPS
    return f"00:00:{seconds:06.3f}"


def _ellipsize(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"
