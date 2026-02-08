# MedGemma Integration (Practical Path)

This repository is designed to be runnable without GPUs by default.
To connect a real MedGemma deployment, ClinicaFlow supports an **OpenAI-compatible** chat-completions backend.

This works well with common self-hosting stacks (e.g. vLLM’s OpenAI server mode).

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
```

## 3) Run a case

```bash
python -m clinicaflow --input examples/sample_case.json --pretty
```

You should see:

- `trace` includes `multimodal_reasoning` output with `reasoning_backend: "external"` when the call succeeds.
- If the endpoint is unavailable or returns invalid JSON, ClinicaFlow falls back to deterministic reasoning and populates `reasoning_backend_error`.

## Notes on safety

- The **Safety & Escalation Agent** remains deterministic by design.
- You should keep site protocols in the policy pack (`clinicaflow/resources/policy_pack.json`) and replace demo entries with real protocol IDs.

