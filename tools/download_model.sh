#!/usr/bin/env bash
# Download the MiniMax-H3 weights you need.
#
# The full repository is ~498 GB because it ships the original checkpoint and
# the diffusers conversion side by side, for two task families. Scope the
# download to what you actually run:
#
#   fl2va only, diffusers layout   ~85 GB   (text-to-video, image-to-video)
#   ref2va only, diffusers layout  ~85 GB   (reference-to-video)
#   both, original layout         ~400 GB   (SGLang / vLLM serving)
#
# Usage:
#   ./tools/download_model.sh                       # fl2va, diffusers layout
#   ./tools/download_model.sh --variant ref2va
#   ./tools/download_model.sh --layout original --variant both
#   ./tools/download_model.sh --dest /mnt/models/MiniMax-H3
set -uo pipefail

MODEL_ID="MiniMaxAI/MiniMax-H3"
DEST="./models/MiniMax-H3"
VARIANT="fl2va"
LAYOUT="diffusers"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --variant) VARIANT="$2"; shift 2 ;;
    --layout)  LAYOUT="$2";  shift 2 ;;
    --dest)    DEST="$2";    shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ "$VARIANT" != "fl2va" && "$VARIANT" != "ref2va" && "$VARIANT" != "both" ]]; then
  echo "--variant must be fl2va, ref2va or both" >&2
  exit 2
fi
if [[ "$LAYOUT" != "diffusers" && "$LAYOUT" != "original" ]]; then
  echo "--layout must be diffusers or original" >&2
  exit 2
fi

if ! command -v hf >/dev/null 2>&1; then
  echo "The 'hf' CLI is missing. Install it with:"
  echo "  python3 -m pip install -U 'huggingface_hub[cli]'"
  echo
  echo "Falling back to huggingface-cli if present..."
  if command -v huggingface-cli >/dev/null 2>&1; then
    HFC="huggingface-cli download"
  else
    exit 1
  fi
else
  HFC="hf download"
fi

# Task-family subdirectories, matching the repo layout.
if [[ "$LAYOUT" == "original" ]]; then
  case "$VARIANT" in
    fl2va)  INCLUDE=("model_index.json" "FL2VA/*") ;;
    ref2va) INCLUDE=("model_index.json" "Ref2VA/*") ;;
    both)   INCLUDE=("model_index.json" "FL2VA/*" "Ref2VA/*") ;;
  esac
else
  # The diffusers layout lives at the repository root for fl2va and under
  # Ref2VA/ for ref2va. model_index.json selects the components.
  case "$VARIANT" in
    fl2va)
      INCLUDE=("model_index.json" "modular_model_index.json" "transformer/*" \
               "transformer_ref/*" "vae/*" "audio_vae/*" "scheduler/*" \
               "audio_scheduler/*" "text_encoder/*" "tokenizer/*" "processor/*") ;;
    ref2va|both)
      INCLUDE=("model_index.json" "Ref2VA/*") ;;
  esac
fi

echo "Model    : $MODEL_ID"
echo "Variant  : $VARIANT"
echo "Layout   : $LAYOUT"
echo "Dest     : $DEST"
echo "Patterns : ${INCLUDE[*]}"
echo
echo "This can take a long time. Resume is automatic."
echo

mkdir -p "$DEST"
$HFC "$MODEL_ID" --include "${INCLUDE[@]}" --local-dir "$DEST" || exit 1

cat <<EOF

Download finished: $DEST

Next steps
  1. Serve it:            ./tools/serve_local.sh --model-path $DEST
  2. Point the app at it: export H3_LOCAL_BASE_URL=http://127.0.0.1:30010
                          export H3_LOCAL_BASE_URL_REF=http://127.0.0.1:30011
  3. Restart the app and pick the "Local H3 server" backend.

Note on Turbo LoRA
  The community repo advertises "MiniMaxAI/MiniMax-H3-Turbo-Lora". That
  repository does not exist on Hugging Face (the API answers 401), so there is
  no artefact to download. The app therefore exposes the LoRA only as a label
  for whatever your H3 server loads; it does not fetch or apply one itself.
EOF
