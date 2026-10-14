# MiniMax H3 Video Maker

A self-hosted studio for **MiniMax-H3**, the 33B omni-modal video model. It
generates video with **native stereo audio** in three modes, and it writes the
prompt format H3 actually expects instead of hoping a generic prompt will do.

| Mode | Task | Inputs | What it makes |
| --- | --- | --- | --- |
| Text to Video | `t2va` | prompt only | a clip from a description |
| Image to Video | `fl2va` | 1 image (first frame) or 2 (first + last) | a clip that starts from your frame(s) |
| Reference to Video | `ref2va` | up to 9 images, 3 videos, 3 audio clips | a clip that reuses subjects, style and voice |

Everything runs behind one FastAPI app with a browser UI, a prompt composer that
follows the official H3-Context-IR guide, and three interchangeable backends.

## Landing page

`index.html` at the repo root is a static overview page. It is separate from the
app UI, which lives at `app/static/index.html` and is served by FastAPI at `/`.
Open the landing page directly in a browser, or enable GitHub Pages on `main`
with the root folder selected.

## Quick start

```bash
git clone <this repo> && cd <this repo>
./run.sh
# open http://127.0.0.1:12000
```

`run.sh` installs the dependencies on first run. The app starts with the
**demo backend**, which renders a real, playable, watermarked mp4 with stereo
audio on the CPU. That needs no GPU and no credentials, so you can click through
the whole flow -- compose, submit, watch progress, download -- immediately.

