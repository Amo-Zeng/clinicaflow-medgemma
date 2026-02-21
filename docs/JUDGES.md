# Judge Quickstart (ClinicaFlow Console)

This repo is designed so a judge can evaluate the agentic workflow in **~3 minutes**.

## 1) Run the demo (CPU-only, deterministic)

```bash
bash scripts/demo_one_click.sh
```

Recording-friendly mode (auto-start Director overlay + clears local-only demo data):

```bash
DEMO_RECORD=1 bash scripts/demo_one_click.sh
```

Open the printed UI URL (it may auto-select a free port).

## 2) Follow the built-in runbook

In the UI, start from **Home** (or the welcome modal), then:

- Recommended: click **Director: off** (top-right) to enable the recording overlay (teleprompter + UI highlights).
  - Hotkeys: `N`/`P` next/prev, `D` do-step, `Esc` end.
- Or open the **Demo** tab and click through manually:

1. Ops readiness (`/doctor`, `/metrics`, `/openapi.json`, `/policy_pack`)
2. High-acuity case (critical) + download a **redacted** audit bundle (or **Judge pack.zip**)
3. Neuro red-flag case (urgent)
4. Routine case
5. Benchmarks (synthetic proxy + vignette regression; try `standard` or `mega`)
6. Governance tab (safety gate + trigger coverage + export report)
7. Rules tab (deterministic safety rulebook)
8. Ops tab (live metrics + per-agent latency/errors)
9. Adversarial vignette (abbrev/negation/injection-like strings)
10. Clinician review tooling (export local review JSON/markdown)

## 3) Reproduce writeup numbers (one command)

```bash
bash scripts/reproduce_writeup.sh
```

Outputs are written to `tmp/writeup_assets/` (gitignored).

## 4) Optional: real MedGemma backend

If you have a GPU machine hosting MedGemma via an OpenAI-compatible endpoint (e.g., vLLM server mode):

```bash
REQUIRE_MEDGEMMA=1 MEDGEMMA_MODEL='<HF_ID_OR_LOCAL_PATH>' bash scripts/demo_one_click.sh
```

The top-right backend badge should show `openai_compatible`.

## 5) Optional: multimodal images in the demo UI

- Upload images under **Triage → Patient intake → Upload images**.
- To actually send images to a vision-capable endpoint:
  - set `CLINICAFLOW_REASONING_SEND_IMAGES=1`
  - (optional) increase `CLINICAFLOW_MAX_REQUEST_BYTES` if your payloads are large.

Privacy posture: redacted audit bundles exclude images; full bundles store images under `images/` in the zip.

## 6) Optional: build a submission pack zip (offline-friendly)

```bash
bash scripts/prepare_submission_pack.sh
```

This writes `tmp/submission_pack/clinicaflow_submission_pack_<sha>_<timestamp>.zip` (writeup + tables + docs + cover images),
plus a `submission_manifest.json` with SHA256 hashes for provenance.
