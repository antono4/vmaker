# AGENTS.md

Repository knowledge for the MiniMax H3 Video Maker.

## What this is

A FastAPI app that wraps MiniMax-H3 (33B omni-modal, video + native stereo
audio) behind a browser UI. Three interchangeable backends: `demo` (CPU
renderer), `local` (self-hosted SGLang/vLLM), `api` (MiniMax Open Platform).

## Commands

```bash
python3 -m pytest tests/ -q          # full suite, ~8s
python3 -m pytest tests/ -q -k prompt # fast subset
./run.sh                             # start on :12000, installs deps if missing
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 12000
```

`pytest` is installed in `~/.local/bin`, which is **not** on `PATH`. Always use
`python3 -m pytest`, never bare `pytest`. Do not pass `--timeout`; the
`pytest-timeout` plugin is not installed and the flag is rejected.

## Environment gotcha

The runtime can reset between turns and wipe `~/.local/lib/python3.13/...`.
If imports suddenly fail with `ModuleNotFoundError: No module named 'numpy'`,
reinstall: `python3 -m pip install -r requirements.txt pytest`.

## Prompt format (the part worth getting right)

H3 does not take loose prose. Two shapes, both in `app/prompt.py`:

- `t2va` / `fl2va` -> `build_base_prompt`: `integrated_multimodal_description`,
  `overall_soundscape`, `non_diegetic_music`
- `ref2va` -> `build_ref_prompt`: `subject_definitions`, `summary`,
  `retention_analysis`, `detailed_description`, `overall_soundscape`,
  `non_diegetic_music` (in that order)

Rules encoded in the composer, all from the vendored guides in `docs/`:

- Shot timestamps only from shot 2 onward, formatted `At 00:04.500,`
- Camera written as motion + amplitude + speed: "pushes in slow, steady"
- Dialogue wrapped in `<d>[lang] ...</d>`; bare lines get wrapped
- Reference labels (`<Picture N>` / `<Video N>` / `<Audio N>`) keep one meaning
  across all six sections
- `retention_analysis` notes shots that use a label and uses the guide's
  vocabulary (`fully_preserved`, `partially_copy`, `reference`, ...)
- `summary` opens with a bracketed tag, e.g. `[reference generation + image
  reference]`
- `non_diegetic_music` is written as `N/A` rather than omitted in ref mode

When changing composer output, update `tests/test_app.py` expectations *and*
re-check against `docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md` section 7, which
has a complete worked example.

## Condition roles (verified against upstream scripts)

- `fl2va`: image -> `role: "keyframe"`, `frame_index: 0`; a second image gets
  `frame_index: -1` (last frame)
- `ref2va`: image -> `role: "reference"` (no `frame_index`)

## Sizing

The model card uses **`short_edge`**, not width/height. 768p keeps the short
edge at 768, so 16:9 -> 1364x768 and 9:16 -> 768x1364. `app/main.py` passes
`short_edge` as 768 for `768p` and 1440 for `2k`; `app/adapters/demo.py`
derives width/height from it. Do not "fix" 1364x768 to 1280x720.

## Cancellation

Renders run in a worker thread via `asyncio.to_thread`, which cannot be
interrupted from outside. Cancellation is cooperative:

- `ProgressReporter` (in `app/adapters/base.py`) carries a cancel flag
- Backends call `check_canceled(progress)` inside their loops
- `DELETE /api/jobs/{id}` calls `reporter.cancel()` **before** `task.cancel()`
- `lifespan` in `app/main.py` cancels reporters and drains `RUNNING` on shutdown

`ProgressFn` stays a plain callable so tests can pass a bare function;
`check_canceled` no-ops when the callable has no `check` method.

Without the shutdown drain, any test that submits a job hangs in teardown until
the render finishes (this cost ~5 minutes before it was fixed).

## Demo renderer performance

`app/adapters/demo.py` is the CPU renderer. It builds the smooth field (blobs,
vignette, light sweep) on a coarse ~320px grid and scales it up, so only the
grain and tint touch every pixel. A 10s 768p clip takes ~23s on 4 cores.
Float32 throughout; float64 is roughly twice as slow for no visible gain.
Grain is skipped on frames that get a full-canvas overlay.

## Backend contract

Adding a backend = one module in `app/adapters/` plus an entry in
`_REGISTRY` in `app/adapters/__init__.py`. The contract is a single
`generate(job_id, request, progress) -> GenerationResult`.

## Upstream provenance

`tools/fetch_upstream.sh` vendors the model card, prompt guides and request
scripts into `upstream/`. `upstream/community-comfyui/` is the third-party
ComfyUI wrapper from the source repo.

The Turbo LoRA advertised by that wrapper (`MiniMaxAI/MiniMax-H3-Turbo-Lora`)
does **not** exist on Hugging Face -- `GET /api/models/MiniMaxAI/MiniMax-H3-Turbo-Lora`
returns 401 while `MiniMaxAI/MiniMax-H3` returns 200. The UI exposes it as a
label only and never downloads it. Do not add a download step for it.

## Two index.html files, do not confuse them

- `index.html` (repo root) — static landing page for GitHub Pages. Self-contained:
  inline CSS, no JS, no build step, no dependency on the app.
- `app/static/index.html` — the actual studio UI, served by FastAPI at `/`.

The landing page reuses the palette from `app/static/styles.css` but duplicates
the tokens, since it must stand alone.

GitHub Pages is enabled on `main`, root folder. The live page is
`https://antono4.github.io/vmaker/`, and it is also set as the repo homepage.
Pages uses the legacy builder, so a push to `main` republishes it; check
`GET /repos/antono4/vmaker/pages/builds/latest` for the build status.

## Remote

Pushed to `https://github.com/antono4/vmaker` (public, default branch `main`).
The local repo was initialised here, so `main` is the only branch.

`GITHUB_TOKEN` is **not** set in this environment. The working credential is
`GH_DISPATCH_TOKEN` (authenticates as `antono4`, has admin on the repo). Use it
for `curl` against the API and for the push URL, then reset the remote to the
plain URL so the token is not left in `.git/config`.

## Tests

`tests/test_app.py` drives the real ASGI app over HTTP and writes real media
files; nothing is mocked. The slow part is rendering, so the shared 16:9 clip is
a module-scoped fixture (`landscape_render`). Keep new render tests on small
durations (4s) or reuse the fixture.
