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
SERVER_PID=""

cleanup() {
  if [[ -n "${VLLM_PID:-}" ]]; then
    kill "${VLLM_PID}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${SERVER_PID:-}" ]]; then
    kill "${SERVER_PID}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

ensure_venv() {
  if [[ ! -d "$VENV_DIR" ]]; then
    echo "[demo] Creating venv at: $VENV_DIR"
    python3 -m venv "$VENV_DIR"
  fi
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  echo "[demo] Installing/refreshing dependencies (pip)…"
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

is_port_free() {
  local port="$1"
  python - "$port" <<'PY'
import socket
import sys

port = int(sys.argv[1])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.bind(("127.0.0.1", port))
except OSError:
    sys.exit(1)
finally:
    s.close()
sys.exit(0)
PY
}

find_free_port() {
  local start_port="$1"
  local tries="${2:-20}"
  local port="$start_port"
  local i=0
  while [[ "$i" -lt "$tries" ]]; do
    if is_port_free "$port" >/dev/null 2>&1; then
      echo "$port"
      return 0
    fi
    port=$((port + 1))
    i=$((i + 1))
  done
  return 1
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

REQUESTED_PORT="$CLINICAFLOW_PORT"

if ! is_port_free "$CLINICAFLOW_PORT" >/dev/null 2>&1; then
  echo "[demo] Port ${CLINICAFLOW_PORT} is already in use."
  if free_port="$(find_free_port "$CLINICAFLOW_PORT" 30)"; then
    echo "[demo] Using free port: ${free_port}"
    CLINICAFLOW_PORT="$free_port"
  else
    echo "[demo] Could not find a free port near ${CLINICAFLOW_PORT}."
    echo "       Stop the existing server, or set CLINICAFLOW_PORT=... and re-run."
    exit 1
  fi
fi

if [[ "$CLINICAFLOW_PORT" != "$REQUESTED_PORT" ]]; then
  echo ""
  echo "[demo] IMPORTANT: Requested port ${REQUESTED_PORT} was busy."
  echo "       Open the UI on: http://127.0.0.1:${CLINICAFLOW_PORT}/"
  echo ""
fi

echo ""
echo "[demo] Sanity check:"
doctor_json="$(clinicaflow doctor)"
echo "$doctor_json" | python -m json.tool

if [[ "${REQUIRE_MEDGEMMA:-0}" == "1" ]]; then
  python - "$doctor_json" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
rb = payload.get("reasoning_backend") or {}
backend = str(rb.get("backend") or "").strip().lower()
ok = rb.get("connectivity_ok")
model = str(rb.get("model") or "").strip()

if backend not in {"openai", "openai_compatible"} or ok is not True or not model:
    print("")
    print("[demo] ERROR: REQUIRE_MEDGEMMA=1 but the reasoning backend is not ready.")
    print(f"       backend={backend!r} connectivity_ok={ok!r} model={model!r}")
    print("       Fix by setting a real MedGemma endpoint, e.g.:")
    print("         MEDGEMMA_MODEL='<HF_ID_OR_LOCAL_PATH>' bash scripts/demo_one_click.sh")
    sys.exit(2)
PY
fi

if [[ "$RUN_BENCHMARKS" == "1" ]]; then
  echo ""
  echo "[demo] Vignette regression benchmark:"
  python -m clinicaflow.benchmarks.vignettes --print-markdown
fi

echo ""
echo "[demo] Starting ClinicaFlow demo server..."
set -x
clinicaflow serve --host "$CLINICAFLOW_HOST" --port "$CLINICAFLOW_PORT" &
set +x
SERVER_PID="$!"

echo "[demo] Waiting for server..."
wait_for_http_200 "http://127.0.0.1:${CLINICAFLOW_PORT}/health" 60

if curl -fsS "http://127.0.0.1:${CLINICAFLOW_PORT}/static/app.js" >/dev/null 2>&1; then
  echo "[demo] Console UI assets detected."
else
  echo "[demo] WARNING: Console UI assets not detected."
  echo "       You may be running an older server instance or a stale install."
  echo "       Try stopping existing processes and re-running this script."
fi

ui_header="$(
  curl -fsSI "http://127.0.0.1:${CLINICAFLOW_PORT}/" 2>/dev/null \
    | tr -d '\r' \
    | awk -F': ' 'tolower($1)=="x-clinicaflow-ui"{print $2}' \
    | tail -n 1
)"
if [[ "${ui_header:-}" == "legacy" ]]; then
  echo "[demo] WARNING: Legacy 2-box fallback UI detected."
  echo "       Make sure you opened: http://127.0.0.1:${CLINICAFLOW_PORT}/"
  echo "       If it persists, delete the venv and re-run:"
  echo "         rm -rf .venv && bash scripts/demo_one_click.sh"
fi

echo ""
echo "[demo] Ready:"
echo "       UI:      http://127.0.0.1:${CLINICAFLOW_PORT}/"
echo "       OpenAPI: http://127.0.0.1:${CLINICAFLOW_PORT}/openapi.json"
echo "       Metrics: http://127.0.0.1:${CLINICAFLOW_PORT}/metrics"
echo ""

wait "$SERVER_PID"
