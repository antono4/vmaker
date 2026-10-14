#!/usr/bin/env bash
# Re-fetch the upstream reference material kept in ./upstream.
#
# The MiniMax-H3 model card, its prompt-writing guides and its request scripts
# are the source of truth for the API shapes this app speaks. Vendoring them
# keeps the app self-describing and lets you diff against upstream later.
#
# Usage:  ./tools/fetch_upstream.sh
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HF="https://huggingface.co/MiniMaxAI/MiniMax-H3/raw/main"
GH="https://raw.githubusercontent.com/minimaxh3turbo/MiniMax-H3-Turbo-LoRA-ComfyUI/main"

fetch() {  # fetch <url> <destination>
  local url="$1" dest="$2"
  mkdir -p "$(dirname "$dest")"
  if curl -fsSL "$url" -o "$dest"; then
    printf '  ok   %s\n' "${dest#"$ROOT"/}"
  else
    printf '  FAIL %s\n' "$url" >&2
    rm -f "$dest"
  fi
}

echo "== MiniMax-H3 model card, guides and request scripts =="
fetch "$HF/README.md" "$ROOT/upstream/model/README.md"
fetch "$HF/model_index.json" "$ROOT/upstream/model/model_index.json"
fetch "$HF/modular_model_index.json" "$ROOT/upstream/model/modular_model_index.json"
fetch "$HF/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md" "$ROOT/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md"
fetch "$HF/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md" "$ROOT/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md"

for name in reproducible-768p-t2va-request reproducible-768p-fl2va-request \
            reproducible-768p-ref2va-request; do
  fetch "$HF/scripts/readme/$name.sh" "$ROOT/upstream/scripts/$name.sh"
done

for name in full-2k-t2va-h3-context-ir full-2k-t2va-h3-base full-2k-t2va-h3-regenerate-2k \
            full-2k-i2va-h3-base full-2k-ref2va-h3-base \
            full-2k-t2va-reference-2k-result-by-directly-calling-open-platform-api; do
  fetch "$HF/scripts/readme/$name.sh" "$ROOT/upstream/scripts/$name.sh"
done

echo
echo "== Community ComfyUI wrapper (the repo this app was requested from) =="
for path in README.md LICENSE i2v/h3_i2v.py i2v/inference_i2v.py t2v/h3_t2v.py \
            t2v/inference_t2v.py t2v/download_model.py r2v/h3_r2v.py r2v/inference_r2v.py \
            lora/h3_loader.py lora/h3_turbo_lora.py lora/sglang_serve.py \
            vae/h3_vae.py vae/h3_context.py; do
  fetch "$GH/$path" "$ROOT/upstream/community-comfyui/$path"
done

echo
echo "Done. Reference material lives in upstream/ and docs/."
