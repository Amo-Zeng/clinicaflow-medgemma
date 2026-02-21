#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

OUT_DIR="${OUT_DIR:-$ROOT_DIR/tmp/submission_pack}"
WRITEUP_ASSETS_DIR="$OUT_DIR/writeup_assets"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"

# Default to deterministic generation for reproducibility. Set
# SUBMISSION_USE_EXTERNAL=1 if you explicitly want to use your configured
# OpenAI-compatible endpoints while generating assets.
if [[ "${SUBMISSION_USE_EXTERNAL:-0}" != "1" ]]; then
  export CLINICAFLOW_REASONING_BACKEND="deterministic"
  export CLINICAFLOW_COMMUNICATION_BACKEND="deterministic"
fi

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

echo "[pack] Building submission pack at: $OUT_DIR"
echo ""

echo "[pack] Reproducing writeup assets..."
OUT_DIR="$WRITEUP_ASSETS_DIR" bash scripts/reproduce_writeup.sh >/dev/null
echo "[pack] Writeup assets: $WRITEUP_ASSETS_DIR"
echo ""

ensure_venv() {
  if [[ ! -d "$VENV_DIR" ]]; then
    echo "[pack] Creating venv at: $VENV_DIR"
    python3 -m venv "$VENV_DIR"
  fi
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  python -m pip install -q -U pip
  python -m pip install -q -e .
}

echo "[pack] Generating clinician review packet (synthetic; no PHI)..."
ensure_venv >/dev/null
clinicaflow benchmark review_packet --set standard --limit 30 --include-gold --out "$OUT_DIR/clinician_review_packet_standard.md" >/dev/null

if [[ -f "reviews/clinician_reviews.json" ]]; then
  echo "[pack] Including clinician review notes..."
  cp -f "reviews/clinician_reviews.json" "$OUT_DIR/clinician_reviews.json"
  clinicaflow benchmark review_summary --in "reviews/clinician_reviews.json" --out "$OUT_DIR/clinician_review_summary.md" --max-quotes 3 >/dev/null || true
else
  echo "[pack] No clinician review JSON found at reviews/clinician_reviews.json (skipping)."
fi

echo "[pack] Copying key docs..."
cp -f champion_writeup_medgemma.md "$OUT_DIR/champion_writeup_medgemma.md"
cp -f README.md "$OUT_DIR/README.md"
cp -f docs/JUDGES.md "$OUT_DIR/JUDGES.md"
cp -f docs/VIDEO_SCRIPT.md "$OUT_DIR/VIDEO_SCRIPT.md"
cp -f docs/SAFETY.md "$OUT_DIR/SAFETY.md"
cp -f docs/MEDGEMMA_INTEGRATION.md "$OUT_DIR/MEDGEMMA_INTEGRATION.md"
cp -f docs/VIGNETTE_REGRESSION.md "$OUT_DIR/VIGNETTE_REGRESSION.md"
cp -f docs/CLINICIAN_REVIEW_TEMPLATE.md "$OUT_DIR/CLINICIAN_REVIEW_TEMPLATE.md"

if [[ -f "cover_560x280.png" ]]; then cp -f cover_560x280.png "$OUT_DIR/cover_560x280.png"; fi
if [[ -f "cover_560x280.jpg" ]]; then cp -f cover_560x280.jpg "$OUT_DIR/cover_560x280.jpg"; fi

echo "[pack] Capturing repo snapshot..."
sha="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
stamp="$(date -u +%Y%m%dT%H%M%SZ 2>/dev/null || echo unknown)"
git archive --format=zip --output "$OUT_DIR/clinicaflow-medgemma_${sha}.zip" HEAD 2>/dev/null || true

echo "[pack] Writing manifest..."
python - "$OUT_DIR" "$sha" "$stamp" <<'PY'
import hashlib
import json
import os
import sys
from pathlib import Path

out_dir = Path(sys.argv[1])
sha = sys.argv[2]
stamp = sys.argv[3]

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

file_hashes = {}
for path in sorted(out_dir.rglob("*")):
    if not path.is_file():
        continue
    rel = path.relative_to(out_dir).as_posix()
    if rel.endswith(".zip") and rel.startswith("clinicaflow_submission_pack_"):
        continue
    data = path.read_bytes()
    file_hashes[rel] = sha256_bytes(data)

manifest = {
    "generated_at_utc": stamp,
    "git_sha_short": sha,
    "deterministic_generation": os.environ.get("SUBMISSION_USE_EXTERNAL", "0") != "1",
    "files_sha256": file_hashes,
    "notes": [
        "Synthetic-only artifacts (no PHI).",
        "Update the demo video link placeholder before final submission.",
        "For the best demo experience: run scripts/demo_one_click.sh and enable Director mode in the UI.",
    ],
}

(out_dir / "submission_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
PY

echo "[pack] Creating zip..."
zip_name="clinicaflow_submission_pack_${sha}_${stamp}.zip"
python - "$OUT_DIR" "$zip_name" <<'PY'
import sys
import zipfile
from pathlib import Path

out_dir = Path(sys.argv[1])
zip_name = sys.argv[2]
zip_path = out_dir / zip_name

with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    for path in sorted(out_dir.rglob("*")):
        if not path.is_file():
            continue
        if path == zip_path:
            continue
        rel = path.relative_to(out_dir).as_posix()
        zf.write(path, rel)
print(str(zip_path))
PY

echo ""
echo "[pack] Done."
echo "       Folder: $OUT_DIR"
echo "       Zip:    $OUT_DIR/$zip_name"
echo ""
echo "       Next:"
echo "         - Record your 3-minute demo (UI top-right → Director mode)."
echo "         - Replace the placeholder video link in README/writeup before submitting."
