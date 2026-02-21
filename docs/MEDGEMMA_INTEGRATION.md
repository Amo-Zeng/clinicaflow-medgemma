# MedGemma Integration (Practical Path)

This repository is designed to be runnable without GPUs by default.
To connect a real MedGemma deployment, ClinicaFlow supports an **OpenAI-compatible** chat-completions backend.

This works well with common self-hosting stacks (e.g. vLLM’s OpenAI server mode).

## One-click demo (recommended)

If you have a GPU machine with vLLM installed, you can let this repo start the model server and the ClinicaFlow demo API in one command:

```bash
MEDGEMMA_MODEL='<HF_ID_OR_LOCAL_PATH>' bash scripts/demo_one_click.sh
```

This will:

- start `vllm.entrypoints.openai.api_server` on `http://127.0.0.1:8001` (customize with `MEDGEMMA_HOST` / `MEDGEMMA_PORT`),
- export the required `CLINICAFLOW_REASONING_*` env vars,
- run `clinicaflow doctor`,
- start the ClinicaFlow demo server on `http://127.0.0.1:8000`.

If you are running an already-hosted endpoint, set `CLINICAFLOW_REASONING_BACKEND=openai_compatible` and related env vars directly; the script will not override them.

## 1) Start a local model server (example: vLLM)

This is a reference setup. Adjust for your hardware and model choice.

```bash
# Example only (not executed by this repo):
python -m vllm.entrypoints.openai.api_server \
  --model <PATH_OR_HF_ID_OF_MEDGEMMA> \
  --host 127.0.0.1 --port 8001
```

## 2) Point ClinicaFlow at the endpoint

Set environment variables:

```bash
export CLINICAFLOW_REASONING_BACKEND=openai_compatible
export CLINICAFLOW_REASONING_BASE_URL=http://127.0.0.1:8001
export CLINICAFLOW_REASONING_MODEL=<YOUR_MODEL_NAME>
# optional:
export CLINICAFLOW_REASONING_API_KEY=<TOKEN_IF_NEEDED>
export CLINICAFLOW_REASONING_TIMEOUT_S=30
export CLINICAFLOW_REASONING_MAX_RETRIES=1
export CLINICAFLOW_REASONING_RETRY_BACKOFF_S=0.5
export CLINICAFLOW_REASONING_TEMPERATURE=0.2
export CLINICAFLOW_REASONING_MAX_TOKENS=600
# optional (privacy guard; enabled by default):
export CLINICAFLOW_PHI_GUARD=1
# optional: circuit breaker (prevents repeated long timeouts if the endpoint is down)
export CLINICAFLOW_INFERENCE_CIRCUIT_FAILS=2
export CLINICAFLOW_INFERENCE_CIRCUIT_COOLDOWN_S=15
export CLINICAFLOW_INFERENCE_CIRCUIT_WINDOW_S=60
# optional (multimodal): send uploaded `image_data_urls` to a vision-capable endpoint
export CLINICAFLOW_REASONING_SEND_IMAGES=1
export CLINICAFLOW_REASONING_MAX_IMAGES=2
# optional: allow larger payloads if you attach images
export CLINICAFLOW_MAX_REQUEST_BYTES=2097152
```

## Optional: Use MedGemma for communication polish

ClinicaFlow can also reuse the same OpenAI-compatible endpoint to rewrite the deterministic drafts
(clinician handoff + patient return precautions) for clarity and conciseness.

This is intentionally a **rewrite-only** step: it is instructed not to add new clinical facts or diagnoses.

```bash
export CLINICAFLOW_COMMUNICATION_BACKEND=openai_compatible
# optional: point the rewrite step at a different endpoint/model
export CLINICAFLOW_COMMUNICATION_BASE_URL=http://127.0.0.1:8001
export CLINICAFLOW_COMMUNICATION_MODEL=<YOUR_MODEL_NAME>
export CLINICAFLOW_COMMUNICATION_API_KEY=<TOKEN_IF_NEEDED>
```

## Optional: Multimodal images in the Console UI

The demo UI supports image uploads for **synthetic** multimodal cases:

- uploaded images are stored in-memory in your browser session,
- the API payload includes `image_data_urls` (data URLs),
- redacted audit bundles exclude images,
- full audit bundles store images as separate files under `images/` (not inline base64 in `intake.json`).

To actually send images to a vision-capable MedGemma endpoint, set:

```bash
export CLINICAFLOW_REASONING_SEND_IMAGES=1
```

If your payloads become large, increase:

```bash
export CLINICAFLOW_MAX_REQUEST_BYTES=2097152
```

## 3) Run a case

```bash
python -m clinicaflow --input examples/sample_case.json --pretty
```

You should see:

- `trace` includes `multimodal_reasoning` output with `reasoning_backend: "external"` when the call succeeds.
- If the endpoint is unavailable or returns invalid JSON, ClinicaFlow falls back to deterministic reasoning and populates `reasoning_backend_error`.
- The prompt wrapper quotes the intake summary as JSON and instructs the model to ignore embedded instructions (basic prompt-injection hardening).

## Notes on safety

- The **Safety & Escalation Agent** remains deterministic by design.
- You should keep site protocols in the policy pack (`clinicaflow/resources/policy_pack.json`) and replace demo entries with real protocol IDs.
