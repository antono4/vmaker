#!/usr/bin/env bash
# Serve MiniMax-H3 locally with SGLang, exposing the /v1/videos API this app
# speaks. Mirrors the deployment in the official model card.
#
#   POST /v1/videos              {"task","prompt","conditions","target","seed"}
#   GET  /v1/videos/{id}         {"status"}
#   GET  /v1/videos/{id}/content mp4
#
# FL2VA (text-to-video, image-to-video) listens on 30010.
# Ref2VA (reference-to-video) needs its own server and listens on 30011.
#
# Usage:
#   ./tools/serve_local.sh --model-path ./models/MiniMax-H3
#   ./tools/serve_local.sh --model-path ./models/MiniMax-H3 --variant ref2va
#   ./tools/serve_local.sh --num-gpus 8 --ulysses-degree 8
set -uo pipefail

MODEL_PATH="MiniMaxAI/MiniMax-H3"
VARIANT="fl2va"
NUM_GPUS=4
ULYSSES=4
PORT=""
HOST="0.0.0.0"
MODE="speed"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --model-path)      MODEL_PATH="$2"; shift 2 ;;
    --variant)         VARIANT="$2";    shift 2 ;;
    --num-gpus)        NUM_GPUS="$2";   shift 2 ;;
    --ulysses-degree)  ULYSSES="$2";    shift 2 ;;
    --port)            PORT="$2";       shift 2 ;;
    --host)            HOST="$2";       shift 2 ;;
    --performance-mode) MODE="$2";      shift 2 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ "$VARIANT" != "fl2va" && "$VARIANT" != "ref2va" ]]; then
  echo "--variant must be fl2va or ref2va" >&2
  exit 2
fi

if [[ -z "$PORT" ]]; then
  if [[ "$VARIANT" == "ref2va" ]]; then PORT=30011; else PORT=30010; fi
fi

if ! command -v sglang >/dev/null 2>&1; then
  cat >&2 <<'EOF'
'sglang' is not installed. Install it with:

  python3 -m pip install "sglang[all]"

The 33B model needs a CUDA GPU with roughly 24 GB VRAM for 768p, or multiple
GPUs with --ulysses-degree sharding. It will not run on CPU.
EOF
  exit 1
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  echo "GPUs visible:"
  nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
  echo
else
  echo "WARNING: nvidia-smi not found. SGLang needs CUDA GPUs." >&2
fi

echo "Serving $VARIANT from $MODEL_PATH"
echo "Endpoint: http://$HOST:$PORT"
echo

exec sglang serve \
  --model-path "$MODEL_PATH" \
  --num-gpus "$NUM_GPUS" \
  --ulysses-degree "$ULYSSES" \
  --performance-mode "$MODE" \
  --host "$HOST" \
  --port "$PORT" \
  --model-variant "$VARIANT"
