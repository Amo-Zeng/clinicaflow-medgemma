#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
CLINICAFLOW_HOST="${CLINICAFLOW_HOST:-0.0.0.0}"
CLINICAFLOW_PORT="${CLINICAFLOW_PORT:-8000}"

MEDGEMMA_HOST="${MEDGEMMA_HOST:-127.0.0.1}"
MEDGEMMA_PORT="${MEDGEMMA_PORT:-8001}"
MEDGEMMA_MODEL="${MEDGEMMA_MODEL:-}"
MEDGEMMA_VLLM_ARGS="${MEDGEMMA_VLLM_ARGS:-}"
MEDGEMMA_SERVED_MODEL_NAME="${MEDGEMMA_SERVED_MODEL_NAME:-}"

RUN_BENCHMARKS="${RUN_BENCHMARKS:-0}"

VLLM_PID=""

cleanup() {
  if [[ -n "${VLLM_PID:-}" ]]; then
    kill "${VLLM_PID}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

ensure_venv() {
  if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
  fi
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  python -m pip install -q -U pip
  python -m pip install -q -e .
}

wait_for_http_200() {
  local url="$1"
  local timeout_s="${2:-90}"
  python - "$url" "$timeout_s" <<'PY'
import sys
import time
import urllib.request

url = sys.argv[1]
timeout_s = float(sys.argv[2])
deadline = time.time() + timeout_s

while time.time() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310
            if 200 <= resp.status < 300:
                sys.exit(0)
    except Exception:
        time.sleep(1)

sys.exit(1)
PY
}

maybe_start_medgemma_vllm() {
  if [[ -n "${CLINICAFLOW_REASONING_BACKEND:-}" && "${CLINICAFLOW_REASONING_BACKEND}" != "deterministic" ]]; then
    echo "[demo] Using existing CLINICAFLOW_REASONING_BACKEND=${CLINICAFLOW_REASONING_BACKEND}"
    return 0
  fi

  if [[ -z "$MEDGEMMA_MODEL" ]]; then
    echo "[demo] MEDGEMMA_MODEL not set; using deterministic reasoning."
    return 0
  fi

  if ! python -c 'import vllm' >/dev/null 2>&1; then
    echo "[demo] vLLM not installed; using deterministic reasoning."
    echo "       Install vLLM on your GPU machine, then re-run with:"
    echo "         MEDGEMMA_MODEL='<HF_ID_OR_LOCAL_PATH>' pip install vllm"
    return 0
  fi

  echo "[demo] Starting MedGemma vLLM OpenAI-compatible server..."
  set -x
  python -m vllm.entrypoints.openai.api_server \
    --model "$MEDGEMMA_MODEL" \
    --host "$MEDGEMMA_HOST" \
    --port "$MEDGEMMA_PORT" \
    $MEDGEMMA_VLLM_ARGS &
  set +x
  VLLM_PID="$!"

  echo "[demo] Waiting for model server..."
  wait_for_http_200 "http://${MEDGEMMA_HOST}:${MEDGEMMA_PORT}/v1/models" 180

  export CLINICAFLOW_REASONING_BACKEND="openai_compatible"
  export CLINICAFLOW_REASONING_BASE_URL="http://${MEDGEMMA_HOST}:${MEDGEMMA_PORT}"
  export CLINICAFLOW_REASONING_MODEL="${MEDGEMMA_SERVED_MODEL_NAME:-$MEDGEMMA_MODEL}"
  echo "[demo] MedGemma reasoning enabled: ${CLINICAFLOW_REASONING_MODEL}"
}

ensure_venv
maybe_start_medgemma_vllm

echo ""
echo "[demo] Sanity check:"
clinicaflow doctor | python -m json.tool

if [[ "$RUN_BENCHMARKS" == "1" ]]; then
  echo ""
  echo "[demo] Vignette regression benchmark:"
  python -m clinicaflow.benchmarks.vignettes --print-markdown
fi

echo ""
echo "[demo] Starting ClinicaFlow demo server..."
echo "       UI: http://127.0.0.1:${CLINICAFLOW_PORT}/"
echo "       OpenAPI: http://127.0.0.1:${CLINICAFLOW_PORT}/openapi.json"
echo "       Metrics: http://127.0.0.1:${CLINICAFLOW_PORT}/metrics"
echo ""
clinicaflow serve --host "$CLINICAFLOW_HOST" --port "$CLINICAFLOW_PORT"

