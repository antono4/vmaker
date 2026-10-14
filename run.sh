#!/usr/bin/env bash
# Run the MiniMax H3 Video Maker.
#
#   ./run.sh                 # start on port 12000
#   ./run.sh --port 8080
#   ./run.sh --backend local # preselect the local H3 server backend
#
# Environment variables you may want to set first:
#   MINIMAX_API_KEY      enables the MiniMax Open Platform backend
#   MINIMAX_API_BASE     https://api.minimax.io (global) or https://api.minimaxi.com (CN)
#   H3_LOCAL_BASE_URL    SGLang/vLLM endpoint for fl2va  (default http://127.0.0.1:30010)
#   H3_LOCAL_BASE_URL_REF SGLang/vLLM endpoint for ref2va (default http://127.0.0.1:30011)
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PORT="${H3_PORT:-12000}"
HOST="${H3_HOST:-0.0.0.0}"
BACKEND=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)    PORT="$2"; shift 2 ;;
    --host)    HOST="$2"; shift 2 ;;
    --backend) BACKEND="$2"; shift 2 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ -n "$BACKEND" ]]; then export H3_DEFAULT_BACKEND="$BACKEND"; fi
export H3_PORT="$PORT" H3_HOST="$HOST"

if ! python3 -c "import fastapi, uvicorn, httpx, PIL, numpy, imageio_ffmpeg" 2>/dev/null; then
  echo "Installing dependencies..."
  python3 -m pip install -r requirements.txt || exit 1
fi

ENCODER="$(python3 -c 'import app.media as m; print(m.ffmpeg_path() or "")' 2>/dev/null || true)"
if [[ -z "$ENCODER" ]]; then
  echo "WARNING: no ffmpeg binary found. Video encoding will fail."
  echo "         Install ffmpeg, or: python3 -m pip install imageio-ffmpeg"
  echo
fi

echo "MiniMax H3 Video Maker"
echo "  http://127.0.0.1:$PORT"
echo "  default backend: ${H3_DEFAULT_BACKEND:-demo}"
echo

exec python3 -m uvicorn app.main:app --host "$HOST" --port "$PORT" --log-level info
