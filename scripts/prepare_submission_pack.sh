#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

OUT_DIR="${OUT_DIR:-$ROOT_DIR/tmp/submission_pack}"
WRITEUP_ASSETS_DIR="$OUT_DIR/writeup_assets"

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

echo "[pack] Building submission pack at: $OUT_DIR"
echo ""

echo "[pack] Reproducing writeup assets..."
OUT_DIR="$WRITEUP_ASSETS_DIR" bash scripts/reproduce_writeup.sh >/dev/null
echo "[pack] Writeup assets: $WRITEUP_ASSETS_DIR"
echo ""

echo "[pack] Copying key docs..."
cp -f champion_writeup_medgemma.md "$OUT_DIR/champion_writeup_medgemma.md"
cp -f README.md "$OUT_DIR/README.md"
cp -f docs/JUDGES.md "$OUT_DIR/JUDGES.md"
cp -f docs/VIDEO_SCRIPT.md "$OUT_DIR/VIDEO_SCRIPT.md"
cp -f docs/VIGNETTE_REGRESSION.md "$OUT_DIR/VIGNETTE_REGRESSION.md"
cp -f docs/CLINICIAN_REVIEW_TEMPLATE.md "$OUT_DIR/CLINICIAN_REVIEW_TEMPLATE.md"

if [[ -f "cover_560x280.png" ]]; then cp -f cover_560x280.png "$OUT_DIR/cover_560x280.png"; fi
if [[ -f "cover_560x280.jpg" ]]; then cp -f cover_560x280.jpg "$OUT_DIR/cover_560x280.jpg"; fi
if [[ -f "clinicaflow-medgemma.zip" ]]; then cp -f clinicaflow-medgemma.zip "$OUT_DIR/clinicaflow-medgemma.zip"; fi

echo "[pack] Creating zip..."
(
  cd "$OUT_DIR"
  zip -qr clinicaflow_submission_pack.zip . -x "clinicaflow_submission_pack.zip"
)

echo ""
echo "[pack] Done."
echo "       Folder: $OUT_DIR"
echo "       Zip:    $OUT_DIR/clinicaflow_submission_pack.zip"

