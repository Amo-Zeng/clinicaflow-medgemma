#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
OUT_DIR="${OUT_DIR:-$ROOT_DIR/tmp/writeup_assets}"

ensure_venv() {
  if [[ ! -d "$VENV_DIR" ]]; then
    echo "[writeup] Creating venv at: $VENV_DIR"
    python3 -m venv "$VENV_DIR"
  fi
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  python -m pip install -q -U pip
  python -m pip install -q -e .
}

ensure_venv

mkdir -p "$OUT_DIR"

echo "[writeup] Writing assets to: $OUT_DIR"
echo ""

echo "[writeup] Synthetic proxy benchmark (seed=17, n=220)"
python -m clinicaflow.benchmarks.synthetic --seed 17 --n 220 --print-markdown | tee "$OUT_DIR/synthetic_proxy.md"
echo ""

echo "[writeup] Vignette regression (standard)"
python -m clinicaflow.benchmarks.vignettes --set standard --print-markdown | tee "$OUT_DIR/vignettes_standard.md"
echo ""

echo "[writeup] Vignette regression (extended)"
python -m clinicaflow.benchmarks.vignettes --set extended --print-markdown | tee "$OUT_DIR/vignettes_extended.md"
echo ""

echo "[writeup] Vignette stress test (adversarial)"
python -m clinicaflow.benchmarks.vignettes --set adversarial --print-markdown | tee "$OUT_DIR/vignettes_adversarial.md"
echo ""

echo "[writeup] Vignettes combined (all)"
python -m clinicaflow.benchmarks.vignettes --set all --print-markdown | tee "$OUT_DIR/vignettes_all.md"
echo ""

echo "[writeup] Vignettes combined (mega)"
python -m clinicaflow.benchmarks.vignettes --set mega --print-markdown | tee "$OUT_DIR/vignettes_mega.md"
echo ""

echo "[writeup] Diagnostics snapshot (no secrets)"
clinicaflow doctor | tee "$OUT_DIR/doctor.json" >/dev/null

REVIEWS_PATH="${CLINICIAN_REVIEWS_PATH:-}"
if [[ -z "${REVIEWS_PATH}" ]]; then
  for p in "clinician_reviews.json" "reviews/clinician_reviews.json" "tmp/clinician_reviews.json"; do
    if [[ -f "$p" ]]; then
      REVIEWS_PATH="$p"
      break
    fi
  done
fi

if [[ -n "${REVIEWS_PATH:-}" && -f "${REVIEWS_PATH}" ]]; then
  echo ""
  echo "[writeup] Clinician review summary (${REVIEWS_PATH})"
  clinicaflow benchmark review_summary --in "${REVIEWS_PATH}" --print-markdown | tee "$OUT_DIR/clinician_review_summary.md"
fi

echo ""
echo "[writeup] Done."
echo "         - Markdown tables: $OUT_DIR/*.md"
echo "         - Diagnostics:     $OUT_DIR/doctor.json"
