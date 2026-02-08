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

## Docker

```bash
docker build -t clinicaflow .
docker run --rm -p 8000:8000 clinicaflow
```

Or:

```bash
docker compose up --build
```

## Suggested environment variables

- `CLINICAFLOW_LOG_LEVEL=INFO`
- `CLINICAFLOW_DEBUG=false`
- `CLINICAFLOW_MAX_REQUEST_BYTES=262144`
- `CLINICAFLOW_POLICY_PACK_PATH=/path/to/site_policy_pack.json`
- `CLINICAFLOW_POLICY_TOPK=2`

## Model serving

See `docs/MEDGEMMA_INTEGRATION.md` for connecting a MedGemma endpoint via an OpenAI-compatible server.

