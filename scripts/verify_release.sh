#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[verify] Running unit tests..."
python -m unittest discover -s tests -q
echo ""

echo "[verify] Checking for placeholder links..."
PLACEHOLDER_VIDEO_ID="${PLACEHOLDER_VIDEO_ID:-vZgvNssSSGk}"
if command -v rg >/dev/null 2>&1; then
  if rg -n "${PLACEHOLDER_VIDEO_ID}" \
    README.md KAGGLE_WRITEUP.md champion_writeup_medgemma.md \
    clinicaflow/resources/web/index.html public_demo/index.html streamlit_app.py >/dev/null 2>&1; then
    echo "[verify] ERROR: Placeholder demo video ID detected (${PLACEHOLDER_VIDEO_ID})."
    rg -n "${PLACEHOLDER_VIDEO_ID}" \
      README.md KAGGLE_WRITEUP.md champion_writeup_medgemma.md \
      clinicaflow/resources/web/index.html public_demo/index.html streamlit_app.py || true
    exit 2
  fi
fi
echo "[verify] Placeholder links: OK"
echo ""

echo "[verify] Validating vignette resources..."
python - <<'PY'
import json
import re
from pathlib import Path

from clinicaflow.benchmarks.vignettes import load_default_vignette_paths, load_vignettes

expected_min = {
    "standard": 30,
    "adversarial": 20,
    "realworld": 20,
    "case_reports": 20,
}

counts = {}
for set_name in ["standard", "adversarial", "realworld", "case_reports"]:
    rows = []
    for p in load_default_vignette_paths(set_name):
        rows.extend(load_vignettes(p))
    counts[set_name] = len(rows)
    if len(rows) < expected_min[set_name]:
        raise SystemExit(f"vignette set {set_name!r} too small: {len(rows)} < {expected_min[set_name]}")

print(json.dumps({"vignette_counts": counts}, indent=2))

# Stricter checks for case reports: provenance required + basic PHI regex.
case_path = Path("clinicaflow/resources/vignettes_case_reports.jsonl")
rows = [json.loads(line) for line in case_path.read_text(encoding="utf-8").splitlines() if line.strip()]
if len(rows) < 45:
    raise SystemExit(f"case_reports expected ~50, got {len(rows)}")

missing = [r.get("id") for r in rows if not (r.get("source") or {}).get("url") or not (r.get("source") or {}).get("title")]
if missing:
    raise SystemExit(f"case_reports missing source fields for: {missing[:5]}")

phi_re = re.compile(r"\b(\d{3}-\d{2}-\d{4}|\(\d{3}\)\s*\d{3}-\d{4}|\d{3}[- ]\d{3}[- ]\d{4})\b")
phi_hits = []
for r in rows:
    blob = json.dumps(r.get("input") or {}, ensure_ascii=False)
    if phi_re.search(blob):
        phi_hits.append(r.get("id"))
if phi_hits:
    raise SystemExit(f"PHI-like phone/SSN patterns found in: {phi_hits[:5]}")

print(json.dumps({"case_reports": {"rows": len(rows), "missing_source_fields": len(missing), "phi_hits": len(phi_hits)}}, indent=2))
PY
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
if compgen -G "tmp/submission_pack/clinicaflow_submission_pack_*.zip" >/dev/null; then
  echo "[verify] Latest submission pack zip:"
  ls -1t tmp/submission_pack/clinicaflow_submission_pack_*.zip | head -n 1
  echo ""
fi

echo "[verify] Done."
echo ""
echo "[verify] Next:"
echo "         - Record: DEMO_RECORD=1 bash scripts/demo_one_click.sh"
echo "         - If buttons don't respond, open /?reset=1 (or Clear demo data)."
