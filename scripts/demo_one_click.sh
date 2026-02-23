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

USE_FREE_MEDGEMMA="${USE_FREE_MEDGEMMA:-0}"
USE_HF_ROUTER_MEDGEMMA="${USE_HF_ROUTER_MEDGEMMA:-0}"
HF_ROUTER_BASE_URL="${HF_ROUTER_BASE_URL:-https://router.huggingface.co/hf-inference}"
HF_ROUTER_MODEL="${HF_ROUTER_MODEL:-google/medgemma-4b-it}"
HF_ROUTER_TOKEN="${HF_ROUTER_TOKEN:-}"
FREE_MEDGEMMA_SPACE_URL="${FREE_MEDGEMMA_SPACE_URL:-https://senthil3226w-medgemma-4b-it.hf.space}"
FREE_MEDGEMMA_SPACE_URLS="${FREE_MEDGEMMA_SPACE_URLS:-https://senthil3226w-medgemma-4b-it.hf.space,https://majweldon-medgemma-4b-it.hf.space,https://echo3700-google-medgemma-4b-it.hf.space,https://noumanjavaid-google-medgemma-4b-it.hf.space,https://shiveshk1-google-medgemma-4b-it.hf.space,https://myopicoracle-google-medgemma-4b-it-chatbot.hf.space,https://qazi-musa-med-gemma-3.hf.space,https://warshanks-medgemma-4b-it.hf.space,https://warshanks-medgemma-1-5-4b-it.hf.space,https://warshanks-medgemma-27b-it.hf.space,https://eminkarka1-cortix-medgemma.hf.space|predict}"
FREE_MEDGEMMA_API_NAME="${FREE_MEDGEMMA_API_NAME:-chat}"

RUN_BENCHMARKS="${RUN_BENCHMARKS:-0}"
OPEN_BROWSER="${OPEN_BROWSER:-0}"
DEMO_RECORD="${DEMO_RECORD:-0}"
DEMO_RESET="${DEMO_RESET:-0}"
DEMO_AUTORUN="${DEMO_AUTORUN:-}"
DEMO_AUTORUN_SET="${DEMO_AUTORUN_SET:-}"
ALLOW_LEGACY_UI="${ALLOW_LEGACY_UI:-0}"
PING_INFERENCE="${PING_INFERENCE:-0}"

VLLM_PID=""
SERVER_PID=""
DOCTOR_JSON=""

cleanup() {
  if [[ -n "${VLLM_PID:-}" ]]; then
    kill "${VLLM_PID}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${SERVER_PID:-}" ]]; then
    kill "${SERVER_PID}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

cf() {
  python -m clinicaflow.cli "$@"
}

