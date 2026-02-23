# Judge Quickstart (ClinicaFlow Console)

This repo is designed so a judge can evaluate the agentic workflow in **~3 minutes**.

Public interactive live demo (static; no server): https://2agi.me/clinicaflow-medgemma/

## 1) Run the demo (CPU-only, deterministic)

```bash
bash scripts/demo_one_click.sh
```

Recording-friendly mode (auto-start Director overlay + clears local-only demo data):

```bash
DEMO_RECORD=1 bash scripts/demo_one_click.sh
```

Open the printed UI URL (it may auto-select a free port).

If the UI looks “too simple” (stale cached assets), click **Clear demo data** (top-right) or open `/?reset=1`.

## 2) Follow the built-in runbook

In the UI, start from **Home** (or the welcome modal), then:

- Recommended: click **Start 3-minute demo** (Home) to launch the Director overlay (teleprompter + UI highlights).
  - You can also toggle it via **Director: off** (top-right).
  - Hotkeys: `N`/`P` next/prev, `D` do-step, `Esc` end.
- Or open the **Demo** tab and click through manually:

1. Ops readiness (`/doctor`, `/metrics`, `/openapi.json`, `/policy_pack`)
   - Optional: deep inference ping (`/ping`) to prove the configured backend actually responds (no PHI).
2. High-acuity case (critical) + download a **redacted** audit bundle (or **Judge pack.zip**)
   - In redacted exports, open `manifest.json` to see SHA256 hashes and `phi_scrubbed_patterns` (category labels only).
3. Neuro red-flag case (urgent)
4. Routine case
5. Benchmarks (synthetic proxy + vignette regression; try `standard` or `mega`)
6. Governance tab (safety gate + trigger coverage + **Ops SLO** + export report)
7. Rules tab (deterministic safety rulebook)
8. Ops tab (live metrics + rolling p50/p95 + per-agent latency/errors)
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

If you **don’t** have a GPU machine, you can try a **public Hugging Face Space** (Gradio) as a demo-only backend:

```bash
USE_FREE_MEDGEMMA=1 REQUIRE_MEDGEMMA=1 bash scripts/demo_one_click.sh
```

This is best-effort (Spaces can be rate-limited/sleep/change).

If you have a Hugging Face token, you can also use the **Hugging Face router inference API** (demo-only):

```bash
USE_HF_ROUTER_MEDGEMMA=1 HF_ROUTER_TOKEN='<HF_TOKEN>' REQUIRE_MEDGEMMA=1 bash scripts/demo_one_click.sh
```

## Optional: free evidence links (PubMed / MedlinePlus / Crossref / OpenAlex / ClinicalTrials.gov)

Attach best-effort external citations (no API keys; demo-only):

```bash
CLINICAFLOW_EVIDENCE_BACKEND=auto bash scripts/demo_one_click.sh
```

See `docs/EVIDENCE_APIS.md` for backend options and tuning.

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
