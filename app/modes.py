"""Generation mode specifications.

These limits are taken verbatim from the MiniMax-H3 model card
(https://huggingface.co/MiniMaxAI/MiniMax-H3) so the UI and the API validate
against the same numbers the model actually supports.

H3-Base-FL2VA (task ``t2va`` / ``fl2va``)
    0 images -> text-to-video, 1 image -> first-or-last frame, 2 -> both.
H3-Base-Ref2VA (task ``ref2va``)
    <= 9 images, <= 3 videos (2-15s each), <= 3 audio clips (2-15s each),
    and at most 12 files in total across all input types.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Mode:
    key: str
    label: str
    task: str
    backend_variant: str
    description: str
    images: int
    videos: int
    audio: int
    aspect_ratios: tuple[str, ...]
    min_duration: float
    max_duration: float
    default_duration: float
    max_total_files: int = 0
    default_aspect: str = "16:9"

    @property
    def requires_reference(self) -> bool:
        return self.task == "ref2va"

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "task": self.task,
            "backend_variant": self.backend_variant,
            "description": self.description,
            "limits": {
                "images": self.images,
                "videos": self.videos,
                "audio": self.audio,
                "max_total_files": self.max_total_files,
            },
            "aspect_ratios": list(self.aspect_ratios),
            "duration": {
                "min": self.min_duration,
                "max": self.max_duration,
                "default": self.default_duration,
            },
            "default_aspect": self.default_aspect,
        }


ASPECT_RATIOS = ("21:9", "16:9", "4:3", "1:1", "3:4", "9:16")

MODES: dict[str, Mode] = {
    "t2v": Mode(
        key="t2v",
        label="Text to Video",
        task="t2va",
        backend_variant="fl2va",
        description=(
            "Generate a video with native stereo audio from a text prompt. "
            "No image input."
        ),
        images=0,
        videos=0,
        audio=0,
        aspect_ratios=ASPECT_RATIOS,
        min_duration=4.0,
        max_duration=15.0,
        default_duration=10.0,
    ),
    "i2v": Mode(
        key="i2v",
        label="Image to Video",
        task="fl2va",
        backend_variant="fl2va",
        description=(
            "Animate a still image. One image drives the first or the last "
            "frame, two images describe the path between them."
        ),
        images=2,
        videos=0,
        audio=0,
        aspect_ratios=("auto",) + ASPECT_RATIOS,
        min_duration=4.0,
        max_duration=15.0,
        default_duration=8.0,
        default_aspect="auto",
    ),
    "r2v": Mode(
        key="r2v",
        label="Reference to Video",
        task="ref2va",
        backend_variant="ref2va",
        description=(
            "Omni-reference generation. Mix up to 9 images, 3 videos and "
            "3 audio clips to steer subject, style, motion and voice."
        ),
        images=9,
        videos=3,
        audio=3,
        aspect_ratios=("auto",) + ASPECT_RATIOS,
        min_duration=4.0,
        max_duration=15.0,
        default_duration=5.0,
        max_total_files=12,
        default_aspect="auto",
    ),
}

# Section skeleton of a Context-IR prompt. The order matches the official
# "Video Prompt Writing Guide" for both the base and the reference modes.
PROMPT_SECTIONS_BASE = (
    "integrated_multimodal_description",
    "overall_soundscape",
    "non_diegetic_music",
)

PROMPT_SECTIONS_REF = (
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
)

SHOT_CAMERA_MOVES = (
    "static",
    "push in",
    "pull out",
    "pan left",
    "pan right",
    "tilt up",
    "tilt down",
    "tracking",
    "handheld",
    "crane",
    "orbit",
    "zoom in",
    "zoom out",
)

SHOT_SIZES = (
    "extreme wide shot",
    "wide shot",
    "full shot",
    "medium wide shot",
    "medium shot",
    "medium close-up",
    "close-up",
    "extreme close-up",
    "over-the-shoulder",
    "point of view",
)


def get_mode(key: str) -> Mode:
    mode = MODES.get((key or "").lower())
    if mode is None:
        raise ValueError(f"Unknown mode '{key}'. Expected one of: {', '.join(MODES)}")
    return mode