ensure_venv() {
  if [[ ! -d "$VENV_DIR" ]]; then
    echo "[demo] Creating venv at: $VENV_DIR"
    python3 -m venv "$VENV_DIR"
  fi
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  # No third-party deps required for the CPU-only demo. We run the CLI via
  # `python -m clinicaflow.cli` so an editable install is optional.
  #
  # Best-effort: if setuptools is available, install editable so users can
  # also invoke the `clinicaflow` entrypoint.
  if python -c 'import setuptools' >/dev/null 2>&1; then
    python -m pip install -q -e . >/dev/null 2>&1 || true
  fi
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

select_free_medgemma_space() {
  local urls_csv="${FREE_MEDGEMMA_SPACE_URLS:-${FREE_MEDGEMMA_SPACE_URL}}"
  local entries=()
  IFS=',' read -ra entries <<< "$urls_csv"

  for entry in "${entries[@]}"; do
    entry="$(echo "$entry" | xargs)"
    [[ -z "$entry" ]] && continue

    local url="$entry"
    local api_name="${FREE_MEDGEMMA_API_NAME}"
    if [[ "$entry" == *"|"* ]]; then
      url="$(echo "${entry%%|*}" | xargs)"
      api_name="$(echo "${entry##*|}" | xargs)"
    fi

    [[ -z "$url" ]] && continue
    api_name="${api_name:-chat}"

    echo "[demo] Probing free Space: ${url} (api_name=${api_name})"
    export CLINICAFLOW_REASONING_BACKEND="gradio_space"
    export CLINICAFLOW_REASONING_BASE_URL="$url"
    export CLINICAFLOW_REASONING_BASE_URLS=""
    export CLINICAFLOW_REASONING_GRADIO_API_NAME="$api_name"

    local dj=""
    if ! dj="$(cf doctor 2>/dev/null)"; then
      echo "[demo]   -> doctor failed"
      continue
    fi

    local ready=""
    ready="$(python - <<'PY' <<<"$dj"
import json
import sys

payload = json.loads(sys.stdin.read())
rb = payload.get("reasoning_backend") or {}
ok = rb.get("connectivity_ok") is True
gr = rb.get("gradio") or {}
api_ok = gr.get("api_name_found")
ready = ok and (api_ok is not False)
sys.stdout.write("1" if ready else "0")
PY
)"
    if [[ "${ready}" == "1" ]]; then
      DOCTOR_JSON="$dj"
      export CLINICAFLOW_REASONING_BASE_URLS="${entry},${urls_csv}"
      echo "[demo] Selected free Space: ${url} (api_name=${api_name})"
      return 0
    fi

    echo "[demo]   -> not ready"
  done

  echo "[demo] WARNING: No free Spaces were ready; falling back to: ${FREE_MEDGEMMA_SPACE_URL}"
  export CLINICAFLOW_REASONING_BACKEND="gradio_space"
  export CLINICAFLOW_REASONING_BASE_URL="${FREE_MEDGEMMA_SPACE_URL}"
  export CLINICAFLOW_REASONING_BASE_URLS="${urls_csv}"
  export CLINICAFLOW_REASONING_GRADIO_API_NAME="${FREE_MEDGEMMA_API_NAME}"
  return 1
}

maybe_start_medgemma_vllm() {
  if [[ -n "${CLINICAFLOW_REASONING_BACKEND:-}" && "${CLINICAFLOW_REASONING_BACKEND}" != "deterministic" ]]; then
    echo "[demo] Using existing CLINICAFLOW_REASONING_BACKEND=${CLINICAFLOW_REASONING_BACKEND}"
    return 0
  fi

  if [[ "${USE_HF_ROUTER_MEDGEMMA}" == "1" ]]; then
    echo "[demo] Using Hugging Face router inference (token required; demo-only)."
    export CLINICAFLOW_REASONING_BACKEND="hf_inference"
    export CLINICAFLOW_REASONING_BASE_URL="${HF_ROUTER_BASE_URL}"
    export CLINICAFLOW_REASONING_MODEL="${HF_ROUTER_MODEL}"
    if [[ -n "${HF_ROUTER_TOKEN:-}" ]]; then
      export CLINICAFLOW_REASONING_API_KEY="${HF_ROUTER_TOKEN}"
    fi
    return 0
  fi

  if [[ "${USE_FREE_MEDGEMMA}" == "1" ]]; then
    echo "[demo] Using free hosted MedGemma Space (best-effort; demo-only)."
    export CLINICAFLOW_REASONING_BACKEND="gradio_space"
    export CLINICAFLOW_REASONING_BASE_URL=""
    export CLINICAFLOW_REASONING_BASE_URLS="${FREE_MEDGEMMA_SPACE_URLS:-${FREE_MEDGEMMA_SPACE_URL}}"
    export CLINICAFLOW_REASONING_GRADIO_API_NAME="${FREE_MEDGEMMA_API_NAME}"
    select_free_medgemma_space || true
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

  vllm_extra_args=()
  if [[ -n "${MEDGEMMA_SERVED_MODEL_NAME:-}" ]]; then
    if python -m vllm.entrypoints.openai.api_server --help 2>&1 | grep -q -- "--served-model-name"; then
      vllm_extra_args+=(--served-model-name "$MEDGEMMA_SERVED_MODEL_NAME")
    else
      echo "[demo] WARNING: MEDGEMMA_SERVED_MODEL_NAME is set but this vLLM build has no --served-model-name flag."
      echo "       Ignoring MEDGEMMA_SERVED_MODEL_NAME; model will be served as: ${MEDGEMMA_MODEL}"
    fi
  fi

  echo "[demo] Starting MedGemma vLLM OpenAI-compatible server..."
  set -x
  # shellcheck disable=SC2086
  python -m vllm.entrypoints.openai.api_server \
    --model "$MEDGEMMA_MODEL" \
    --host "$MEDGEMMA_HOST" \
    --port "$MEDGEMMA_PORT" \
    "${vllm_extra_args[@]}" \
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
doctor_json="${DOCTOR_JSON:-}"
if [[ -z "${doctor_json:-}" ]]; then
  doctor_json="$(cf doctor)"
fi
echo "$doctor_json" | python -m json.tool

if [[ "${PING_INFERENCE}" == "1" ]]; then
  echo ""
  echo "[demo] Deep ping (no PHI):"
  if ! cf ping --which all --pretty; then
    echo ""
    echo "[demo] WARNING: Inference ping failed."
    if [[ "${REQUIRE_MEDGEMMA:-0}" == "1" ]]; then
      echo "       REQUIRE_MEDGEMMA=1 is set; refusing to continue."
      exit 2
    fi
  fi
fi

echo ""
echo "[demo] Resource validation (policy pack + vignettes):"
cf validate --pretty | python -m json.tool >/dev/null
echo "[demo] Resource validation: OK"

if [[ "${REQUIRE_MEDGEMMA:-0}" == "1" ]]; then
  python - "$doctor_json" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
rb = payload.get("reasoning_backend") or {}
backend = str(rb.get("backend") or "").strip().lower()
ok = rb.get("connectivity_ok")
model = str(rb.get("model") or "").strip()
base_url = str(rb.get("base_url") or "").strip()

ready = False
if backend in {"openai", "openai_compatible"}:
    ready = ok is True and bool(model)
elif backend == "gradio_space":
    ready = ok is True and bool(base_url)
elif backend == "hf_inference":
    ready = ok is True and bool(model) and bool(base_url)

if not ready:
    print("")
    print("[demo] ERROR: REQUIRE_MEDGEMMA=1 but the reasoning backend is not ready.")
    print(f"       backend={backend!r} connectivity_ok={ok!r} model={model!r} base_url={base_url!r}")
    print("       Fix by setting a real MedGemma endpoint, e.g.:")
    print("         MEDGEMMA_MODEL='<HF_ID_OR_LOCAL_PATH>' bash scripts/demo_one_click.sh")
    print("       Or use a free hosted Hugging Face Space (best-effort), e.g.:")
    print("         CLINICAFLOW_REASONING_BACKEND=gradio_space \\")
    print("         CLINICAFLOW_REASONING_BASE_URL='https://senthil3226w-medgemma-4b-it.hf.space' \\")
    print("         bash scripts/demo_one_click.sh")
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
cf serve --host "$CLINICAFLOW_HOST" --port "$CLINICAFLOW_PORT" &
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

headers="$(
  curl -fsSI "http://127.0.0.1:${CLINICAFLOW_PORT}/" 2>/dev/null || true
)"
if [[ -z "${headers:-}" ]]; then
  # Some older server builds may not implement HEAD; fall back to GET header dump.
  headers="$(
    curl -fsS -D - -o /dev/null "http://127.0.0.1:${CLINICAFLOW_PORT}/" 2>/dev/null || true
  )"
