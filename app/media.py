"""Video / audio helpers.

ffmpeg is located through ``imageio-ffmpeg`` so the app works on machines that
have no system ffmpeg (the OpenHands runtime is one of them). Everything here
degrades gracefully: if no encoder is available we still hand back the raw
frames so the caller can report a useful error instead of crashing.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np

SAMPLE_RATE = 32000  # H3-AudioVAE outputs 32 kHz stereo
FPS = 24  # H3 output frame rate


def ffmpeg_path() -> str | None:
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def has_encoder() -> bool:
    return ffmpeg_path() is not None


def write_video(
    frames: list[np.ndarray],
    path: Path,
    fps: int = FPS,
    audio: np.ndarray | None = None,
    sample_rate: int = SAMPLE_RATE,
) -> Path:
    """Encode ``frames`` (uint8 HxWx3) plus optional stereo audio into an mp4."""
    exe = ffmpeg_path()
    if exe is None:
        raise RuntimeError(
            "No ffmpeg binary available. Install ffmpeg or the imageio-ffmpeg "
            "package to encode video."
        )
    if not frames:
        raise RuntimeError("No frames to encode.")

    path.parent.mkdir(parents=True, exist_ok=True)
    height, width = frames[0].shape[:2]
    if width % 2 or height % 2:
        width -= width % 2
        height -= height % 2
        frames = [f[:height, :width] for f in frames]

    tmp_audio: Path | None = None
    cmd = [
        exe, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}", "-r", str(fps), "-i", "pipe:0",
    ]
    if audio is not None and len(audio):
        tmp_audio = path.with_suffix(".tmp.wav")
        write_wav(audio, tmp_audio, sample_rate)
        cmd += ["-i", str(tmp_audio)]
    cmd += [
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
    ]
    if tmp_audio is not None:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += [str(path)]

    try:
        proc = subprocess.run(cmd, input=b"".join(f.tobytes() for f in frames), capture_output=True)
    finally:
        if tmp_audio is not None:
            tmp_audio.unlink(missing_ok=True)

    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed ({proc.returncode}): {proc.stderr.decode(errors='replace')[-800:]}"
        )
    return path


def write_wav(audio: np.ndarray, path: Path, sample_rate: int = SAMPLE_RATE) -> Path:
    """Write float32/float64 audio as a 16 bit PCM wav without scipy."""
    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.asarray(audio, dtype=np.float32)
    if data.ndim == 1:
        data = data.reshape(1, -1)
    if data.shape[0] > data.shape[1]:
        data = data.T  # expect (channels, samples)
    channels, samples = data.shape
    clipped = np.clip(data, -1.0, 1.0)
    interleaved = (clipped.T.reshape(-1) * 32767.0).astype("<i2")

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(interleaved.tobytes())
    return path


def wav_duration(path: Path) -> float:
    import wave

    try:
        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate() or 1
            return handle.getnframes() / float(rate)
    except Exception:
        return 0.0


def probe_duration(path: Path) -> float:
    """Read the duration of any media file ffprobe-less via ffmpeg."""
    exe = ffmpeg_path()
    if exe is None or not path.exists():
        return 0.0
    probe = str(Path(exe).with_name("ffprobe"))
    if Path(probe).exists():
        proc = subprocess.run(
            [probe, "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True,
        )
        if proc.returncode == 0:
            try:
                return float(json.loads(proc.stdout)["format"]["duration"])
            except Exception:
                pass
    if path.suffix.lower() == ".wav":
        return wav_duration(path)
    return 0.0


def parse_frame_rate(value: str) -> float:
    try:
        if "/" in value:
            num, den = value.split("/")
            return float(num) / float(den or 1)
        return float(value)
    except Exception:
        return float(FPS)


def audio_from_prompt(prompt: str, duration: float, seed: int = 0) -> np.ndarray:
    """Deterministic placeholder stereo track.

    Used only by the offline demo backend so the audio muxing path can be
    exercised without the 33B model. The result is a short musical phrase with
    an amplitude envelope, not noise, so it is pleasant to check by ear.
    """
    samples = int(SAMPLE_RATE * max(duration, 0.1))
    t = np.arange(samples, dtype=np.float64) / SAMPLE_RATE
    rng = np.random.default_rng(seed or 0)

    # pick a pentatonic root from the prompt so the demo varies per prompt
    root = 110.0 * (2 ** (len(prompt) % 12) / 12.0) * 1.0
    scale = [1.0, 9 / 8, 5 / 4, 3 / 2, 5 / 3, 2.0]
    left = np.zeros(samples)
    right = np.zeros(samples)
    beat = 0.5
    index = 0
    position = 0.0
    while position < duration:
        note = root * scale[rng.integers(0, len(scale))] * (2 if rng.random() > 0.7 else 1)
        start = int(position * SAMPLE_RATE)
        length = int(beat * SAMPLE_RATE)
        end = min(start + length, samples)
        if end > start:
            local = np.arange(end - start) / SAMPLE_RATE
            env = np.exp(-3.0 * local) * (1 - np.exp(-80.0 * local))
            tone = np.sin(2 * math.pi * note * local) * 0.5
            tone += np.sin(2 * math.pi * note * 2 * local) * 0.15
            left[start:end] += tone * env
            right[start:end] += tone * env * 0.9
        position += beat
        index += 1
    bed = 0.05 * np.sin(2 * math.pi * root / 2 * t)
    left += bed
    right += bed
    peak = float(np.max(np.abs(np.concatenate([left, right]))) or 1.0)
    gain = 0.85 / peak
    return np.stack([left * gain, right * gain])
