# Deployment Notes

This repo ships with a lightweight stdlib HTTP server intended for demos and prototypes.
For production-like deployments, you typically want:

- a supervised process manager,
- structured logs,
- request IDs,
- and a separate model serving tier.

## Local

```bash
python -m clinicaflow.demo_server
```

- Demo UI: `http://127.0.0.1:8000/`
- OpenAPI: `http://127.0.0.1:8000/openapi.json`
- Metrics: `http://127.0.0.1:8000/metrics`
- Deep ping (inference; no PHI): `http://127.0.0.1:8000/ping?which=all`
- Probes: `GET /health`, `GET /ready`, `GET /live`

If `CLINICAFLOW_API_KEY` is set, `POST /triage` and `POST /triage_stream` require auth via `Authorization: Bearer ...` or `X-API-Key`.

## Docker

```bash
docker build -t clinicaflow .
docker run --rm -p 8000:8000 clinicaflow
```

Or:

```bash
docker compose up --build
```

Notes:

- The container runs the server as a non-root user.
- A Docker `HEALTHCHECK` probes `GET /health`.
- The demo server respects `PORT` when started via `python -m clinicaflow.demo_server` (useful for free hosting platforms).

## Free public deployment (bonus)

The competition offers bonus credit for a **public interactive live demo app**.
The repo is designed to deploy cleanly as a small Docker service without third‑party dependencies.

### Option A — Hugging Face Spaces (Docker)

1. Create a new Space → choose **Docker**.
2. Import from GitHub: `Amo-Zeng/clinicaflow-medgemma` (branch `main`).
3. In Space **Settings → Variables**, set (recommended):
   - `PORT=7860` (Hugging Face default)
   - `CLINICAFLOW_LOG_LEVEL=INFO`
   - `CLINICAFLOW_PHI_GUARD=true`
   - `CLINICAFLOW_REASONING_BACKEND=gradio_space`
   - `CLINICAFLOW_REASONING_BASE_URLS=https://senthil3226w-medgemma-4b-it.hf.space,https://majweldon-medgemma-4b-it.hf.space,https://echo3700-google-medgemma-4b-it.hf.space,https://noumanjavaid-google-medgemma-4b-it.hf.space,https://eminkarka1-cortix-medgemma.hf.space|predict`
   - `CLINICAFLOW_EVIDENCE_BACKEND=auto` (optional; best-effort citations)

Notes:

- For better stability than random public Spaces, you can instead use the Hugging Face router (token required):
  `CLINICAFLOW_REASONING_BACKEND=hf_inference` + `CLINICAFLOW_REASONING_API_KEY=<HF_TOKEN>`.
- Consider setting `CLINICAFLOW_API_KEY` to protect `POST /triage` endpoints if you share the URL widely.

### Option B — Koyeb (Docker)

Koyeb commonly offers a free tier for small web services.

1. Create a new Web Service → “Deploy from GitHub”.
2. Select `Amo-Zeng/clinicaflow-medgemma`.
3. Use Docker build (detects `Dockerfile` automatically).
4. Configure environment variables similarly to the Hugging Face list above.
5. Ensure the service listens on the platform-provided port (`PORT`), or set `PORT=8000` if required.

### Option C — GitHub Pages (static; no server)

This repo includes a GitHub Pages-ready **static live demo** under `public_demo/` that runs in the browser and calls
public MedGemma Gradio Spaces (best-effort).

- After enabling GitHub Pages for the repo (Settings → Pages → Source: “GitHub Actions”), the URL is typically:
  `https://amo-zeng.github.io/clinicaflow-medgemma/`
- The deploy workflow is `.github/workflows/pages.yml`.

## Suggested environment variables

- See `.env.example` for a complete list (including external reasoning backend knobs).

- `CLINICAFLOW_LOG_LEVEL=INFO`
- `CLINICAFLOW_JSON_LOGS=false`
- `CLINICAFLOW_DEBUG=false`
- `CLINICAFLOW_MAX_REQUEST_BYTES=262144`
- `CLINICAFLOW_POLICY_PACK_PATH=/path/to/site_policy_pack.json`
- `CLINICAFLOW_POLICY_TOPK=2`
- `CLINICAFLOW_CORS_ALLOW_ORIGIN=*`
- `CLINICAFLOW_API_KEY=` (optional; protects `POST /triage` + `POST /triage_stream`)

## Model serving

See `docs/MEDGEMMA_INTEGRATION.md` for connecting a MedGemma endpoint via an OpenAI-compatible server.

## Audit bundles

For QA/compliance workflows, you can persist an auditable bundle per run:

```bash
clinicaflow audit --input examples/sample_case.json --out-dir audits/run1
```

Use `--redact` to omit demographics/notes/image descriptions from the saved bundle.
