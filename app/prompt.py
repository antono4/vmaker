"""H3-Context-IR prompt composer.

The official model card is explicit that raw user text is not what H3-Base
expects: H3-Base consumes the *Context Intermediate Representation* produced by
H3-Context-IR, and quality drops sharply without it. This module builds that
representation locally from structured fields, following the two public
templates:

* base mode  -> ``integrated_multimodal_description`` / ``overall_soundscape``
                / ``non_diegetic_music``
* ref mode   -> ``subject_definitions`` / ``summary`` / ``retention_analysis``
                / ``detailed_description`` / ``overall_soundscape``
                / ``non_diegetic_music``

See ``docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md`` and
``docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md`` for the source material.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .modes import SHOT_CAMERA_MOVES, SHOT_SIZES

DIALOGUE_TAG = re.compile(r"<d>\s*(?:\[(?P<lang>[A-Za-z\-]+)\])?\s*(?P<line>.*?)</d>", re.S)

# The official guide specifies camera motion as "motion type + amplitude + speed".
# These phrases turn the UI's short move names into the prose H3 expects.
CAMERA_PHRASES = {
    "static": "holds a static shot",
    "none": "holds a static shot",
    "push in": "pushes in",
    "pull out": "pulls out",
    "pan left": "pans left",
    "pan right": "pans right",
    "tilt up": "tilts up",
    "tilt down": "tilts down",
    "tracking": "tracks the subject",
    "handheld": "is handheld",
    "crane": "cranes",
    "orbit": "orbits the subject",
    "zoom in": "zooms in",
    "zoom out": "zooms out",
}


def _camera_sentence(move: str, amplitude: str, speed: str) -> str:
    key = (move or "").strip().lower()
    if not key:
        return ""
    phrase = CAMERA_PHRASES.get(key, f"moves ({key})")
    if phrase.startswith("holds"):
        return f"The camera {phrase}."
    modifiers = [m.strip().rstrip(".") for m in (amplitude, speed) if m and m.strip()]
    if modifiers:
        return f"The camera {phrase} {', '.join(modifiers)}."
    return f"The camera {phrase}."


def _timecode(seconds: float) -> str:
    """Format seconds as mm:ss.mmm, the timestamp style used by the guide."""
    seconds = max(float(seconds), 0.0)
    minutes = int(seconds // 60)
    remainder = seconds - minutes * 60
    return f"{minutes:02d}:{remainder:06.3f}"


@dataclass
class Shot:
    """One shot inside a sequence."""

    description: str = ""
    shot_size: str = ""
    camera_move: str = ""
    amplitude: str = ""
    speed: str = ""
    start_seconds: float | None = None
    dialogue: list[str] = field(default_factory=list)
    on_screen_text: list[str] = field(default_factory=list)

    def render(self, index: int, is_first: bool) -> str:
        parts: list[str] = []
        leading_time = ""
        if not is_first and self.start_seconds is not None:
            leading_time = f"At {_timecode(self.start_seconds)},"
        if self.shot_size:
            parts.append(self.shot_size.rstrip(".") + ".")
        camera = _camera_sentence(self.camera_move, self.amplitude, self.speed)
        if camera:
            parts.append(camera)
        body = " ".join(self.description.split())
        if body:
            parts.append(body if body.endswith((".", "!", "?")) else body + ".")
        for text in self.on_screen_text:
            text = " ".join(text.split())
            if text:
                parts.append(f'On-screen text reads "{text}".')
        for line in self.dialogue:
            line = " ".join(line.split())
            if not line:
                continue
            match = DIALOGUE_TAG.search(line)
            if match:
                parts.append(f"The speaker delivers {match.group(0)}.")
            else:
                parts.append(f"The speaker delivers <d>{line}</d>.")
        if leading_time and parts:
            parts[0] = parts[0][:1].lower() + parts[0][1:]
            return f"{leading_time} {parts[0]}" + (" " + " ".join(parts[1:]) if len(parts) > 1 else "")
        return " ".join(parts).strip()


@dataclass
class Reference:
    """One reference asset for Ref2VA mode."""

    kind: str  # image | video | audio
    label: str = ""
    description: str = ""
    role: str = ""
    retention: str = "fully_preserved"
    uri: str = ""
    filename: str = ""

    @property
    def index(self) -> int:
        match = re.search(r"(\d+)", self.label)
        return int(match.group(1)) if match else 0


RETENTION_POLICIES = (
    "fully_preserved",
    "partially_preserved",
    "reference",
    "partially_copy",
    "fully_copy",
    "replaced",
    "removed",
)

KIND_TO_LABEL = {"image": "Picture", "video": "Video", "audio": "Audio"}


@dataclass
class PromptSpec:
    mode: str
    subject: str = ""
    action: str = ""
    setting: str = ""
    style: str = ""
    lighting: str = ""
    extra: str = ""
    shots: list[Shot] = field(default_factory=list)
    soundscape: str = ""
    music: str = ""
    negative: str = ""
    references: list[Reference] = field(default_factory=list)
    summary: str = ""
    language: str = "English"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PromptSpec":
        shots = [
            Shot(
                description=str(s.get("description", "")),
                shot_size=str(s.get("shot_size", "")),
                camera_move=str(s.get("camera_move", "")),
                amplitude=str(s.get("amplitude", "")),
                speed=str(s.get("speed", "")),
                start_seconds=_to_float(s.get("start_seconds")),
                dialogue=_to_list(s.get("dialogue")),
                on_screen_text=_to_list(s.get("on_screen_text")),
            )
            for s in data.get("shots", []) or []
            if isinstance(s, dict)
        ]
        references = [
            Reference(
                kind=str(r.get("kind", "image")),
                label=str(r.get("label", "")),
                description=str(r.get("description", "")),
                role=str(r.get("role", "reference")),
                retention=str(r.get("retention", "fully_preserved")),
                uri=str(r.get("uri", "")),
                filename=str(r.get("filename", "")),
            )
            for r in data.get("references", []) or []
            if isinstance(r, dict)
        ]
        return cls(
            mode=str(data.get("mode", "t2v")),
            subject=str(data.get("subject", "")),
            action=str(data.get("action", "")),
            setting=str(data.get("setting", "")),
            style=str(data.get("style", "")),
            lighting=str(data.get("lighting", "")),
            extra=str(data.get("extra", "")),
            shots=shots,
            soundscape=str(data.get("soundscape", "")),
            music=str(data.get("music", "")),
            negative=str(data.get("negative", "")),
            references=references,
            summary=str(data.get("summary", "")),
            language=str(data.get("language", "English")),
        )


def _to_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [line for line in value.splitlines() if line.strip()]
    if isinstance(value, Iterable):
        return [str(v) for v in value]
    return [str(value)]


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sentence(text: str) -> str:
    text = " ".join((text or "").split())
    if not text:
        return ""
    return text if text.endswith((".", "!", "?", ":")) else text + "."


def _numbered(label: str, index: int) -> str:
    return f"<{label} {index}>"


def auto_label(kind: str, index: int) -> str:
    return _numbered(KIND_TO_LABEL.get(kind, "Subject"), index)


def subject_line(ref: Reference) -> str:
    label = ref.label or auto_label(ref.kind, ref.index or 1)
    description = _sentence(ref.description)
    if description:
        return f"{label} is {description}"
    return f"{label} is provided by the user as a {ref.kind} reference."


def build_base_prompt(spec: PromptSpec) -> str:
    """Compose the base-mode (t2va / fl2va) Context-IR prompt."""
    blocks: list[str] = []

    preamble: list[str] = []
    if spec.mode == "i2v" and spec.references:
        picture_labels = [
            r.label or auto_label(r.kind, i + 1)
            for i, r in enumerate(spec.references)
            if r.kind == "image"
        ]
        if picture_labels:
            joined = ", ".join(picture_labels[:-1]) + (
                f" and {picture_labels[-1]}" if len(picture_labels) > 1 else picture_labels[0]
            )
            if len(picture_labels) == 1:
                preamble.append(
                    f"For the target video, at 0.00 seconds into the target video, "
                    f"{joined} (from [Shot 1]) is fully referenced."
                )
            else:
                preamble.append(
                    f"For the target video, the first frame fully references "
                    f"{picture_labels[0]} and the final frame fully references "
                    f"{picture_labels[-1]}."
                )
    if preamble:
        blocks.append("\n".join(preamble))

    opening: list[str] = []
    if spec.style:
        opening.append(_sentence(spec.style))
    if spec.setting:
        opening.append(_sentence(f"The scene is set in {spec.setting}"))
    if spec.lighting:
        opening.append(_sentence(f"Lighting: {spec.lighting}"))

    shots: list[str] = []
    for index, shot in enumerate(spec.shots, start=1):
        rendered = shot.render(index, is_first=index == 1)
        if rendered:
            shots.append(f"[Shot {index}] {rendered}")
    if not shots:
        fallback = _sentence(" ".join(p for p in (spec.subject, spec.action) if p))
        if fallback:
            shots.append(f"[Shot 1] {fallback}")

    description_parts = opening + shots
    if spec.extra:
        description_parts.append(_sentence(spec.extra))

    if description_parts:
        blocks.append("integrated_multimodal_description: " + " ".join(description_parts))

    if spec.soundscape:
        blocks.append("overall_soundscape: " + _sentence(spec.soundscape))
    if spec.music:
        blocks.append("non_diegetic_music: " + _sentence(spec.music))

    return "\n".join(blocks).strip()


def _shots_mentioning(spec: PromptSpec, label: str) -> list[int]:
    """Shot numbers whose text refers to ``label`` (e.g. <Picture 1>)."""
    hits = []
    for index, shot in enumerate(spec.shots, start=1):
        haystack = " ".join([shot.description, *shot.dialogue, *shot.on_screen_text])
        if label and label in haystack:
            hits.append(index)
    return hits


def _summary_tag(spec: PromptSpec) -> str:
    """Build the bracketed relationship tag the guide puts on the summary."""
    tags: list[str] = []
    kinds = {ref.kind for ref in spec.references}
    if spec.mode == "r2v":
        if "video" in kinds:
            tags.append("video editing")
        else:
            tags.append("reference generation")
    if "image" in kinds:
        tags.append("image reference")
    if "audio" in kinds:
        tags.append("audio reference")
    policies = {ref.retention for ref in spec.references}
    if policies & {"fully_copy", "partially_copy"}:
        tags.append("audio reuse" if "audio" in kinds else "material reuse")
    return f"[{' + '.join(tags)}] " if tags else ""


def build_ref_prompt(spec: PromptSpec) -> str:
    """Compose the reference-mode (ref2va) Context-IR prompt.

    Section order and wording follow the Full-Reference Mode guide:
    subject_definitions, summary, retention_analysis, detailed_description,
    overall_soundscape, non_diegetic_music.
    """
    blocks: list[str] = []

    if spec.references:
        lines = ["subject_definitions:"]
        counters: dict[str, int] = {}
        for ref in spec.references:
            counters[ref.kind] = counters.get(ref.kind, 0) + 1
            if not ref.label:
                ref.label = auto_label(ref.kind, counters[ref.kind])
            lines.append(subject_line(ref))
        blocks.append("\n".join(lines))

    summary_bits: list[str] = []
    if spec.summary:
        summary_bits.append(_sentence(spec.summary))
    else:
        composed = " ".join(
            p for p in (spec.subject, spec.action, spec.setting, spec.style) if p
        )
        if composed:
            summary_bits.append(_sentence(composed))
    if spec.references:
        kinds = sorted({r.kind for r in spec.references})
        summary_bits.append(
            _sentence(
                f"The target video reuses the supplied {', '.join(kinds)} "
                f"reference material under the retention policy listed below"
            )
        )
    if summary_bits:
        blocks.append("summary:\n" + _summary_tag(spec) + " ".join(summary_bits))

    if spec.references:
        lines = ["retention_analysis:"]
        for ref in spec.references:
            label = ref.label
            policy = ref.retention or "reference"
            detail = _sentence(ref.description) if ref.description else ""
            location = ""
            shots = _shots_mentioning(spec, label)
            if shots:
                location = f" (appears in {', '.join(f'[Shot {n}]' for n in shots)})"
            line = f"{label}{location}: {policy}"
            if detail:
                line += f" - {detail}"
            lines.append(line)
        blocks.append("\n".join(lines))

    opening: list[str] = []
    if spec.style:
        opening.append(_sentence(spec.style))
    if spec.lighting:
        opening.append(_sentence(f"Lighting: {spec.lighting}"))

    shots: list[str] = []
    for index, shot in enumerate(spec.shots, start=1):
        rendered = shot.render(index, is_first=index == 1)
        if rendered:
            shots.append(f"[Shot {index}] {rendered}")
    if not shots and (spec.subject or spec.action):
        shots.append(
            "[Shot 1] " + _sentence(" ".join(p for p in (spec.subject, spec.action) if p))
        )

    description_parts = opening + shots
    if spec.extra:
        description_parts.append(_sentence(spec.extra))
    if description_parts:
        blocks.append("detailed_description:\n" + " ".join(description_parts))

    if spec.soundscape:
        blocks.append("overall_soundscape:\n" + _sentence(spec.soundscape))
    if spec.music:
        blocks.append("non_diegetic_music:\n" + _sentence(spec.music))
    elif spec.references:
        # The guide's examples write N/A rather than omitting the section when
        # the target video has no audience-only score.
        blocks.append("non_diegetic_music:\nN/A")

    return "\n\n".join(blocks).strip()


def compose(spec: PromptSpec) -> str:
    if spec.mode == "r2v":
        return build_ref_prompt(spec)
    return build_base_prompt(spec)


def validate_references(mode, references: Sequence[Reference]) -> list[str]:
    """Return a list of human readable problems; empty means valid."""
    problems: list[str] = []
    counts = {"image": 0, "video": 0, "audio": 0}
    for ref in references:
        if ref.kind not in counts:
            problems.append(f"Unknown reference kind '{ref.kind}'.")
            continue
        counts[ref.kind] += 1

    if counts["image"] > mode.images:
        problems.append(f"{counts['image']} images supplied, the limit is {mode.images}.")
    if counts["video"] > mode.videos:
        problems.append(f"{counts['video']} videos supplied, the limit is {mode.videos}.")
    if counts["audio"] > mode.audio:
        problems.append(f"{counts['audio']} audio clips supplied, the limit is {mode.audio}.")

    total = sum(counts.values())
    if mode.max_total_files and total > mode.max_total_files:
        problems.append(
            f"{total} reference files supplied, the limit is {mode.max_total_files}."
        )

    if mode.requires_reference and total == 0:
        problems.append("Reference mode needs at least one image, video or audio clip.")

    return problems


def build_conditions(mode, references: Sequence[Reference]) -> list[dict]:
    """Translate references into the SGLang ``conditions`` array.

    Roles follow the official request scripts: FL2VA keyframes use
    ``keyframe`` (``frame_index`` 0 for the first, -1 for the last), while
    everything in Ref2VA -- images included -- uses ``reference``.
    """
    conditions: list[dict] = []
    image_count = 0
    for ref in references:
        if not ref.uri:
            continue
        if ref.kind == "image":
            image_count += 1
            if mode.requires_reference:
                conditions.append({"type": "image", "uri": ref.uri,
                                   "role": "reference"})
            else:
                conditions.append({
                    "type": "image",
                    "uri": ref.uri,
                    "role": "keyframe",
                    "frame_index": 0 if image_count == 1 else -1,
                })
        elif ref.kind in ("video", "audio"):
            conditions.append({"type": ref.kind, "uri": ref.uri,
                               "role": "reference"})
    return conditions


def reference_hints(mode) -> list[dict]:
    """Small helper payload for the UI describing the reference slots."""
    hints = []
    for kind, label, limit in (
        ("image", "Picture", mode.images),
        ("video", "Video", mode.videos),
        ("audio", "Audio", mode.audio),
    ):
        if limit:
            hints.append({"kind": kind, "label": label, "limit": limit})
    return hints
