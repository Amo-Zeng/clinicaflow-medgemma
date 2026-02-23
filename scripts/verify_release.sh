#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[verify] Running unit tests..."
python -m unittest discover -s tests
echo ""

echo "[verify] Reproducing writeup assets..."
bash scripts/reproduce_writeup.sh
echo ""

echo "[verify] Building submission pack..."
bash scripts/prepare_submission_pack.sh
echo ""

echo "[verify] Smoke triage (deterministic, no external calls)..."
python - <<'PY'
import json

from clinicaflow.demo_server import SAMPLE_INTAKE
from clinicaflow.models import PatientIntake
from clinicaflow.pipeline import ClinicaFlowPipeline

pipeline = ClinicaFlowPipeline()
intake = PatientIntake.from_mapping(SAMPLE_INTAKE)
out = pipeline.run(intake)

payload = out.to_dict()
assert payload.get("risk_tier") in {"routine", "urgent", "critical"}
assert isinstance(payload.get("red_flags"), list)
assert isinstance(payload.get("recommended_next_actions"), list)
print(json.dumps({"risk_tier": payload.get("risk_tier"), "red_flags": payload.get("red_flags")[:3]}, indent=2))
PY

echo ""
echo "[verify] Done."