To generate real video you need a GPU and the H3 weights. See
[Backends](#backends).

## Backends

The app ships three adapters. Pick one per request in the UI; the app only
offers the ones that are actually usable in your environment.

### 1. Local H3 server (SGLang / vLLM) -- real generation

This is the official self-hosting path. It needs a CUDA GPU (roughly 24 GB VRAM
for 768p, or several GPUs with `--ulysses-degree` sharding).

```bash
./tools/download_model.sh                  # ~85 GB, fl2va, diffusers layout
./tools/serve_local.sh --model-path ./models/MiniMax-H3
```

Then point the app at it and restart:

```bash
export H3_LOCAL_BASE_URL=http://127.0.0.1:30010      # fl2va: t2v and i2v
export H3_LOCAL_BASE_URL_REF=http://127.0.0.1:30011  # ref2va: r2v
```

Ref2VA runs on a **second** server on a different port, so start a second
instance with `--variant ref2va`.

### 2. MiniMax Open Platform API -- real generation, no GPU

```bash
export MINIMAX_API_KEY=...
export MINIMAX_API_BASE=https://api.minimax.io   # or https://api.minimaxi.com
./run.sh
```

This backend also enables two hosted-only extras in the UI: **Expand with
H3-Context-IR API**, which rewrites a short idea into a full prompt, and
**Regenerate to 2K**, which upscales a finished 768p clip. Local files cannot
be uploaded to this API, so reference inputs must already be public URLs.

### 3. Demo backend -- no GPU, no key

Renders a watermarked placeholder on the CPU so you can verify the studio end to
end. It is clearly marked in the output and in the job metadata; it is never
model output.

## Prompting: the H3-Context-IR format

H3 does not take a loose sentence. It takes a structured description, and the
quality difference is large. The composer in this app builds that structure from
form fields, and you can see the result live before you render.

Text/Image to Video (`t2va`, `fl2va`) produces three sections:

```text
integrated_multimodal_description: <style>. The scene is set in <setting>.
Lighting: <lighting>. [Shot 1] <shot size>. The camera pushes in slow, steady.
<what happens>. The speaker delivers <d>[English] <line>.</d> On-screen text
reads "OPEN 24 HOURS".
overall_soundscape: <ambience and physical sounds>
non_diegetic_music: <audience-only score>
```

Reference to Video (`ref2va`) produces six sections, in this order:

```text
subject_definitions:    what each <Picture N>, <Video N>, <Audio N> denotes
summary:                [relationship tag] what the target video shows
retention_analysis:     <Label> (appears in [Shot N]): fully_preserved - ...
detailed_description:   [Shot N] ... prose that uses the labels
overall_soundscape:     ambience and physical sounds
non_diegetic_music:     audience-only score, or N/A
```

The composer handles the details the guide is picky about:

- **Shot timestamps** appear only from the second shot on, as
  `At 00:04.500, close-up.`
- **Camera moves** are written as motion + amplitude + speed, e.g.
  `The camera pushes in slow, steady.` A static shot is
  `The camera holds a static shot.`
- **Dialogue** is wrapped in `<d>[lang] ...</d>` tags; bare lines get the tag
  added for you.
- **Keyframes** are described as first/final frame in `fl2va` and as plain
  references in `ref2va`.
- **Retention** uses the guide's vocabulary: `fully_preserved`,
  `partially_preserved`, `fully_copy`, `partially_copy`, `reference`.

The two upstream guides are vendored in [`docs/`](docs) so you can read the
source of truth offline. Run `./tools/fetch_upstream.sh` to refresh them.

If you already have a finished prompt, paste it into **Raw prompt override** and
the composer is bypassed.

## How a request flows

```
browser form ─► POST /api/generate ─► compose prompt + build conditions
                                  ─► pick backend ─► background job
                                  ─► poll GET /api/jobs/{id} ─► mp4 + poster
```

Jobs run in a background thread so the UI stays responsive. Progress, stage and
errors stream into the gallery. **Delete** on a running job cancels it: the
render loop checks a cancel flag between frames, so it stops within a frame or
two rather than running to completion.

The UI has four panels: **Compose** (mode, scene, shots, references, audio),
**Render** (backend, duration, resolution, seed, Turbo LoRA), **Output** (the
player), and **Library** (past renders, newest first).

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `H3_PORT` | `12000` | HTTP port |
| `H3_HOST` | `0.0.0.0` | bind address |
| `H3_DATA_DIR` | `./data` | outputs, uploads, `jobs.json` |
| `H3_DEFAULT_BACKEND` | `demo` | preselected backend |
| `H3_LOCAL_BASE_URL` | `http://127.0.0.1:30010` | fl2va server |
| `H3_LOCAL_BASE_URL_REF` | `http://127.0.0.1:30011` | ref2va server |
| `MINIMAX_API_BASE` | `https://api.minimax.io` | hosted API root |
| `MINIMAX_API_KEY` | -- | enables the API backend |
| `H3_MAX_UPLOAD_MB` | `64` | per-file upload cap |
| `H3_READ_TIMEOUT` | `600` | seconds to wait for a render |

## API

Interactive docs are at `/docs` when the app is running.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/healthz` | liveness, encoder status, job count |
| `GET` | `/api/backends` | available backends and why each is or is not usable |
| `GET` | `/api/modes` | modes, limits, shot sizes, camera moves, retention policies |
| `POST` | `/api/prompt/preview` | compose a prompt and validate it, without rendering |
| `POST` | `/api/prompt/expand` | rewrite a short idea (needs `MINIMAX_API_KEY`) |
| `POST` | `/api/generate` | submit a render; JSON or multipart with uploads |
| `GET` | `/api/jobs` | list jobs |
| `GET` | `/api/jobs/{id}` | one job |
| `DELETE` | `/api/jobs/{id}` | cancel a running job or delete a finished one |
| `POST` | `/api/jobs/{id}/regenerate-2k` | upscale to 2K (needs `MINIMAX_API_KEY`) |

Reference files are uploaded as `file_0`, `file_1`, ... and matched to the
`references` array by index. The JSON body goes in the `payload` form field.

## Layout

```
app/
  main.py          FastAPI routes, job orchestration, uploads
  modes.py         t2v / i2v / r2v definitions and limits
  prompt.py        H3-Context-IR composer, validation, conditions
  media.py         ffmpeg discovery, mp4 muxing, synthetic audio
  store.py         job persistence and restart recovery
  config.py        environment-driven settings
  adapters/        base contract, demo, local (SGLang), minimax_api
  static/          index.html, styles.css, app.js
docs/              the two official prompt-writing guides
tools/             fetch_upstream.sh, download_model.sh, serve_local.sh
upstream/          vendored model card, request scripts, community wrapper
tests/             test_app.py
```

Adding a backend means writing one module in `app/adapters/` and adding it to
the registry in `app/adapters/__init__.py`. The contract is a single
`generate(job_id, request, progress)` method.

## Tests

```bash
python3 -m pytest tests/ -q
```

The suite drives the real ASGI app over HTTP, writes and re-reads real media
files, and renders a real mp4 with the demo backend. It does not mock the code
under test. Rendering is the slow part, so the shared 16:9 clip is rendered once
per module.

## Notes and limits

- **Turbo LoRA.** The community ComfyUI wrapper advertises
  `MiniMaxAI/MiniMax-H3-Turbo-Lora`. That repository does not exist on Hugging
  Face -- the API answers `401` -- so there is no artefact to download. The app
  exposes the LoRA only as a label describing what your H3 server has loaded; it
  does not fetch or apply one itself.
- **2K regeneration** is a hosted service (`H3-Regenerate-2K`). It is not part
  of the open-source release, which is why the button needs an API key.
- **Duration** is clamped to 4-15 s per the model card, and the UI shows the
  clamp rather than silently changing your request.
- **Resolution** follows the model card's `short_edge` semantics: 768p keeps the
  short edge at 768, so 16:9 becomes 1364x768 and 9:16 becomes 768x1364.
- The demo renderer is single-threaded NumPy. A 4-second clip takes roughly 20
  seconds on 4 cores; long clips take proportionally longer.

## Credits

- Model: [MiniMaxAI/MiniMax-H3](https://huggingface.co/MiniMaxAI/MiniMax-H3)
- Community ComfyUI wrapper:
  [minimaxh3turbo/MiniMax-H3-Turbo-LoRA-ComfyUI](https://github.com/minimaxh3turbo/MiniMax-H3-Turbo-LoRA-ComfyUI)
- Prompt guides: the two `VIDEO_PROMPT_WRITING_GUIDE_*.md` files in `docs/`
