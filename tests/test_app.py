"""Tests for the prompt composer, validation, media and the HTTP API.

These exercise real code paths: the composer is pure, the media tests write and
re-read actual files, and the API tests drive the live ASGI app over HTTP.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("H3_DATA_DIR", tempfile.mkdtemp(prefix="h3test-"))

from app import media, modes  # noqa: E402
from app import prompt as prompt_lib  # noqa: E402
from app.prompt import PromptSpec, Reference, Shot  # noqa: E402


# ----------------------------------------------------------------- modes
def test_mode_limits_match_the_model_card():
    t2v = modes.get_mode("t2v")
    assert (t2v.task, t2v.images, t2v.videos, t2v.audio) == ("t2va", 0, 0, 0)

    i2v = modes.get_mode("i2v")
    assert (i2v.task, i2v.images) == ("fl2va", 2)

    r2v = modes.get_mode("r2v")
    assert (r2v.task, r2v.images, r2v.videos, r2v.audio) == ("ref2va", 9, 3, 3)
    assert r2v.max_total_files == 12
    assert (r2v.min_duration, r2v.max_duration) == (4.0, 15.0)


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        modes.get_mode("nope")


# ----------------------------------------------------------- composer: base
def test_base_prompt_has_the_three_required_sections():
    spec = PromptSpec(
        mode="t2v",
        style="Cinematic, live-action, 35mm film",
        setting="a starship bridge",
        shots=[Shot(description="A captain watches the fleet leave.",
                    shot_size="medium wide shot", camera_move="push in",
                    amplitude="slow", speed="steady", start_seconds=0)],
        soundscape="A low resonant hum.",
        music="Space-opera orchestral score.",
    )
    text = prompt_lib.compose(spec)
    assert text.startswith("integrated_multimodal_description: ")
    assert "overall_soundscape: A low resonant hum." in text
    assert "non_diegetic_music: Space-opera orchestral score." in text
    assert "[Shot 1] medium wide shot." in text
    assert "The camera pushes in slow, steady." in text


def test_shot_timestamps_use_timecode_and_stay_inside_the_sentence():
    spec = PromptSpec(
        mode="t2v",
        shots=[
            Shot(description="Opening.", shot_size="wide shot", start_seconds=0),
            Shot(description="The camera cuts to a close-up.",
                 shot_size="close-up", start_seconds=4.5),
        ],
    )
    text = prompt_lib.compose(spec)
    assert "At 00:04.500, close-up." in text
    assert "At 00:04.500, Close-up" not in text
    assert "[Shot 1] wide shot." in text  # first shot carries no timestamp


def test_dialogue_and_on_screen_text_are_rendered():
    spec = PromptSpec(
        mode="t2v",
        shots=[Shot(description="She speaks.", start_seconds=0,
                    dialogue=["<d>[English] The fleet is gone.</d>"],
                    on_screen_text=["HYPERSPACE"])],
    )
    text = prompt_lib.compose(spec)
    assert "The speaker delivers <d>[English] The fleet is gone.</d>." in text
    assert 'On-screen text reads "HYPERSPACE".' in text


def test_bare_dialogue_gets_wrapped_in_d_tags():
    spec = PromptSpec(mode="t2v",
                      shots=[Shot(description="x", dialogue=["hello there"])])
    assert "<d>hello there</d>" in prompt_lib.compose(spec)


def test_static_camera_is_described_as_held():
    spec = PromptSpec(mode="t2v", shots=[Shot(description="x", camera_move="static")])
    assert "The camera holds a static shot." in prompt_lib.compose(spec)


def test_i2v_prompt_references_the_first_frame():
    spec = PromptSpec(
        mode="i2v",
        references=[Reference(kind="image", label="<Picture 1>", uri="x.png")],
        shots=[Shot(description="She turns toward the window.", start_seconds=0)],
    )
    text = prompt_lib.compose(spec)
    assert "at 0.00 seconds into the target video" in text
    assert "<Picture 1> (from [Shot 1]) is fully referenced" in text


def test_fl2va_prompt_names_both_frames():
    spec = PromptSpec(
        mode="i2v",
        references=[Reference(kind="image", label="<Picture 1>", uri="a.png"),
                    Reference(kind="image", label="<Picture 2>", uri="b.png")],
        shots=[Shot(description="A slow dissolve.", start_seconds=0)],
    )
    text = prompt_lib.compose(spec)
    assert "the first frame fully references <Picture 1>" in text
    assert "the final frame fully references <Picture 2>" in text


def test_empty_spec_produces_an_empty_prompt():
    assert prompt_lib.compose(PromptSpec(mode="t2v")).strip() == ""


# ------------------------------------------------------------ composer: ref
def test_ref_prompt_has_all_six_sections_in_order():
    refs = [
        Reference(kind="image", label="<Picture 1>",
                  description="the young man in a bright pink suit",
                  retention="fully_preserved"),
        Reference(kind="audio", label="<Audio 1>",
                  description="a spoken male voiceover",
                  retention="reference"),
    ]
    spec = PromptSpec(
        mode="r2v",
        subject="the young man",
        action="stands in a sunlit pasture holding a black lamb",
        references=refs,
        shots=[Shot(description="<Picture 1> speaks softly.",
                    shot_size="medium shot", start_seconds=0)],
        soundscape="Music overlaid with calm male dialogue.",
        music="A sustained atmospheric bed.",
    )
    text = prompt_lib.compose(spec)
    order = ["subject_definitions:", "summary:", "retention_analysis:",
             "detailed_description:", "overall_soundscape:", "non_diegetic_music:"]
    positions = [text.index(section) for section in order]
    assert positions == sorted(positions), "sections are out of order"
    assert "<Picture 1> is the young man in a bright pink suit." in text
    assert "<Picture 1> (appears in [Shot 1]): fully_preserved" in text
    assert "<Audio 1>: reference" in text


def test_ref_mode_auto_labels_when_missing():
    spec = PromptSpec(
        mode="r2v",
        references=[Reference(kind="image", description="a red bicycle"),
                    Reference(kind="video", description="a spinning wheel")],
    )
    text = prompt_lib.compose(spec)
    assert "<Picture 1> is a red bicycle." in text
    assert "<Video 1> is a spinning wheel." in text


def test_ref_summary_carries_the_relationship_tag():
    spec = PromptSpec(
        mode="r2v", subject="the young man", action="holds a black lamb",
        references=[Reference(kind="image", label="<Picture 1>",
                              description="a man in a pink suit"),
                    Reference(kind="audio", label="<Audio 1>",
                              description="a male voiceover", retention="reference")],
    )
    text = prompt_lib.compose(spec)
    assert "summary:\n[reference generation + image reference + audio reference]" in text


def test_ref_retention_analysis_notes_which_shots_use_a_label():
    spec = PromptSpec(
        mode="r2v",
        references=[Reference(kind="image", label="<Picture 1>",
                              description="a red bicycle")],
        shots=[Shot(description="<Picture 1> rolls past.", start_seconds=0),
               Shot(description="A wide shot of the street.", start_seconds=3)],
    )
    text = prompt_lib.compose(spec)
    assert "<Picture 1> (appears in [Shot 1]): fully_preserved - a red bicycle." in text


def test_ref_music_section_is_na_when_no_score_is_supplied():
    spec = PromptSpec(
        mode="r2v", subject="a subject",
        references=[Reference(kind="image", label="<Picture 1>")],
    )
    assert "non_diegetic_music:\nN/A" in prompt_lib.compose(spec)


# -------------------------------------------------------------- validation
def test_image_limit_is_enforced():
    refs = [Reference(kind="image", label=f"<Picture {i}>") for i in range(1, 11)]
    problems = prompt_lib.validate_references(modes.get_mode("r2v"), refs)
    assert any("images supplied, the limit is 9" in p for p in problems)


def test_total_file_cap_allows_exactly_twelve():
    """9 images + 3 videos is exactly the cap of 12, so it passes."""
    refs = ([Reference(kind="image", label=f"<Picture {i}>") for i in range(1, 10)]
            + [Reference(kind="video", label=f"<Video {i}>") for i in range(1, 4)])
    assert prompt_lib.validate_references(modes.get_mode("r2v"), refs) == []


def test_total_file_cap_rejects_thirteen():
    refs = ([Reference(kind="image", label=f"<Picture {i}>") for i in range(1, 10)]
            + [Reference(kind="video", label=f"<Video {i}>") for i in range(1, 4)]
            + [Reference(kind="audio", label="<Audio 1>")])
    problems = prompt_lib.validate_references(modes.get_mode("r2v"), refs)
    assert any("limit is 12" in p for p in problems)


def test_ref_mode_requires_at_least_one_reference():
    problems = prompt_lib.validate_references(modes.get_mode("r2v"), [])
    assert any("at least one" in p for p in problems)


def test_valid_reference_set_passes():
    refs = [Reference(kind="image", label="<Picture 1>"),
            Reference(kind="video", label="<Video 1>"),
            Reference(kind="audio", label="<Audio 1>")]
    assert prompt_lib.validate_references(modes.get_mode("r2v"), refs) == []


# -------------------------------------------------------------- conditions
def test_conditions_map_fl2va_images_to_keyframes():
    refs = [
        Reference(kind="image", label="<Picture 1>", uri="https://x/1.png"),
        Reference(kind="image", label="<Picture 2>", uri="https://x/2.png"),
    ]
    conditions = prompt_lib.build_conditions(modes.get_mode("i2v"), refs)
    assert conditions[0] == {"type": "image", "uri": "https://x/1.png",
                             "role": "keyframe", "frame_index": 0}
    assert conditions[1]["frame_index"] == -1


def test_conditions_map_ref2va_inputs_to_references():
    """The official ref2va script uses role 'reference' for every input,
    images included -- see upstream/scripts/reproducible-768p-ref2va-request.sh."""
    refs = [
        Reference(kind="image", label="<Picture 1>", uri="https://x/1.png"),
        Reference(kind="video", label="<Video 1>", uri="https://x/v.mp4"),
        Reference(kind="audio", label="<Audio 1>", uri="https://x/a.mp3"),
    ]
    conditions = prompt_lib.build_conditions(modes.get_mode("r2v"), refs)
    assert conditions == [
        {"type": "image", "uri": "https://x/1.png", "role": "reference"},
        {"type": "video", "uri": "https://x/v.mp4", "role": "reference"},
        {"type": "audio", "uri": "https://x/a.mp3", "role": "reference"},
    ]


def test_conditions_skip_references_without_a_uri():
    refs = [Reference(kind="image", label="<Picture 1>", uri="")]
    assert prompt_lib.build_conditions(modes.get_mode("i2v"), refs) == []


# ------------------------------------------------------------------- media
def test_wav_roundtrip_writes_readable_stereo():
    audio = np.stack([np.sin(np.arange(3200) / 10.0), np.sin(np.arange(3200) / 20.0)])
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "a.wav"
        media.write_wav(audio, path)
        with wave.open(str(path), "rb") as handle:
            assert handle.getnchannels() == 2
            assert handle.getframerate() == media.SAMPLE_RATE
            assert handle.getnframes() == 3200


def test_demo_audio_is_deterministic_and_bounded():
    first = media.audio_from_prompt("a starship bridge", 1.0, seed=5)
    second = media.audio_from_prompt("a starship bridge", 1.0, seed=5)
    assert first.shape == second.shape
    assert (first == second).all()
    assert first.shape[0] == 2
    assert abs(first).max() <= 1.0


def test_an_encoder_is_available_in_this_environment():
    assert media.ffmpeg_path() is not None, "imageio-ffmpeg should provide a binary"
    assert media.has_encoder()


def test_write_video_produces_a_playable_file_with_audio():
    frames = [np.full((96, 160, 3), value, dtype=np.uint8) for value in (10, 90, 170)]
    audio = media.audio_from_prompt("test", 0.5, seed=1)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "clip.mp4"
        media.write_video(frames, path, fps=6, audio=audio)
        assert path.exists() and path.stat().st_size > 0

        probe = subprocess.run(
            [media.ffmpeg_path(), "-hide_banner", "-i", str(path)],
            capture_output=True,
        )
        info = probe.stderr.decode(errors="replace")
        assert "Video: h264" in info
        assert "Audio: aac" in info
        assert "160x96" in info


def test_write_video_without_frames_raises():
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(RuntimeError):
            media.write_video([], Path(tmp) / "x.mp4")


# ---------------------------------------------------------------- adapters
@pytest.fixture(scope="module")
def landscape_render():
    """One 1-second 16:9 demo render shared by the assertions below.

    Rendering is the slow part of this suite, so it happens once.
    """
    from app.adapters import GenerationRequest, get

    request = GenerationRequest(
        mode="t2v", task="t2va", prompt="a lone cyclist in a yellow raincoat",
        duration=1.0, aspect_ratio="16:9", short_edge=768, seed=3,
        shots=[{"description": "pedals toward the camera"}],
    )
    backend = get("demo")
    ok, reason = backend.available()
    assert ok, reason
    return backend.generate("t1", request, lambda *_a: None)


def test_demo_backend_renders_a_real_mp4(landscape_render):
    result = landscape_render
    assert Path(result.video_path).exists()
    assert Path(result.video_path).stat().st_size > 1000
    assert Path(result.poster_path).exists()
    assert result.meta["watermarked"] is True
    assert result.meta["frames"] == 24
    # 768 is the short edge, so 16:9 becomes 1364x768 (even dimensions for x264)
    assert result.meta["resolution"] == "1364x768"


def test_demo_output_is_playable_h264_with_stereo_aac(landscape_render):
    probe = subprocess.run(
        [media.ffmpeg_path(), "-hide_banner", "-i", landscape_render.video_path],
        capture_output=True,
    )
    info = probe.stderr.decode(errors="replace")
    assert "Video: h264" in info
    assert "Audio: aac" in info
    assert "1364x768" in info
    assert "24 fps" in info
    assert "32000 Hz, stereo" in info


def test_demo_backend_honours_the_9_by_16_short_edge():
    from app.adapters import GenerationRequest, get

    request = GenerationRequest(
        mode="t2v", task="t2va", prompt="vertical", duration=1.0,
        aspect_ratio="9:16", short_edge=768, seed=1, shots=[{"description": "x"}],
    )
    result = get("demo").generate("t2", request, lambda *_a: None)
    assert result.meta["resolution"] == "768x1364"


def test_backend_registry_exposes_three_backends():
    from app.adapters import ORDER, all_backends

    assert ORDER == ("demo", "local", "api")
    infos = [b.info() for b in all_backends()]
    assert {i["name"] for i in infos} == {"demo", "local", "api"}
    for info in infos:
        assert set(info) >= {"name", "label", "available", "reason", "requires"}


def test_unknown_backend_raises():
    from app.adapters import get
    from app.adapters.base import BackendError

    with pytest.raises(BackendError):
        get("does-not-exist")


def test_progress_reporter_raises_once_canceled():
    from app.adapters.base import Canceled, ProgressReporter

    seen: list[tuple[float, str]] = []
    reporter = ProgressReporter(lambda v, s: seen.append((v, s)))
    reporter.report(0.5, "halfway")
    assert seen == [(0.5, "halfway")]

    reporter.cancel()
    assert reporter.canceled is True
    with pytest.raises(Canceled):
        reporter.report(0.9, "almost")


def test_demo_render_stops_early_when_canceled():
    import threading
    import time as time_module

    from app.adapters import GenerationRequest, get
    from app.adapters.base import Canceled, ProgressReporter

    request = GenerationRequest(
        mode="t2v", task="t2va", prompt="cancel me", duration=10.0,
        aspect_ratio="16:9", short_edge=768, seed=1, shots=[{"description": "x"}],
    )
    reporter = ProgressReporter(lambda *_a: None)
    threading.Timer(2.0, reporter.cancel).start()

    started = time_module.time()
    with pytest.raises(Canceled):
        get("demo").generate("cancel-me", request, reporter)
    # a 10s clip at 24fps takes well over a minute to render
    assert time_module.time() - started < 30


def test_local_backend_target_payload_matches_the_official_schema():
    from app.adapters import GenerationRequest

    request = GenerationRequest(mode="i2v", task="fl2va", prompt="p", duration=8.0,
                                aspect_ratio="auto", short_edge=768, seed=0)
    assert request.target() == {"short_edge": 768, "aspect_ratio": "auto",
                                "duration_seconds": 8.0}


def test_local_backend_routes_ref2va_to_the_second_endpoint():
    from app.adapters.local import LocalBackend

    backend = LocalBackend()
    assert backend.endpoint_for("fl2va").endswith("30010")
    assert backend.endpoint_for("ref2va").endswith("30011")


# --------------------------------------------------------------- job store
def test_job_store_marks_interrupted_jobs_as_failed_on_reload():
    from app.store import JobStore

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "jobs.json"
        store = JobStore(path)
        job = store.create(mode="t2v", backend="demo", task="t2va", prompt="hello")
        store.update(job.id, status="running", progress=0.5)

        reloaded = JobStore(path).get(job.id)
        assert reloaded is not None
        assert reloaded.status == "failed"
        assert "restart" in reloaded.error


def test_job_store_delete_removes_the_record():
    from app.store import JobStore

    with tempfile.TemporaryDirectory() as tmp:
        store = JobStore(Path(tmp) / "jobs.json")
        job = store.create(mode="t2v", backend="demo", task="t2va", prompt="x")
        assert store.delete(job.id) is True
        assert store.get(job.id) is None
        assert store.delete(job.id) is False


# --------------------------------------------------------------------- API
@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_health_and_metadata_endpoints(client):
    assert client.get("/healthz").json()["status"] == "ok"
    assert len(client.get("/api/backends").json()["backends"]) == 3

    meta = client.get("/api/modes").json()
    assert [m["key"] for m in meta["modes"]] == ["t2v", "i2v", "r2v"]
    assert meta["model"]["id"] == "MiniMaxAI/MiniMax-H3"
    assert meta["model"]["max_duration"] == 15


def test_prompt_preview_endpoint_composes_and_validates(client):
    response = client.post("/api/prompt/preview", json={
        "mode": "r2v",
        "subject": "the young man",
        "shots": [{"description": "He speaks.", "start_seconds": 0}],
        "references": [{"kind": "image", "label": "<Picture 1>",
                        "description": "a man in a pink suit",
                        "retention": "fully_preserved"}],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["task"] == "ref2va"
    assert "subject_definitions:" in body["prompt"]
    assert body["problems"] == []


def test_prompt_preview_rejects_an_unknown_mode(client):
    assert client.post("/api/prompt/preview", json={"mode": "nope"}).status_code == 400


def test_generate_rejects_an_empty_prompt(client):
    response = client.post("/api/generate", json={"mode": "t2v", "backend": "demo"})
    assert response.status_code == 400
    assert "empty" in response.json()["detail"]


def test_generate_rejects_too_many_references(client):
    response = client.post("/api/generate", json={
        "mode": "r2v", "backend": "demo",
        "references": [{"kind": "image", "label": f"<Picture {i}>"}
                       for i in range(1, 12)],
    })
    assert response.status_code == 400
    assert "limit is 9" in response.json()["detail"]


def test_generate_clamps_duration_to_the_mode_range(client):
    high = client.post("/api/generate", json={
        "mode": "t2v", "backend": "demo", "duration": 900,
        "subject": "a lighthouse in a storm",
    })
    assert high.json()["job"]["duration"] == 15.0

    low = client.post("/api/generate", json={
        "mode": "t2v", "backend": "demo", "duration": 0.1,
        "subject": "a lighthouse in a storm",
    })
    assert low.json()["job"]["duration"] == 4.0


def test_generate_falls_back_to_a_valid_aspect_ratio(client):
    response = client.post("/api/generate", json={
        "mode": "t2v", "backend": "demo", "aspect_ratio": "99:1",
        "subject": "a paper boat",
    })
    assert response.json()["job"]["aspect_ratio"] == "16:9"


def test_generate_accepts_a_reference_upload(client):
    response = client.post(
        "/api/generate",
        data={"payload": json.dumps({
            "mode": "r2v", "backend": "demo", "duration": 4, "subject": "a subject",
            "references": [{"kind": "image", "label": "<Picture 1>",
                            "description": "a reference", "retention": "reference"}],
        })},
        files={"file_0": ("ref.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, "image/png")},
    )
    assert response.status_code == 200
    refs = response.json()["job"]["meta"]["references"]
    assert refs[0]["filename"] == "ref.png"
    assert refs[0]["uri"].startswith("/media/uploads/")


def test_job_lookup_and_delete(client):
    created = client.post("/api/generate", json={
        "mode": "t2v", "backend": "demo", "duration": 4,
        "subject": "a paper boat on a puddle",
    }).json()["job"]

    fetched = client.get(f"/api/jobs/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["job"]["id"] == created["id"]

    assert client.delete(f"/api/jobs/{created['id']}").status_code == 200
    assert client.get(f"/api/jobs/{created['id']}").status_code == 404


def test_regenerate_2k_without_a_key_is_a_clear_error(client):
    created = client.post("/api/generate", json={
        "mode": "t2v", "backend": "demo", "duration": 4, "subject": "x",
    }).json()["job"]
    response = client.post(f"/api/jobs/{created['id']}/regenerate-2k")
    assert response.status_code == 400
    assert "MINIMAX_API_KEY" in response.json()["detail"]
    assert "not part of the open-source release" in response.json()["detail"]


def test_prompt_expand_without_a_key_explains_the_hosted_dependency(client):
    response = client.post("/api/prompt/expand", json={"text": "a short idea"})
    assert response.status_code == 400
    assert "MINIMAX_API_KEY" in response.json()["detail"]


def test_index_page_serves_the_studio(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "MiniMax H3 Video Maker" in response.text