fi

ui_header="$(
  echo "${headers:-}" \
    | tr -d '\r' \
    | awk -F': ' 'tolower($1)=="x-clinicaflow-ui"{print $2}' \
    | tail -n 1
)"
if [[ "${ui_header:-}" == "legacy" ]]; then
  echo "[demo] ERROR: Legacy 2-box fallback UI detected."
  echo "       This repo ships a richer Console UI; legacy mode usually means:"
  echo "         - you opened the wrong port, OR"
  echo "         - a stale service-worker cache, OR"
  echo "         - a stale venv/install."
  echo ""
  echo "       Fix:"
  echo "         1) Open: http://127.0.0.1:${CLINICAFLOW_PORT}/?reset=1"
  echo "         2) If it persists: rm -rf .venv && bash scripts/demo_one_click.sh"
  echo ""
  echo "       Override (not recommended): ALLOW_LEGACY_UI=1 bash scripts/demo_one_click.sh"
  if [[ "${ALLOW_LEGACY_UI}" != "1" ]]; then
    exit 3
  fi
fi

UI_URL="http://127.0.0.1:${CLINICAFLOW_PORT}/"
if [[ "${DEMO_RECORD}" == "1" ]]; then
  UI_URL="http://127.0.0.1:${CLINICAFLOW_PORT}/?director=1&reset=1"
  OPEN_BROWSER="1"
  echo ""
  echo "[demo] Recording mode enabled (DEMO_RECORD=1)."
  echo "       - Auto-starts Director mode in the browser"
  echo "       - Resets local-only demo storage for a clean recording"
else
  qs=""
  if [[ "${DEMO_RESET}" == "1" ]]; then
    qs="reset=1"
  fi
  if [[ -n "${DEMO_AUTORUN:-}" ]]; then
    qs="${qs:+${qs}&}autorun=${DEMO_AUTORUN}"
  fi
  if [[ -n "${DEMO_AUTORUN_SET:-}" ]]; then
    qs="${qs:+${qs}&}set=${DEMO_AUTORUN_SET}"
  fi
  if [[ -n "${qs:-}" ]]; then
    UI_URL="http://127.0.0.1:${CLINICAFLOW_PORT}/?${qs}"
  fi
fi

echo ""
echo "[demo] Ready:"
echo "       UI:      ${UI_URL}"
echo "       OpenAPI: http://127.0.0.1:${CLINICAFLOW_PORT}/openapi.json"
echo "       Metrics: http://127.0.0.1:${CLINICAFLOW_PORT}/metrics"
echo ""
echo "       Tip: Start from the Home tab (or welcome modal) → Start 3-minute demo."
echo "       Tip: After a triage run, click 'Judge pack.zip' to download all artifacts."
echo ""

if [[ "${OPEN_BROWSER}" == "1" ]]; then
  python - <<PY
import webbrowser
webbrowser.open("${UI_URL}")
PY
fi

wait "$SERVER_PID"
